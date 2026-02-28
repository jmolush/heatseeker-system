"""
Grader Adapter — Converts Heatseeker scraper output to grader input format.

The grader expects:
  gex_nodes: [{"s": strike, "t": total_value}, ...]  (negative t = negative gamma)
  king_node: {"strike": X, "gex": Y}
  trinity_data: {"SPXW": {"king_node": ..., "price": ...}, "SPY": ..., "QQQ": ...}

Our scraper outputs:
  panels: [{"ticker": "SPXW", "price": X, "nodes": [{"strike": X, "value": X, "gamma_type": "positive"|"negative", ...}], "king_node": {...}}, ...]
"""

from typing import Dict, List, Optional, Tuple


def scraper_to_grader_nodes(panel: Dict) -> List[Dict]:
    """
    Convert a scraper panel's nodes to grader gex_nodes format.
    
    Scraper: {"strike": 690, "value": 14196600, "gamma_type": "positive", ...}
    Grader:  {"s": 690, "t": 14196600}  (negative t for negative gamma)
    
    Key insight: Skylit shows absolute values with color for sign.
    If gamma_type is "negative", the value represents negative gamma exposure,
    so we negate the value for the grader.
    """
    nodes = []
    for node in panel.get('nodes', []):
        strike = node.get('strike', 0)
        value = node.get('value', 0)
        gamma_type = node.get('gamma_type', 'unknown')
        
        # Skip zero-value nodes to reduce noise
        if value == 0:
            continue
        
        # Apply sign based on gamma type
        # positive gamma = absorption/pinning = positive GEX
        # negative gamma = amplification = negative GEX
        if gamma_type == 'negative':
            t = -abs(value)
        elif gamma_type == 'positive':
            t = abs(value)
        else:
            # Unknown/neutral — use the raw value (could be either)
            t = value
        
        nodes.append({"s": strike, "t": t})
    
    return nodes


def scraper_to_grader_king(panel: Dict) -> Optional[Dict]:
    """
    Convert scraper king_node to grader format.
    
    Scraper: {"strike": 690, "value": 14196600, "gamma_type": "positive"}
    Grader:  {"strike": 690, "gex": 14196600}
    """
    king = panel.get('king_node')
    if not king:
        return None
    
    value = king.get('value', 0)
    gamma_type = king.get('gamma_type', 'unknown')
    
    # Apply sign
    if gamma_type == 'negative':
        gex = -abs(value)
    elif gamma_type == 'positive':
        gex = abs(value)
    else:
        gex = value
    
    return {
        "strike": king.get('strike', 0),
        "gex": gex
    }


def scraper_to_trinity_data(scraped_data: Dict) -> Dict:
    """
    Convert full scraper output to trinity_data format for the grader.
    
    Returns: {"SPXW": {"king_node": {...}, "price": X}, "SPY": ..., "QQQ": ..., "VIX": ...}
    """
    trinity = {}
    
    for panel in scraped_data.get('panels', []):
        ticker = panel.get('ticker', '')
        if ticker not in ('SPXW', 'SPY', 'QQQ', 'VIX'):
            continue
        
        king = scraper_to_grader_king(panel)
        
        trinity[ticker] = {
            "price": panel.get('price', 0),
            "change_pct": panel.get('change_pct', 0),
            "king_node": king,
            "node_count": panel.get('node_count', 0),
        }
    
    return trinity


def compute_velocity_from_captures(current_nodes: List[Dict], 
                                     prev_1m: List[Dict] = None,
                                     prev_5m: List[Dict] = None, 
                                     prev_10m: List[Dict] = None) -> Dict:
    """
    Compute velocity (rate of change) by comparing current nodes to previous captures.
    
    Returns: {"1m": growth_rate, "5m": growth_rate, "10m": growth_rate}
    
    Growth rate = (current_total - previous_total) / previous_total
    """
    velocity = {}
    
    current_total = sum(abs(n.get('t', 0)) for n in current_nodes)
    
    for label, prev in [("1m", prev_1m), ("5m", prev_5m), ("10m", prev_10m)]:
        if prev is None:
            velocity[label] = 0
            continue
        prev_total = sum(abs(n.get('t', 0)) for n in prev)
        if prev_total == 0:
            velocity[label] = 0
        else:
            velocity[label] = (current_total - prev_total) / prev_total
    
    return velocity


def prepare_grader_input(scraped_data: Dict, 
                          ticker: str = "SPY",
                          direction: str = "LONG",
                          expiry: str = None,
                          prev_captures: Dict = None) -> Dict:
    """
    Prepare full grader input from a single scraper capture.
    
    Args:
        scraped_data: Full scraper output (all 4 panels)
        ticker: Which panel to grade (SPY, QQQ, SPXW)
        direction: LONG or SHORT
        expiry: Option expiry date (YYYY-MM-DD)
        prev_captures: {"1m": scraped_data, "5m": ..., "10m": ...} for velocity
    
    Returns: Dict ready to pass to grade_dual()
    """
    # Find the target panel
    target_panel = None
    for panel in scraped_data.get('panels', []):
        if panel.get('ticker') == ticker:
            target_panel = panel
            break
    
    if not target_panel:
        return None
    
    price = target_panel.get('price', 0)
    gex_nodes = scraper_to_grader_nodes(target_panel)
    king_node = scraper_to_grader_king(target_panel)
    trinity_data = scraper_to_trinity_data(scraped_data)
    
    # Compute velocity if previous captures provided
    velocity = {}
    if prev_captures:
        prev_nodes = {}
        for tf, prev_data in prev_captures.items():
            for panel in prev_data.get('panels', []):
                if panel.get('ticker') == ticker:
                    prev_nodes[tf] = scraper_to_grader_nodes(panel)
                    break
        
        velocity = compute_velocity_from_captures(
            gex_nodes,
            prev_1m=prev_nodes.get('1m'),
            prev_5m=prev_nodes.get('5m'),
            prev_10m=prev_nodes.get('10m')
        )
    
    # Extract VIX data for context
    vix_panel = None
    for panel in scraped_data.get('panels', []):
        if panel.get('ticker') == 'VIX':
            vix_panel = panel
            break
    
    vix_nodes = scraper_to_grader_nodes(vix_panel) if vix_panel else []
    
    return {
        "ticker": ticker,
        "price": price,
        "gex_nodes": gex_nodes,
        "vex_nodes": vix_nodes,  # Use VIX gamma as VEX proxy for now
        "king_node": king_node,
        "velocity": velocity,
        "trinity_data": trinity_data,
        "direction": direction,
        "expiry": expiry,
    }


def grade_capture(scraped_data: Dict,
                   ticker: str = "SPY",
                   direction: str = "LONG",
                   expiry: str = None,
                   prev_captures: Dict = None) -> Optional[Dict]:
    """
    Grade a capture end-to-end: scraper data → adapter → grader → result.
    
    This is the main entry point for the analysis pipeline.
    """
    from grader import grade_dual
    
    inputs = prepare_grader_input(scraped_data, ticker, direction, expiry, prev_captures)
    if not inputs:
        return None
    
    result = grade_dual(
        ticker=inputs['ticker'],
        price=inputs['price'],
        gex_nodes=inputs['gex_nodes'],
        vex_nodes=inputs['vex_nodes'],
        king_node=inputs['king_node'],
        velocity=inputs['velocity'],
        trinity_data=inputs['trinity_data'],
        direction=inputs['direction'],
        expiry=inputs['expiry'],
    )
    
    return result
