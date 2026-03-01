"""
Grader Adapter v3 — Converts Heatseeker scraper output to grader input format.

The grader expects:
  gex_nodes: [{"s": strike, "t": total_value}, ...]  (negative t = negative gamma)
  king_node: {"strike": X, "gex": Y}
  trinity_data: {"SPXW": {"king_node": ..., "price": ...}, ...}

Our scraper outputs:
  panels: [{"ticker": "SPXW", "nodes": [...], "king_node": {...}}, ...]

This module bridges the two formats and provides the main entry point.
"""

from typing import Dict, List, Optional


def scraper_to_grader_nodes(panel: Dict) -> List[Dict]:
    """
    Convert scraper panel nodes to grader format.
    
    Scraper: {"strike": 690, "value": 14196600, "gamma_type": "positive", ...}
    Grader:  {"s": 690, "t": 14196600}  (negative t for negative gamma)
    """
    nodes = []
    for node in panel.get("nodes", []):
        strike = node.get("strike", 0)
        value = node.get("value", 0)
        gamma_type = node.get("gamma_type", "unknown")

        if value == 0:
            continue

        # Apply sign based on gamma type
        if gamma_type == "negative":
            t = -abs(value)
        elif gamma_type == "positive":
            t = abs(value)
        else:
            t = value  # unknown — use raw

        nodes.append({"s": strike, "t": t})

    return nodes


def scraper_to_grader_king(panel: Dict) -> Optional[Dict]:
    """
    Convert scraper king_node to grader format.
    
    Scraper: {"strike": 690, "value": 14196600, "gamma_type": "positive"}
    Grader:  {"strike": 690, "gex": 14196600}
    """
    king = panel.get("king_node")
    if not king:
        return None

    value = king.get("value", 0)
    gamma_type = king.get("gamma_type", "unknown")

    if gamma_type == "negative":
        gex = -abs(value)
    elif gamma_type == "positive":
        gex = abs(value)
    else:
        gex = value

    return {"strike": king.get("strike", 0), "gex": gex}


def scraper_to_trinity_data(scraped_data: Dict) -> Dict:
    """
    Convert full scraper output to trinity_data for cross-index grading.
    
    For Trinity Mode: includes SPXW, SPY, QQQ, VIX panels.
    For Individual Mode: includes whichever single ticker is present.
    """
    trinity = {}
    mode = scraped_data.get("mode", "single")
    
    for panel in scraped_data.get("panels", []):
        ticker = panel.get("ticker", "")
        
        # In trinity mode, only include known index tickers
        # In individual mode, include whatever ticker we have
        if mode in ("trinity", "trinity_plus", "dual"):
            if ticker not in ("SPXW", "SPY", "QQQ", "VIX"):
                continue
        
        trinity[ticker] = {
            "price": panel.get("price", 0),
            "change_pct": panel.get("change_pct", 0),
            "king_node": scraper_to_grader_king(panel),
            "node_count": panel.get("node_count", 0),
        }
    return trinity


def compute_velocity(current_nodes, prev_1m=None, prev_5m=None, prev_10m=None):
    """
    Compute rate of change by comparing current vs previous captures.
    
    Returns: {"1m": rate, "5m": rate, "10m": rate}
    """
    current_total = sum(abs(n.get("t", 0)) for n in current_nodes)
    velocity = {}
    for label, prev in [("1m", prev_1m), ("5m", prev_5m), ("10m", prev_10m)]:
        if prev is None:
            velocity[label] = 0
        else:
            prev_total = sum(abs(n.get("t", 0)) for n in prev)
            velocity[label] = (current_total - prev_total) / prev_total if prev_total else 0
    return velocity


def prepare_grader_input(scraped_data: Dict, ticker: str = "SPY",
                         direction: str = "LONG", expiry: str = None,
                         prev_captures: Dict = None,
                         previous_king: Dict = None) -> Optional[Dict]:
    """
    Prepare full grader input from a single scraper capture.
    
    Args:
        scraped_data: Full scraper output (all 4 panels)
        ticker: Which panel to grade (SPY, QQQ, SPXW)
        direction: LONG or SHORT
        expiry: Option expiry (YYYY-MM-DD) for swing grading
        prev_captures: {"1m": scraped_data, "5m": ..., "10m": ...} for velocity
        previous_king: King node from previous capture for stability check
    """
    target_panel = None
    for panel in scraped_data.get("panels", []):
        if panel.get("ticker") == ticker:
            target_panel = panel
            break

    if not target_panel:
        return None

    price = target_panel.get("price") or scraped_data.get("individual_price") or 0
    gex_nodes = scraper_to_grader_nodes(target_panel)
    king_node = scraper_to_grader_king(target_panel)
    trinity_data = scraper_to_trinity_data(scraped_data)

    # Compute velocity if previous captures provided
    velocity = {}
    if prev_captures:
        prev_nodes = {}
        for tf, prev_data in prev_captures.items():
            for p in prev_data.get("panels", []):
                if p.get("ticker") == ticker:
                    prev_nodes[tf] = scraper_to_grader_nodes(p)
                    break
        velocity = compute_velocity(
            gex_nodes,
            prev_1m=prev_nodes.get("1m"),
            prev_5m=prev_nodes.get("5m"),
            prev_10m=prev_nodes.get("10m"),
        )

    # VEX: currently no vanna data — pass empty list
    # When vanna scraping is added, extract vanna panel nodes here
    vex_nodes = []

    return {
        "ticker": ticker,
        "price": price,
        "gex_nodes": gex_nodes,
        "vex_nodes": vex_nodes,
        "king_node": king_node,
        "velocity": velocity,
        "trinity_data": trinity_data,
        "direction": direction,
        "expiry": expiry,
        "previous_king": previous_king,
    }


def grade_capture(scraped_data: Dict, ticker: str = "SPY",
                  direction: str = "LONG", expiry: str = None,
                  prev_captures: Dict = None,
                  previous_king: Dict = None) -> Optional[Dict]:
    """
    Grade a capture end-to-end: scraper data -> adapter -> grader -> result.
    Main entry point for the pipeline.
    """
    from grader import grade_dual

    inputs = prepare_grader_input(
        scraped_data, ticker, direction, expiry, prev_captures, previous_king
    )
    if not inputs:
        return None

    return grade_dual(
        ticker=inputs["ticker"],
        price=inputs["price"],
        gex_nodes=inputs["gex_nodes"],
        vex_nodes=inputs["vex_nodes"],
        king_node=inputs["king_node"],
        velocity=inputs["velocity"],
        trinity_data=inputs["trinity_data"],
        direction=inputs["direction"],
        expiry=inputs["expiry"],
        previous_king=inputs["previous_king"],
    )


def should_analyze(grade_result: Dict, min_pct: float = 30.0) -> bool:
    """
    Pre-filter: should this grade warrant a full Claude analysis?
    Used by analyzer.py to skip low-quality captures and save tokens.
    """
    from grader import should_escalate_to_claude
    escalate, _ = should_escalate_to_claude(grade_result, min_intraday_pct=min_pct)
    return escalate


def grade_context_for_claude(grade_result: Dict) -> Optional[str]:
    """
    Format grade result as structured context to prepend to Claude analysis.
    Gives Claude quantitative data to anchor its qualitative analysis.
    """
    if not grade_result:
        return None

    i = grade_result.get("intraday", {})
    ib = i.get("breakdown", {})
    ticker = grade_result.get("ticker", "?")
    price = grade_result.get("price", 0)

    lines = [
        f"QUANTITATIVE PRE-ANALYSIS (Grader v3 — {ticker} @ ${price:,.2f}):",
        f"  Intraday Score: {i.get('score',0)}/{i.get('max',0)} ({i.get('pct',0):.1f}%) — {i.get('grade','?')}",
    ]

    # Key factors
    bz = ib.get("bounce_zone", {})
    if bz.get("nearest_strike"):
        lines.append(f"  Nearest Node: ${bz['nearest_strike']} ({bz.get('dist_pct','?')}% away)")

    kq = ib.get("king_quality", {})
    if kq.get("king_strike"):
        lines.append(f"  King: ${kq['king_strike']} ({kq.get('king_M','?')}M GEX, {kq.get('alignment','?')})")

    conc = ib.get("concentration", {})
    if conc.get("dominance"):
        lines.append(f"  Dominance: {conc['dominance']}x (top1 ${conc.get('top1','?')} vs top2 ${conc.get('top2','?')})")

    tr = ib.get("tradeable_range", {})
    if tr.get("range_pct"):
        lines.append(f"  Tradeable Range: {tr['range_pct']}%")

    trin = ib.get("trinity", {})
    if trin.get("alignment"):
        lines.append(f"  Trinity Alignment: {trin['alignment']}")

    # Warnings
    if grade_result.get("pinned", {}).get("pinned"):
        p = grade_result["pinned"]
        lines.append(f"  ⚠️ PINNED between ${p.get('below_wall','?')} and ${p.get('above_wall','?')}")

    pat = grade_result.get("pattern", "")
    if pat == "rainbow_road":
        lines.append("  ⚠️ RAINBOW ROAD pattern — scattered, avoid")
    elif pat == "stacked":
        lines.append("  ⚡ STACKED pattern — volatility spring potential")

    # Gatekeepers
    gk = grade_result.get("gatekeepers", {})
    if gk.get("nodes"):
        gk_strs = [f"${g['strike']} ({g['value_M']}M)" for g in gk["nodes"]]
        lines.append(f"  Gatekeepers: {', '.join(gk_strs)}")

    lines.append("")
    lines.append("Use this quantitative data to anchor your analysis. "
                 "The grader measures structure quality — you interpret meaning and recommend trades.")

    return "\n".join(lines)


def grade_all_panels(scraped_data: Dict, direction: str = "LONG",
                     prev_captures: Dict = None) -> Dict:
    """
    Grade ALL tradeable panels from a single capture.
    
    For Trinity Mode: grades SPXW, SPY, QQQ.
    For Individual Mode: grades whatever single ticker is present.
    
    Returns dict keyed by ticker.
    This is the recommended call — grade everything at once, compare.
    """
    from grader import should_escalate_to_claude

    results = {}
    best_ticker = None
    best_score = -1

    mode = scraped_data.get("mode", "single")
    
    # Determine which tickers to grade
    if mode == "individual":
        # Individual mode: grade the single ticker present
        tickers_to_grade = []
        individual_ticker = scraped_data.get("individual_ticker")
        if individual_ticker:
            tickers_to_grade = [individual_ticker]
        else:
            # Fallback: extract from panels
            for panel in scraped_data.get("panels", []):
                t = panel.get("ticker")
                if t:
                    tickers_to_grade.append(t)
    else:
        # Trinity mode: grade the standard index panels
        tickers_to_grade = ["SPXW", "SPY", "QQQ"]

    for ticker in tickers_to_grade:
        grade = grade_capture(scraped_data, ticker, direction, prev_captures=prev_captures)
        if grade:
            escalate, reason = should_escalate_to_claude(grade)
            grade["escalate_to_claude"] = escalate
            grade["escalate_reason"] = reason
            results[ticker] = grade

            intra_score = grade.get("intraday", {}).get("score", 0)
            if intra_score > best_score:
                best_score = intra_score
                best_ticker = ticker

    if best_ticker:
        results["best"] = best_ticker
        results["summary"] = {
            "best_ticker": best_ticker,
            "best_score": best_score,
            "panel_count": len([k for k in results if k not in ("best", "summary")]),
            "mode": mode,
            "escalate_any": any(
                v.get("escalate_to_claude") for k, v in results.items()
                if k not in ("best", "summary")
            ),
        }

    return results
