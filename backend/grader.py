#!/usr/bin/env python3
"""
Dual-Timeframe Grader v2
Quantitative grading for both INTRADAY (0-3 day) and SWING (4+ day) trades.

Adapted for Heatseeker system — expects gex_nodes as [{"s": strike, "t": value}]
where positive t = positive gamma (absorption) and negative t = negative gamma (amplification).

Outputs bullet-point breakdown for each factor to enable tuning.
"""

import math
import calendar
from datetime import datetime
from typing import Dict, List, Optional, Tuple


def normalize_velocity(velocity: float, max_val: float = 1.0) -> float:
    if max_val == 0:
        return 0.5
    normalized = max(-1, min(1, velocity / max_val))
    return (normalized + 1) / 2


def get_time_of_day_score() -> Tuple[int, str]:
    hour = datetime.now().hour
    minute = datetime.now().minute
    t = hour + minute / 60
    if 9.5 <= t < 10.0:
        return 2, "shuffle"
    elif 10.0 <= t < 11.5:
        return 10, "prime"
    elif 11.5 <= t < 14.0:
        return 4, "chop"
    elif 14.0 <= t < 15.5:
        return 8, "power_hour"
    elif 15.5 <= t <= 16.0:
        return 5, "close"
    return 0, "market_closed"


def grade_bounce_zone(price, gex_nodes, max_pct=0.02):
    if not gex_nodes or price <= 0:
        return 0, {"score": 0}
    max_dist = price * max_pct
    candidates = sorted([n for n in gex_nodes if n.get('t', 0) < 0], key=lambda n: n['s'], reverse=True)
    nearest = next((n['s'] for n in candidates if n['s'] < price), None)
    if nearest is None:
        return 0, {"score": 0}
    dist = price - nearest
    score = 25 * max(0, 1 - dist / max_dist)
    return score, {"score": round(score, 1), "bounce_strike": nearest, "distance_pct": round(dist / price * 100, 2)}


def grade_same_day_gex(price, gex_nodes):
    if not gex_nodes or price <= 0:
        return 0, {"score": 0, "concentration": 0, "distance_penalty": 0}
    current = gex_nodes[:50]
    same_w = sum(abs(n.get('t', 0)) for n in current)
    total_w = sum(abs(n.get('t', 0)) for n in gex_nodes)
    if total_w == 0:
        return 0, {"score": 0, "concentration": 0, "distance_penalty": 0}
    conc = same_w / total_w
    strikes = [n['s'] for n in current if n['s'] > 0]
    dp = min(abs(sum(strikes) / len(strikes) - price) / price, 0.5) if strikes else 0
    score = 20 * conc * (1 - dp)
    return score, {"score": round(score, 1), "concentration": round(conc * 100, 1), "distance_penalty": round(dp * 100, 1)}


def grade_king_alignment(price, king_node, direction="LONG"):
    if not king_node or price <= 0:
        return 0, {"score": 0, "alignment": None}
    ks = king_node.get('strike', 0)
    kg = king_node.get('gex', 0)
    if ks == 0:
        return 0, {"score": 0, "alignment": None}
    bull = direction == "LONG"
    above = ks > price
    wall = kg > 0
    if bull and above and wall:
        align = "bullish_aligned"
    elif not bull and not above and wall:
        align = "bearish_aligned"
    elif bull and not above:
        align = "against"
    elif not bull and above:
        align = "against"
    else:
        align = "neutral"
    dp = abs(ks - price) / price
    af = 1.0 if align in ("bullish_aligned", "bearish_aligned") else 0.0
    score = 20 * af * max(0, 1 - dp)
    return score, {"score": round(score, 1), "king_strike": ks, "king_gex": round(kg / 1e6, 2), "alignment": align, "distance_pct": round(dp * 100, 2)}


def grade_velocity(velocity, direction="LONG"):
    if not velocity:
        return 5, {"score": 5, "weighted_sum": 0, "breakdown": {}}
    weights = {"10m": 0.6, "5m": 0.3, "1m": 0.1}
    ws = sum(velocity.get(tf, 0) * w for tf, w in weights.items())
    score = 15 * normalize_velocity(ws, 0.5)
    return score, {"score": round(score, 1), "weighted_sum": round(ws * 100, 1), "breakdown": {k: round(velocity.get(k, 0) * 100, 1) for k in weights}}


def grade_historical_sr(price, levels=None):
    if not levels or price <= 0:
        return 3, {"score": 3, "confluence": "no_data"}
    levels = [float(x) for x in levels]
    nearest = min(levels, key=lambda x: abs(x - price))
    dp = abs(nearest - price) / price * 100
    if dp < 0.1:
        return 10, {"score": 10, "confluence": "exact", "nearest_level": nearest, "distance_pct": round(dp, 2)}
    elif dp < 0.5:
        return 7, {"score": 7, "confluence": "close", "nearest_level": nearest, "distance_pct": round(dp, 2)}
    elif dp < 1.0:
        return 4, {"score": 4, "confluence": "moderate", "nearest_level": nearest, "distance_pct": round(dp, 2)}
    elif dp < 2.0:
        return 2, {"score": 2, "confluence": "weak", "nearest_level": nearest, "distance_pct": round(dp, 2)}
    return 0, {"score": 0, "confluence": "none", "nearest_level": nearest, "distance_pct": round(dp, 2)}


def grade_trinity_alignment(trinity_data, ticker):
    if not trinity_data:
        return 3, {"score": 3, "alignment": "no_data"}
    dirs = []
    for idx in ['SPXW', 'SPY', 'QQQ']:
        td = trinity_data.get(idx, {})
        king = td.get('king_node', {})
        price = td.get('price', 0)
        if king and price:
            dirs.append(1 if king.get('strike', 0) > price else -1)
    if len(dirs) < 2:
        return 3, {"score": 3, "alignment": "insufficient_data", "directions": dirs}
    if all(d == dirs[0] for d in dirs):
        return 10, {"score": 10, "alignment": "aligned", "directions": dirs}
    elif dirs.count(1) == 2:
        return 6, {"score": 6, "alignment": "lean_bullish", "directions": dirs}
    elif dirs.count(-1) == 2:
        return 6, {"score": 6, "alignment": "lean_bearish", "directions": dirs}
    return 0, {"score": 0, "alignment": "divergent", "directions": dirs}


# --- Swing ---

def grade_vex_direction(price, vex_nodes, direction="LONG"):
    if not vex_nodes or price <= 0:
        return 0, {"score": 0, "alignment": None}
    up = sum(n.get('t', 0) for n in vex_nodes if n.get('s', 0) > price)
    down = sum(n.get('t', 0) for n in vex_nodes if n.get('s', 0) < price)
    vd = 1 if (up + down) > 0 else -1
    aligned = (direction == "LONG" and vd == 1) or (direction == "SHORT" and vd == -1)
    return (25 if aligned else 0), {"score": 25 if aligned else 0, "alignment": "aligned" if aligned else "opposed", "upside_vex": round(up / 1e6, 2), "downside_vex": round(down / 1e6, 2)}


def grade_vex_significance(vex_nodes):
    if not vex_nodes:
        return 0, {"score": 0, "significance": 0}
    mx = max(abs(n.get('t', 0)) for n in vex_nodes)
    total = sum(abs(n.get('t', 0)) for n in vex_nodes)
    if total == 0:
        return 0, {"score": 0, "significance": 0}
    sig = mx / total
    return round(20 * sig, 1), {"score": round(20 * sig, 1), "significance": round(sig * 100, 1), "max_vex": round(mx / 1e6, 2)}


def grade_gex_current_week(gex_nodes, price):
    if not gex_nodes or price <= 0:
        return 0, {"score": 0}
    cw = sum(n.get('t', 0) for n in gex_nodes[:50])
    total = sum(n.get('t', 0) for n in gex_nodes)
    if total == 0:
        return 0, {"score": 0}
    ratio = abs(cw) / abs(total)
    return round(15 * ratio, 1), {"score": round(15 * ratio, 1), "ratio": round(ratio * 100, 1)}


def grade_dte(expiry, entry_date=None):
    if not expiry:
        return 5, {"score": 5, "dte": None, "category": "unknown"}
    entry_date = entry_date or datetime.now().strftime("%Y-%m-%d")
    try:
        dte = (datetime.strptime(expiry, "%Y-%m-%d") - datetime.strptime(entry_date, "%Y-%m-%d")).days
    except Exception:
        return 5, {"score": 5, "dte": None, "category": "parse_error"}
    if dte <= 3:
        return 2, {"score": 2, "dte": dte, "category": "very_short"}
    elif dte <= 7:
        return 5, {"score": 5, "dte": dte, "category": "short"}
    elif dte <= 14:
        return 8, {"score": 8, "dte": dte, "category": "medium"}
    return 10, {"score": 10, "dte": dte, "category": "long"}


def grade_king_stability(current_king, previous_king=None):
    if not current_king:
        return 5, {"score": 5, "stability": "no_king"}
    ks = current_king.get('strike', 0)
    if previous_king is None:
        return 12, {"score": 12, "stability": "stable", "unchanged": True, "king_strike": ks}
    unchanged = ks == previous_king.get('strike', 0)
    score = 15 if unchanged else 7.5
    return score, {"score": score, "stability": "stable" if unchanged else "moved", "unchanged": unchanged, "king_strike": ks}


# --- v2: Freshness, Gatekeepers, Alignment, Patterns, OPEX ---

def is_opex_week():
    now = datetime.now()
    cal = calendar.Calendar(firstweekday=0)
    fridays = [d for week in cal.monthdayscalendar(now.year, now.month) for i, d in enumerate(week) if i == 4 and d != 0]
    if len(fridays) >= 3:
        opex = fridays[2]
        delta = opex - now.day
        if -7 <= delta <= 0:
            return True, f"OPEX WEEK (Fri {now.month}/{opex})"
        if 0 < delta <= 7:
            return True, f"PRE-OPEX ({delta}d to {now.month}/{opex})"
    return False, "Normal trading week"


def detect_pattern(price, gex_nodes):
    if not gex_nodes or price <= 0:
        return "unknown", {"pattern": "no_data"}
    sig = sorted(gex_nodes, key=lambda n: abs(n.get('t', 0)), reverse=True)[:20]
    if len(sig) < 5:
        return "insufficient_data", {"pattern": "too_few_nodes"}
    strikes = [n['s'] for n in sig if n['s'] > 0]
    if not strikes:
        return "unknown", {"pattern": "no_valid_strikes"}
    spread = (max(strikes) - min(strikes)) / price * 100
    pc = sum(1 for n in sig if n.get('t', 0) > 0)
    nc = sum(1 for n in sig if n.get('t', 0) < 0)
    if spread > 15 and pc >= 3 and nc >= 3:
        return "rainbow_road", {"pattern": "rainbow_road", "spread_pct": round(spread, 1), "recommendation": "AVOID - chop likely"}
    if spread < 8:
        below = [n for n in sig if n['s'] < price]
        above = [n for n in sig if n['s'] > price]
        if below and above:
            return "clean_range", {"pattern": "clean_range", "spread_pct": round(spread, 1), "recommendation": "TRADEABLE - clear range"}
    for p in sorted([n for n in sig if n.get('t', 0) > 0], key=lambda n: n['s'])[:5]:
        for n in sorted([n for n in sig if n.get('t', 0) < 0], key=lambda n: n['s'], reverse=True)[:5]:
            if abs(p['s'] - n['s']) / price < 0.02:
                return "stacked", {"pattern": "stacked", "pos_strike": p['s'], "neg_strike": n['s'], "recommendation": "VOLATILITY SPRING"}
    return "mixed", {"pattern": "mixed", "spread_pct": round(spread, 1), "recommendation": "Normal conditions"}


def find_gatekeepers(price, gex_nodes, king_node):
    if not gex_nodes or price <= 0:
        return [], {"gatekeepers": [], "count": 0}
    ks = king_node.get('strike', 0) if king_node else 0
    up = ks > price
    gk = []
    for n in gex_nodes:
        s, v = n.get('s', 0), n.get('t', 0)
        if up and price < s < ks:
            gk.append({'strike': s, 'value': v, 'type': 'resistance'})
        elif not up and ks < s < price:
            gk.append({'strike': s, 'value': v, 'type': 'support'})
    gk = sorted(gk, key=lambda n: abs(n['value']), reverse=True)[:3]
    return gk, {"gatekeepers": gk, "count": len(gk), "king_strike": ks, "direction": "up" if up else "down"}


def grade_gatekeeper_situation(price, gatekeepers, king_node):
    if not gatekeepers:
        return 8, {"score": 8, "situation": "no_gatekeeper", "description": "Clear path to King", "trim_recommendation": "NONE"}
    kv = abs(king_node.get('gex', 0)) if king_node else 0
    strongest = max(abs(g['value']) for g in gatekeepers)
    gs = gatekeepers[0]['strike']
    if strongest > kv * 0.5:
        dp = abs(gs - price) / price * 100
        return 15, {"score": 15, "situation": "strong_gatekeeper", "gatekeeper_strike": gs, "gatekeeper_value": round(strongest / 1e6, 1), "distance_pct": round(dp, 2), "description": f"GATEKEEPER AT ${gs}", "trim_recommendation": "TRIM 1/3 AT GATEKEEPER"}
    return 10, {"score": 10, "situation": "weak_gatekeeper", "gatekeeper_strike": gs, "description": f"Gatekeeper at ${gs} - King likely holds", "trim_recommendation": "MONITOR"}


def grade_gex_vex_alignment(gex_nodes, vex_nodes, price, timeframe="intraday"):
    if not gex_nodes or not vex_nodes:
        return 5, {"alignment": "no_data", "score": 5}
    gb = sum(n.get('t', 0) for n in gex_nodes if n.get('s', 0) < price)
    ga = sum(n.get('t', 0) for n in gex_nodes if n.get('s', 0) > price)
    vb = sum(n.get('t', 0) for n in vex_nodes if n.get('s', 0) < price)
    va = sum(n.get('t', 0) for n in vex_nodes if n.get('s', 0) > price)
    gd = 1 if gb > ga else -1
    vd = 1 if vb > va else -1
    aligned = gd == vd
    if gd == 1 and vd == 1:
        at = "bullish_aligned"
    elif gd == -1 and vd == -1:
        at = "bearish_aligned"
    elif gd == 1:
        at = "mixed_gamma_bullish"
    else:
        at = "mixed_gamma_bearish"
    if aligned:
        base = 20 if timeframe == "swing" else 15
        strength = abs(gb - ga) / (abs(gb) + abs(ga) + 1)
        score = base * (0.5 + strength * 0.5)
    else:
        score = (10 if timeframe == "swing" else 8) * 0.5
    return round(score, 1), {"score": round(score, 1), "alignment": at, "aligned": aligned}


def grade_node_freshness(price, gex_nodes):
    if not gex_nodes or price <= 0:
        return 5, {"freshness": "no_data", "score": 5}
    sig = sorted(gex_nodes, key=lambda n: abs(n.get('t', 0)), reverse=True)[:10]
    dists = [{"strike": n['s'], "dist_pct": abs(n['s'] - price) / price * 100, "nearest": abs(n['s'] - price) / price * 100 < 2} for n in sig if n['s'] > 0]
    nearby = sum(1 for d in dists if d['nearest'])
    if nearby >= 3:
        return 15, {"score": 15, "freshness": "highly_fresh", "nearby_nodes": nearby, "description": "Multiple significant nodes near price"}
    elif nearby == 2:
        return 12, {"score": 12, "freshness": "fresh", "nearby_nodes": nearby, "description": "Two significant nodes near price"}
    elif nearby == 1:
        return 8, {"score": 8, "freshness": "single_node", "nearby_nodes": nearby, "description": "One significant node nearby"}
    md = min(d['dist_pct'] for d in dists) if dists else 100
    if md > 5:
        return 4, {"score": 4, "freshness": "delivered_from", "nearby_nodes": 0, "description": "Price has moved away from key nodes"}
    return 6, {"score": 6, "freshness": "moderate", "nearby_nodes": 0, "description": "Moderate distance from key nodes"}


# ============================================================================
# MAIN DUAL GRADER
# ============================================================================

def grade_dual(ticker, price, gex_nodes, vex_nodes=None, king_node=None,
               velocity=None, trinity_data=None, direction="LONG",
               expiry=None, entry_date=None, historical_sr=None,
               previous_king=None):
    """Calculate both INTRADAY and SWING grades with full breakdown."""

    vex_nodes = vex_nodes or []
    velocity = velocity or {}
    trinity_data = trinity_data or {}

    # --- INTRADAY ---
    bounce_s, bounce_d = grade_bounce_zone(price, gex_nodes)
    gex_s, gex_d = grade_same_day_gex(price, gex_nodes)
    king_s, king_d = grade_king_alignment(price, king_node, direction)
    vel_s, vel_d = grade_velocity(velocity, direction)
    tod_s, tod_phase = get_time_of_day_score()
    trinity_s, trinity_d = grade_trinity_alignment(trinity_data, ticker)
    hist_s, hist_d = grade_historical_sr(price, historical_sr)
    fresh_s, fresh_d = grade_node_freshness(price, gex_nodes)
    align_s, align_d = grade_gex_vex_alignment(gex_nodes, vex_nodes, price, "intraday")
    gk_list, gk_info = find_gatekeepers(price, gex_nodes, king_node)
    gk_s, gk_d = grade_gatekeeper_situation(price, gk_list, king_node)
    pattern, pattern_d = detect_pattern(price, gex_nodes)
    is_opex, opex_desc = is_opex_week()

    intraday_total = bounce_s + gex_s + king_s + vel_s + tod_s + trinity_s + hist_s + fresh_s + align_s + gk_s

    # --- SWING ---
    vex_dir_s, vex_dir_d = grade_vex_direction(price, vex_nodes, direction)
    vex_sig_s, vex_sig_d = grade_vex_significance(vex_nodes)
    swing_hist_s = min(hist_s * 1.5, 15)
    dte_s, dte_d = grade_dte(expiry, entry_date)
    king_stab_s, king_stab_d = grade_king_stability(king_node, previous_king)
    gex_cw_s, gex_cw_d = grade_gex_current_week(gex_nodes, price)
    swing_align_s, swing_align_d = grade_gex_vex_alignment(gex_nodes, vex_nodes, price, "swing")
    swing_fresh_s = fresh_s * 0.7
    swing_gk_s = gk_s * 0.7

    swing_total = vex_dir_s + vex_sig_s + swing_hist_s + dte_s + king_stab_s + gex_cw_s + swing_align_s + swing_fresh_s + swing_gk_s

    def letter(s):
        if s >= 80: return "A+"
        if s >= 65: return "A"
        if s >= 50: return "B+"
        if s >= 35: return "B"
        if s >= 20: return "C"
        return "F"

    return {
        "ticker": ticker,
        "timestamp": datetime.now().isoformat(),
        "opex_week": is_opex,
        "opex_description": opex_desc,
        "pattern": pattern,
        "pattern_details": pattern_d,
        "intraday": {
            "score": round(intraday_total, 1),
            "grade": letter(intraday_total),
            "breakdown": {
                "bounce_zone": bounce_d,
                "same_day_gex": gex_d,
                "king_alignment": king_d,
                "velocity": vel_d,
                "time_of_day": {"score": tod_s, "phase": tod_phase},
                "trinity": trinity_d,
                "historical_sr": hist_d,
                "node_freshness": fresh_d,
                "gex_vex_alignment": align_d,
                "gatekeeper": gk_d,
            }
        },
        "swing": {
            "score": round(swing_total, 1),
            "grade": letter(swing_total),
            "breakdown": {
                "vex_direction": vex_dir_d,
                "vex_significance": vex_sig_d,
                "historical_sr": {**hist_d, "weighted_score": round(swing_hist_s, 1)},
                "dte": dte_d,
                "king_stability": king_stab_d,
                "gex_current_week": gex_cw_d,
                "gex_vex_alignment": swing_align_d,
                "node_freshness": {**fresh_d, "weighted_score": round(swing_fresh_s, 1)},
                "gatekeeper": {**gk_d, "weighted_score": round(swing_gk_s, 1)},
            }
        }
    }


def format_grade_report(data):
    """Format grade report for display."""
    ticker = data["ticker"]
    intra = data["intraday"]
    swing = data["swing"]
    warnings = []
    if data.get("opex_week"):
        warnings.append(f"⚠️ {data.get('opex_description')}")
    if data.get("pattern") == "rainbow_road":
        warnings.append("🌈 RAINBOW ROAD - AVOID")
    elif data.get("pattern") == "stacked":
        warnings.append("⚡ STACKED - vol spring")

    lines = [f"**{ticker}** | {datetime.now().strftime('%m/%d %I:%M %p')}"]
    if warnings:
        lines.append(" ".join(warnings))
    bd = intra["breakdown"]
    lines.extend([
        f"\n**INTRADAY: {intra['score']} ({intra['grade']})**",
        f"  Bounce Zone: {bd['bounce_zone']['score']}/25",
        f"  Same-Day GEX: {bd['same_day_gex']['score']}/20",
        f"  King Alignment: {bd['king_alignment']['score']}/20 ({bd['king_alignment'].get('alignment', 'N/A')})",
        f"  Velocity: {bd['velocity']['score']}/15",
        f"  Time of Day: {bd['time_of_day']['score']}/10 ({bd['time_of_day']['phase']})",
        f"  Trinity: {bd['trinity']['score']}/10 ({bd['trinity'].get('alignment', 'N/A')})",
        f"  Historical S/R: {bd['historical_sr']['score']}/10",
        f"  Node Freshness: {bd['node_freshness']['score']}/15 ({bd['node_freshness'].get('freshness', 'N/A')})",
        f"  GEX/VEX Align: {bd['gex_vex_alignment']['score']}/15 ({bd['gex_vex_alignment'].get('alignment', 'N/A')})",
        f"  Gatekeeper: {bd['gatekeeper']['score']}/15 ({bd['gatekeeper'].get('situation', 'N/A')})",
    ])
    sd = swing["breakdown"]
    lines.extend([
        f"\n**SWING: {swing['score']} ({swing['grade']})**",
        f"  VEX Direction: {sd['vex_direction']['score']}/25 ({sd['vex_direction'].get('alignment', 'N/A')})",
        f"  VEX Significance: {sd['vex_significance']['score']}/20",
        f"  Historical S/R: {sd['historical_sr']['weighted_score']}/15",
        f"  DTE: {sd['dte']['score']}/10 ({sd['dte'].get('dte', '?')}d {sd['dte'].get('category', '')})",
        f"  King Stability: {sd['king_stability']['score']}/15 ({sd['king_stability'].get('stability', 'N/A')})",
        f"  GEX Current Week: {sd['gex_current_week']['score']}/15",
        f"  GEX/VEX Align: {sd['gex_vex_alignment']['score']}/20 ({sd['gex_vex_alignment'].get('alignment', 'N/A')})",
        f"  Node Freshness: {sd['node_freshness']['weighted_score']}/10",
        f"  Gatekeeper: {sd['gatekeeper']['weighted_score']}/15",
    ])
    return "\n".join(lines)
