"""
Heatseeker Trading System — Capture Server

Receives screenshots from the Chrome extension and saves them to disk.
Runs on Justin's desktop, accessible via Tailscale.
"""

import os
import json
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS

from config import Config

app = Flask(__name__)
CORS(app)  # Allow Chrome extension to POST


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
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
    default_name = f'capture_{datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")}.png'
    filename = request.form.get('filename', default_name)
    date_str = request.form.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
    timestamp = request.form.get('timestamp', datetime.utcnow().isoformat())
    save_path_override = request.form.get('savePath', '')

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
    }

    meta_path = date_folder / f'{Path(filename).stem}.json'
    with open(str(meta_path), 'w') as f:
        json.dump(meta, f, indent=2)

    print(f'[Capture] Saved: {file_path} ({meta["file_size"]} bytes)')

    return jsonify({
        'status': 'ok',
        'filename': filename,
        'path': str(file_path),
        'size': meta['file_size'],
        'timestamp': timestamp
    })


@app.route('/api/captures', methods=['GET'])
def list_captures():
    """List captures, optionally filtered by date."""
    date_str = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
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
        'timestamp': datetime.utcnow().isoformat(),
        'capture_path': str(base_path),
        'capture_path_exists': base_path.exists(),
        'total_captures': total_captures,
        'capture_dates': dates[:10],  # Last 10 days
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
