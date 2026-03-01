"""
Heatseeker Trading System — Capture Server

Receives screenshots from the Chrome extension and saves them to disk.
Runs on Justin's desktop, accessible via Tailscale.
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS

from config import Config
from vix_monitor import vix_monitor
from confluence import confluence, ConfluenceDetector
from rate_of_change import roc_tracker
from market_regime import regime_classifier

app = Flask(__name__)
CORS(app)  # Allow Chrome extension to POST


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'capture_path': str(Config.CAPTURE_BASE_PATH),
        'version': '0.1.0'
    })


@app.route('/api/capture', methods=['POST'])
def receive_capture():
    """
    Receive a screenshot from the Chrome extension.
    
    Expects multipart form data:
    - image: PNG file
    - filename: suggested filename
    - date: date string for subfolder (YYYY-MM-DD)
    - timestamp: ISO timestamp of capture
    - savePath: override base save path (from extension config)
    """
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400

    image_file = request.files['image']
    # Default filename uses dashes instead of colons (Windows-safe)
    default_name = f'capture_{datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")}.png'
    filename = request.form.get('filename', default_name)
    date_str = request.form.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    timestamp = request.form.get('timestamp', datetime.now(timezone.utc).isoformat())
    save_path_override = request.form.get('savePath', '')
    scraped_data_raw = request.form.get('scraped_data', '')

    # Parse scraped DOM data if provided
    scraped_data = None
    if scraped_data_raw:
        try:
            scraped_data = json.loads(scraped_data_raw)
        except json.JSONDecodeError:
            print('[Capture] Warning: could not parse scraped_data JSON')

    # Determine save location
    base_path = Path(save_path_override) if save_path_override else Config.CAPTURE_BASE_PATH
    date_folder = base_path / date_str
    date_folder.mkdir(parents=True, exist_ok=True)

    # Save the image
    file_path = date_folder / filename
    image_file.save(str(file_path))

    # Save metadata alongside
    meta = {
        'filename': filename,
        'timestamp': timestamp,
        'date': date_str,
        'file_size': os.path.getsize(str(file_path)),
        'save_path': str(file_path),
        'has_scraped_data': scraped_data is not None,
        'mode': scraped_data.get('mode', 'unknown') if scraped_data else 'screenshot_only',
    }
    
    # Include individual ticker info in metadata
    if scraped_data and scraped_data.get('individual_ticker'):
        meta['individual_ticker'] = scraped_data['individual_ticker']
        meta['individual_price'] = scraped_data.get('individual_price')
        meta['individual_change_pct'] = scraped_data.get('individual_change_pct')

    meta_path = date_folder / f'{Path(filename).stem}.json'
    with open(str(meta_path), 'w') as f:
        json.dump(meta, f, indent=2)

    # Save scraped DOM data separately (this is the cheap-to-analyze version)
    grade_results = None
    if scraped_data:
        scraped_path = date_folder / f'{Path(filename).stem}_data.json'
        with open(str(scraped_path), 'w') as f:
            json.dump(scraped_data, f, indent=2)
        node_count = scraped_data.get('total_nodes', 0)
        panel_count = scraped_data.get('panel_count', 0)
        print(f'[Capture] Saved: {file_path} ({meta["file_size"]} bytes) + scraped data ({panel_count} panels, {node_count} nodes)')

        # ── Auto-Grade on Capture ──────────────────────────────
        try:
            from grader_adapter import grade_all_panels
            from grader import format_grade_report, should_escalate_to_claude

            grade_results = grade_all_panels(scraped_data)

            # Print summary to console
            print(f'[Grader] {"="*50}')
            # Print all graded tickers (works for both Trinity and individual mode)
            for ticker, g in grade_results.items():
                if ticker in ("best", "summary"):
                    continue
                if not isinstance(g, dict) or "intraday" not in g:
                    continue
                i = g["intraday"]
                esc = "✅ ESCALATE" if g.get("escalate_to_claude") else "⏭️ skip"
                pat = g.get("pattern", "")
                pat_str = f" | {pat.upper()}" if pat not in ("mixed", "unknown") else ""
                pin_str = " | 📌PINNED" if g.get("pinned", {}).get("pinned") else ""
                print(f'[Grader] {ticker}: {i["score"]}/{i["max"]} '
                      f'({i["pct"]}%) {i["grade"]} | {esc}{pat_str}{pin_str}')

            # Print best panel detail
            best = grade_results.get("best")
            if best and best in grade_results:
                print(f'[Grader] Best: {best}')
                report = format_grade_report(grade_results[best])
                for line in report.split('\n'):
                    print(f'[Grader]   {line}')
            print(f'[Grader] {"="*50}')

            # Save grade alongside capture
            grade_path = date_folder / f'{Path(filename).stem}_grade.json'
            with open(str(grade_path), 'w') as f:
                # Strip non-serializable stuff, keep just the grades
                save_grades = {
                    k: v for k, v in grade_results.items()
                    if k not in ("best", "summary")
                }
                save_grades["_best"] = best
                save_grades["_summary"] = grade_results.get("summary", {})
                json.dump(save_grades, f, indent=2)
            print(f'[Grader] Saved: {grade_path}')

        except Exception as e:
            print(f'[Grader] Auto-grade failed: {e}')
            import traceback
            traceback.print_exc()

        # ── Auto-Analyze via Claude ────────────────────────────
        # Only triggers if best panel grades B+ or higher (50%+ intraday)
        # Threshold: B+ = 50% of max intraday score
        ANALYSIS_MIN_GRADE_PCT = 60.0  # A threshold

        best_ticker = grade_results.get("best") if grade_results else None
        best_grade = grade_results.get(best_ticker) if best_ticker and grade_results else None
        best_pct = best_grade.get("intraday", {}).get("pct", 0) if best_grade else 0

        if best_grade and best_pct >= ANALYSIS_MIN_GRADE_PCT:
            try:
                from analyzer import analyzer
                from grader import format_grade_report

                print(f'[Analyzer] Best panel {best_ticker} scored {best_pct:.1f}% '
                      f'(>= {ANALYSIS_MIN_GRADE_PCT}%) — sending to Claude...')

                analysis = analyzer.analyze(
                    image_path=str(file_path),
                    scraped_data=scraped_data,
                    grade_result=best_grade,
                    direction=best_grade.get("direction", "LONG"),
                    skip_if_low_grade=False,  # We already filtered by grade
                    min_grade_pct=0,
                )

                if analysis:
                    # Save analysis alongside capture
                    analysis_path = date_folder / f'{Path(filename).stem}_analysis.json'
                    with open(str(analysis_path), 'w') as f:
                        # Don't save base64 image data
                        save_analysis = {k: v for k, v in analysis.items() if k != '_image_b64'}
                        json.dump(save_analysis, f, indent=2)

                    if analysis.get('skipped_claude'):
                        print(f'[Analyzer] Claude skipped: {analysis.get("reason", "?")}')
                        print(f'[Analyzer] Grade-only report:')
                        if 'grade_report' in analysis:
                            for line in analysis['grade_report'].split('\n'):
                                print(f'[Analyzer]   {line}')
                    else:
                        model = analysis.get('_model', '?')
                        in_tok = analysis.get('_input_tokens', 0)
                        out_tok = analysis.get('_output_tokens', 0)
                        print(f'[Analyzer] ✅ Claude {model} analysis complete '
                              f'({in_tok} in / {out_tok} out tokens)')

                        # Print key parts of the analysis
                        if analysis.get('raw_analysis'):
                            # Truncate long raw analysis for console
                            raw = analysis['raw_analysis']
                            preview = raw[:500] + '...' if len(raw) > 500 else raw
                            print(f'[Analyzer] {"="*50}')
                            for line in preview.split('\n'):
                                print(f'[Analyzer]   {line}')
                            print(f'[Analyzer] {"="*50}')
                        elif analysis.get('parse_error'):
                            print(f'[Analyzer] (raw text, JSON parse failed)')
                        else:
                            # Structured JSON response — print key fields
                            print(f'[Analyzer] {"="*50}')
                            for key in ['thesis', 'recommendation', 'confidence',
                                        'trade_thesis', 'overall_bias', 'stand_aside']:
                                if key in analysis:
                                    val = analysis[key]
                                    if isinstance(val, dict):
                                        print(f'[Analyzer]   {key}:')
                                        for k, v in val.items():
                                            print(f'[Analyzer]     {k}: {v}')
                                    else:
                                        print(f'[Analyzer]   {key}: {val}')
                            print(f'[Analyzer] {"="*50}')

                    print(f'[Analyzer] Saved: {analysis_path}')

                    # Attach to response
                    response_data_analysis = {
                        'model': analysis.get('_model'),
                        'skipped': analysis.get('skipped_claude', False),
                        'tokens_in': analysis.get('_input_tokens', 0),
                        'tokens_out': analysis.get('_output_tokens', 0),
                    }
                    # Will be added to response_data below

                else:
                    print(f'[Analyzer] No API key or analysis returned None')
                    response_data_analysis = None

            except Exception as e:
                print(f'[Analyzer] Auto-analyze failed: {e}')
                import traceback
                traceback.print_exc()
                response_data_analysis = None
        elif best_grade:
            print(f'[Analyzer] Best panel {best_ticker} scored {best_pct:.1f}% '
                  f'(< {ANALYSIS_MIN_GRADE_PCT}%) — skipping Claude to save tokens')
            response_data_analysis = None
        else:
            response_data_analysis = None

    else:
        print(f'[Capture] Saved: {file_path} ({meta["file_size"]} bytes) [screenshot only, no DOM data]')
        response_data_analysis = None

    response_data = {
        'status': 'ok',
        'filename': filename,
        'path': str(file_path),
        'size': meta['file_size'],
        'timestamp': timestamp,
        'mode': scraped_data.get('mode', 'unknown') if scraped_data else 'screenshot_only',
    }

    # Include individual ticker info if present
    if scraped_data and scraped_data.get('individual_ticker'):
        response_data['individual_ticker'] = scraped_data['individual_ticker']
        response_data['individual_price'] = scraped_data.get('individual_price')
        response_data['individual_change_pct'] = scraped_data.get('individual_change_pct')
    if grade_results:
        # Include grade summary in response so extension could display it
        best = grade_results.get("best")
        if best and best in grade_results:
            bi = grade_results[best]["intraday"]
            response_data['grade'] = {
                'best_panel': best,
                'score': bi['score'],
                'max': bi['max'],
                'pct': bi['pct'],
                'grade': bi['grade'],
                'escalate': grade_results[best].get('escalate_to_claude', False),
                'pattern': grade_results[best].get('pattern', ''),
                'pinned': grade_results[best].get('pinned', {}).get('pinned', False),
            }

    if response_data_analysis:
        response_data['analysis'] = response_data_analysis

    return jsonify(response_data)


@app.route('/api/captures', methods=['GET'])
def list_captures():
    """List captures, optionally filtered by date."""
    date_str = request.args.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    base_path = Config.CAPTURE_BASE_PATH
    date_folder = base_path / date_str

    if not date_folder.exists():
        return jsonify({'date': date_str, 'captures': [], 'count': 0})

    captures = []
    for f in sorted(date_folder.glob('*.png')):
        meta_file = date_folder / f'{f.stem}.json'
        meta = {}
        if meta_file.exists():
            with open(str(meta_file)) as mf:
                meta = json.load(mf)

        captures.append({
            'filename': f.name,
            'path': str(f),
            'size': os.path.getsize(str(f)),
            'timestamp': meta.get('timestamp', ''),
        })

    return jsonify({
        'date': date_str,
        'captures': captures,
        'count': len(captures)
    })


@app.route('/api/captures/dates', methods=['GET'])
def list_capture_dates():
    """List all dates that have captures."""
    base_path = Config.CAPTURE_BASE_PATH
    if not base_path.exists():
        return jsonify({'dates': []})

    dates = sorted([
        d.name for d in base_path.iterdir()
        if d.is_dir() and len(d.name) == 10  # YYYY-MM-DD format
    ], reverse=True)

    return jsonify({'dates': dates})


@app.route('/api/config', methods=['GET'])
def get_config():
    """Return current server configuration (non-sensitive)."""
    return jsonify({
        'capture_base_path': str(Config.CAPTURE_BASE_PATH),
        'opend_host': Config.OPEND_HOST,
        'opend_port': Config.OPEND_PORT,
        'paper_trading_enabled': Config.PAPER_TRADING_ENABLED,
        'live_trading_enabled': Config.LIVE_TRADING_ENABLED,
        'tickers': Config.OPEND_TICKERS,
        'index_tickers': Config.INDEX_TICKERS,
        'market_window': {
            'open': Config.MARKET_OPEN_ET,
            'close': Config.MARKET_CLOSE_ET,
        }
    })


# ─── VIX Endpoints ────────────────────────────────────────────────

@app.route('/api/vix', methods=['GET'])
def get_vix():
    """Get current VIX state and regime."""
    current = vix_monitor.get_current()
    if not current:
        return jsonify({'error': 'VIX data unavailable', 'note': 'Market may be closed'}), 503
    return jsonify(current)


@app.route('/api/vix/context', methods=['GET'])
def get_vix_context():
    """Get VIX context formatted for analysis engine."""
    context = vix_monitor.get_context_for_analysis()
    return jsonify(context)


@app.route('/api/vix/intraday', methods=['GET'])
def get_vix_intraday():
    """Get VIX intraday candle data."""
    candles = vix_monitor.get_intraday_history()
    if not candles:
        return jsonify({'error': 'No intraday data', 'note': 'Market may be closed'}), 503
    return jsonify({'candles': candles, 'count': len(candles)})


@app.route('/api/vix/alerts', methods=['GET'])
def get_vix_alerts():
    """Get recent VIX alerts (spikes, regime changes)."""
    limit = request.args.get('limit', 20, type=int)
    return jsonify({'alerts': vix_monitor.get_alerts(limit=limit)})


# ─── Confluence Endpoints ─────────────────────────────────────────

@app.route('/api/confluence', methods=['GET'])
def get_confluence():
    """Get current cross-index confluence state."""
    result = confluence.check_confluence()
    return jsonify(result.to_dict())


@app.route('/api/confluence/history', methods=['GET'])
def get_confluence_history():
    """Get confluence check history."""
    limit = request.args.get('limit', 50, type=int)
    return jsonify({'history': confluence.get_history(limit=limit)})


@app.route('/api/confluence/trend', methods=['GET'])
def get_confluence_trend():
    """Get confluence trend (improving/deteriorating)."""
    trend = confluence.get_trend()
    if not trend:
        return jsonify({'error': 'Not enough data for trend analysis'}), 404
    return jsonify(trend)


# ─── Grader Endpoints ─────────────────────────────────────────────

@app.route('/api/grade', methods=['POST'])
def grade_capture_endpoint():
    """
    Grade a capture using the quantitative dual-timeframe grader.
    
    Expects JSON body with:
    - scraped_data: Full scraper output (all panels)
    - ticker: Which panel to grade (default: SPY, or "all" for all panels)
    - direction: LONG or SHORT (default: LONG)
    - expiry: Option expiry date (optional, YYYY-MM-DD)
    """
    from grader_adapter import grade_capture as do_grade, grade_all_panels
    from grader import format_grade_report

    data = request.get_json()
    if not data or 'scraped_data' not in data:
        return jsonify({'error': 'scraped_data required'}), 400

    ticker = data.get('ticker', 'SPY')
    direction = data.get('direction', 'LONG')
    expiry = data.get('expiry')

    # Grade all panels at once
    if ticker.lower() == 'all':
        results = grade_all_panels(data['scraped_data'], direction=direction)
        for t, r in results.items():
            r['report'] = format_grade_report(r)
        return jsonify({
            'panels': results,
            'count': len(results),
            'escalate_any': any(r.get('escalate_to_claude') for r in results.values()),
        })

    # Grade single panel
    result = do_grade(data['scraped_data'], ticker=ticker, direction=direction, expiry=expiry)
    if not result:
        return jsonify({'error': f'Panel {ticker} not found in scraped data'}), 404

    result['report'] = format_grade_report(result)
    return jsonify(result)


@app.route('/api/grade/latest', methods=['GET'])
def grade_latest_capture():
    """Grade the most recent capture — single ticker or all panels."""
    from grader_adapter import grade_capture as do_grade, grade_all_panels
    from grader import format_grade_report

    ticker = request.args.get('ticker', 'all')
    direction = request.args.get('direction', 'LONG')

    # Find most recent capture with scraped data
    date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    date_folder = Config.CAPTURE_BASE_PATH / date_str

    if not date_folder.exists():
        return jsonify({'error': 'No captures today'}), 404

    data_files = sorted(date_folder.glob('*_data.json'), reverse=True)
    if not data_files:
        return jsonify({'error': 'No scraped data files found today'}), 404

    with open(str(data_files[0])) as f:
        scraped_data = json.load(f)

    if ticker.lower() == 'all':
        results = grade_all_panels(scraped_data, direction=direction)
        for t, r in results.items():
            r['report'] = format_grade_report(r)
        return jsonify({
            'panels': results,
            'count': len(results),
            'source_file': str(data_files[0]),
            'escalate_any': any(r.get('escalate_to_claude') for r in results.values()),
        })

    result = do_grade(scraped_data, ticker=ticker, direction=direction)
    if not result:
        return jsonify({'error': f'Panel {ticker} not found'}), 404

    result['report'] = format_grade_report(result)
    result['source_file'] = str(data_files[0])
    return jsonify(result)


# ─── Rate of Change Endpoints ────────────────────────────────────

@app.route('/api/roc/alerts', methods=['GET'])
def get_roc_alerts():
    """Get rate-of-change alerts (accumulation, dissipation, reshuffles)."""
    symbol = request.args.get('symbol')
    limit = request.args.get('limit', 50, type=int)
    return jsonify({'alerts': roc_tracker.get_alerts(symbol=symbol, limit=limit)})


@app.route('/api/roc/summary/<symbol>', methods=['GET'])
def get_roc_summary(symbol):
    """Get rate-of-change summary for a specific index."""
    summary = roc_tracker.get_summary(symbol.upper())
    if not summary:
        return jsonify({'error': f'No data for {symbol}'}), 404
    return jsonify(summary)


# ─── Market Regime Endpoints ──────────────────────────────────────

@app.route('/api/regime', methods=['GET'])
def get_regime():
    """Get current market day type classification (trend/levels/whipsaw)."""
    symbol = request.args.get('symbol', 'SPY')
    result = regime_classifier.classify(symbol)
    return jsonify(result.to_dict())


@app.route('/api/regime/history', methods=['GET'])
def get_regime_history():
    """Get regime classification history (how the day evolved)."""
    return jsonify({'history': regime_classifier.get_history()})


@app.route('/api/regime/reclassified', methods=['GET'])
def get_regime_reclassified():
    """Check if the day type changed since last check."""
    change = regime_classifier.has_reclassified()
    if change:
        return jsonify(change)
    return jsonify({'reclassified': False})


# ─── Status Endpoint ─────────────────────────────────────────────

@app.route('/api/status', methods=['GET'])
def status():
    """Full status dashboard — useful for quick validation."""
    base_path = Config.CAPTURE_BASE_PATH
    total_captures = 0
    dates = []

    if base_path.exists():
        for d in sorted(base_path.iterdir(), reverse=True):
            if d.is_dir() and len(d.name) == 10:
                count = len(list(d.glob('*.png')))
                total_captures += count
                dates.append({'date': d.name, 'count': count})

    return jsonify({
        'status': 'ok',
        'version': '0.1.0',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'capture_path': str(base_path),
        'capture_path_exists': base_path.exists(),
        'total_captures': total_captures,
        'capture_dates': dates[:10],  # Last 10 days
        'vix': vix_monitor.get_context_for_analysis(),
        'confluence': confluence.check_confluence().to_dict() if confluence._states else None,
        'roc_alerts': roc_tracker.get_alerts(limit=5),
        'config': {
            'opend_host': Config.OPEND_HOST,
            'opend_port': Config.OPEND_PORT,
            'paper_trading': Config.PAPER_TRADING_ENABLED,
            'tickers': Config.OPEND_TICKERS,
        }
    })


if __name__ == '__main__':
    # Ensure capture directory exists
    Config.CAPTURE_BASE_PATH.mkdir(parents=True, exist_ok=True)
    print(f'[Heatseeker] Starting capture server on {Config.BACKEND_HOST}:{Config.BACKEND_PORT}')
    print(f'[Heatseeker] Captures saving to: {Config.CAPTURE_BASE_PATH}')
    app.run(
        host=Config.BACKEND_HOST,
        port=Config.BACKEND_PORT,
        debug=True
    )
