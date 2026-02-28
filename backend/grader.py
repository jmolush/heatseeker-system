#!/usr/bin/env python3
"""
Heatseeker Grader v3 — Quantitative Setup Scoring

Scores each panel (SPXW, SPY, QQQ) on GEX structure quality.
Runs BEFORE Claude as a cheap pre-filter + context enrichment.

INTRADAY (0DTE): max ~155 pts across 10 factors + penalties
SWING (multi-day): max ~145 pts, VEX-ready (activates when vanna available)

VEX/Vanna hooks built but score 0 until vanna scraping added.
"""

import calendar
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


def _pct(a, b, ref):
    return abs(a - b) / ref * 100 if ref > 0 else 999.0

def _norm_vel(v, mx=1.0):
    if mx == 0: return 0.5
    return (max(-1, min(1, v / mx)) + 1) / 2

def is_opex_week():
    now = datetime.now(timezone.utc)
    cal = calendar.Calendar(firstweekday=0)
    fri = [d for wk in cal.monthdayscalendar(now.year, now.month)
           for i, d in enumerate(wk) if i == 4 and d != 0]
    if len(fri) >= 3:
        delta = fri[2] - now.day
        if -7 <= delta <= 0: return True, f"OPEX WEEK (Fri {now.month}/{fri[2]})"
        if 0 < delta <= 7: return True, f"PRE-OPEX ({delta}d)"
    return False, "Normal week"

def get_time_of_day_score():
    t = ((datetime.now(timezone.utc).hour - 5) % 24) + datetime.now(timezone.utc).minute / 60
    if 9.5 <= t < 10.0: return 2, "opening_shuffle"
    if 10.0 <= t < 11.5: return 10, "prime"
    if 11.5 <= t < 14.0: return 4, "midday_chop"
    if 14.0 <= t < 15.0: return 8, "power_hour"
    if 15.0 <= t < 15.5: return 5, "late_session"
    if 15.5 <= t <= 16.0: return 2, "close"
    return 0, "market_closed"


# === INTRADAY FACTORS ===

def grade_bounce_zone(price, nodes):
    """Nearest significant node to price (0-25)."""
    if not nodes or price <= 0: return 0, {"score": 0}
    n = min(nodes, key=lambda x: abs(x["s"] - price))
    d = _pct(n["s"], price, price)
    s = 25 if d<0.3 else 22 if d<0.5 else 18 if d<1 else 12 if d<2 else 7 if d<3 else 2
    return s, {"score": s, "nearest_strike": n["s"], "nearest_M": round(n["t"]/1e6,2), "dist_pct": round(d,2)}

def grade_king_quality(price, king, direction="LONG"):
    """King distance (0-15) + alignment (0-10) = 0-25."""
    if not king or price <= 0: return 0, {"score": 0}
    ks, kg = king.get("strike",0), king.get("gex",0)
    if not ks: return 0, {"score": 0}
    d = _pct(ks, price, price)
    ds = 15 if d<0.5 else 12 if d<1.5 else 8 if d<3 else 4 if d<5 else 0
    above, lng = ks > price, direction == "LONG"
    if (lng and above) or (not lng and not above): al, aln = 10, "aligned"
    else: al, aln = 2, "against"
    return ds+al, {"score": ds+al, "king_strike": ks, "king_M": round(kg/1e6,2),
                   "dist_pct": round(d,2), "alignment": aln}

def grade_node_concentration(nodes):
    """King dominance vs #2 (0-15)."""
    if not nodes or len(nodes) < 2: return 0, {"score": 0}
    by_abs = sorted(nodes, key=lambda n: abs(n["t"]), reverse=True)
    t1, t2 = abs(by_abs[0]["t"]), abs(by_abs[1]["t"])
    dom = t1/t2 if t2 else 99
    s = 15 if dom>4 else 13 if dom>3 else 10 if dom>2 else 6 if dom>1.5 else 3 if dom>1.2 else 1
    return s, {"score": s, "dominance": round(dom,2),
               "top1": by_abs[0]["s"], "top1_M": round(t1/1e6,2),
               "top2": by_abs[1]["s"], "top2_M": round(t2/1e6,2)}

def grade_tradeable_range(price, nodes, king):
    """Distance from nearest node to king — enough for profit? (0-15)."""
    if not nodes or not king or price <= 0: return 0, {"score": 0}
    ks = king.get("strike",0)
    if not ks: return 0, {"score": 0}
    nearest = min(nodes, key=lambda n: abs(n["s"] - price))
    r = _pct(ks, nearest["s"], price)
    s = 5 if r>5 else 12 if r>3 else 15 if r>2 else 10 if r>1 else 5 if r>0.5 else 2
    return s, {"score": s, "range_pct": round(r,2), "nearest": nearest["s"], "king": ks}

def grade_node_freshness(price, nodes):
    """Significant nodes near current price (0-15)."""
    if not nodes or price <= 0: return 0, {"score": 0}
    sig = sorted(nodes, key=lambda n: abs(n.get("t",0)), reverse=True)[:10]
    nb = sum(1 for n in sig if _pct(n["s"], price, price) < 2.0)
    if nb >= 4: return 15, {"score": 15, "freshness": "highly_fresh", "nearby": nb}
    if nb >= 3: return 12, {"score": 12, "freshness": "fresh", "nearby": nb}
    if nb >= 2: return 9, {"score": 9, "freshness": "moderate", "nearby": nb}
    if nb >= 1: return 6, {"score": 6, "freshness": "single", "nearby": nb}
    return 2, {"score": 2, "freshness": "stale", "nearby": 0}

def grade_velocity(vel, direction="LONG"):
    """Rate of change across timeframes (0-15)."""
    if not vel: return 5, {"score": 5, "reason": "no data"}
    wts = {"10m": 0.5, "5m": 0.3, "1m": 0.2}
    ws = sum(vel.get(tf,0)*w for tf,w in wts.items())
    s = round(15 * _norm_vel(ws, 0.5), 1)
    return s, {"score": s, "weighted_pct": round(ws*100,2)}

def grade_trinity(trinity, ticker):
    """Cross-index king direction agreement (0-15)."""
    if not trinity: return 3, {"score": 3, "alignment": "no_data"}
    dirs, det = [], {}
    for idx in ["SPXW", "SPY", "QQQ"]:
        td = trinity.get(idx, {})
        k, p = td.get("king_node",{}), td.get("price",0)
        if k and p:
            ab = k.get("strike",0) > p
            dirs.append(1 if ab else -1)
            det[idx] = "above" if ab else "below"
    if len(dirs) < 2: return 3, {"score": 3, "alignment": "insufficient", "panels": det}
    if all(d == dirs[0] for d in dirs):
        return 15, {"score": 15, "alignment": "full_agreement", "panels": det}
    if len(dirs) == 3:
        lean = "lean_bullish" if dirs.count(1)==2 else "lean_bearish"
        return 8, {"score": 8, "alignment": lean, "panels": det}
    return 3, {"score": 3, "alignment": "divergent", "panels": det}

def grade_hist_sr(price, levels=None):
    """Confluence with historical S/R (0-10)."""
    if not levels or price <= 0: return 3, {"score": 3, "confluence": "no_data"}
    n = min(levels, key=lambda x: abs(x-price))
    d = _pct(n, price, price)
    if d < 0.1: return 10, {"score": 10, "level": n, "dist_pct": round(d,2)}
    if d < 0.5: return 7, {"score": 7, "level": n, "dist_pct": round(d,2)}
    if d < 1.0: return 4, {"score": 4, "level": n, "dist_pct": round(d,2)}
    return 1, {"score": 1, "level": n, "dist_pct": round(d,2)}


# === PENALTIES & PATTERNS ===

def detect_pinned(price, nodes):
    """Two large nodes boxing price within 2% on both sides (-15)."""
    if not nodes or price <= 0: return 0, {"pinned": False}
    top = sorted(nodes, key=lambda n: abs(n.get("t",0)), reverse=True)[:5]
    above = [n for n in top if n["s"] > price and _pct(n["s"], price, price) < 2]
    below = [n for n in top if n["s"] < price and _pct(n["s"], price, price) < 2]
    if above and below:
        return -15, {"pinned": True, "above_wall": above[0]["s"],
                     "below_wall": below[0]["s"], "penalty": -15}
    return 0, {"pinned": False}

def detect_pattern(price, nodes):
    """Pattern detection: rainbow_road / stacked / clean_range / mixed."""
    if not nodes or price <= 0: return "unknown", 0, {"pattern": "no_data"}
    sig = sorted(nodes, key=lambda n: abs(n.get("t",0)), reverse=True)[:20]
    if len(sig) < 5: return "unknown", 0, {"pattern": "too_few"}
    strikes = [n["s"] for n in sig if n["s"] > 0]
    if not strikes: return "unknown", 0, {"pattern": "no_strikes"}
    spread = (max(strikes) - min(strikes)) / price * 100
    pc = sum(1 for n in sig if n["t"] > 0)
    nc = sum(1 for n in sig if n["t"] < 0)
    if spread > 15 and pc >= 3 and nc >= 3:
        return "rainbow_road", -10, {"pattern": "rainbow_road", "spread": round(spread,1), "penalty": -10}
    for p in sorted([n for n in sig if n["t"]>0], key=lambda n: n["s"])[:5]:
        for neg in sorted([n for n in sig if n["t"]<0], key=lambda n: n["s"], reverse=True)[:5]:
            if abs(p["s"]-neg["s"])/price < 0.015:
                return "stacked", 5, {"pattern": "stacked", "pos": p["s"], "neg": neg["s"], "bonus": 5}
    if spread < 8:
        return "clean_range", 5, {"pattern": "clean_range", "spread": round(spread,1), "bonus": 5}
    return "mixed", 0, {"pattern": "mixed", "spread": round(spread,1)}


# === GATEKEEPERS ===

def find_gatekeepers(price, nodes, king):
    """Find significant nodes between price and king."""
    if not nodes or not king or price <= 0: return [], {"count": 0}
    ks = king.get("strike",0)
    if not ks: return [], {"count": 0}
    going_up = ks > price
    barriers = []
    for n in nodes:
        s, v = n.get("s",0), n.get("t",0)
        if abs(v) < 1e6: continue  # skip small nodes
        if going_up and price < s < ks:
            barriers.append({"strike": s, "value_M": round(v/1e6,2), "type": "resistance"})
        elif not going_up and ks < s < price:
            barriers.append({"strike": s, "value_M": round(v/1e6,2), "type": "support"})
    barriers.sort(key=lambda b: abs(b["value_M"]), reverse=True)
    return barriers[:3], {"count": min(len(barriers),3), "direction": "up" if going_up else "down"}

def grade_gatekeeper(price, gatekeepers, king):
    """Score gatekeeper situation: clear path vs strong barrier (0-10 informational)."""
    if not gatekeepers:
        return 10, {"score": 10, "situation": "clear_path", "trim": "NONE"}
    kv = abs(king.get("gex",0)) if king else 0
    strongest = max(abs(g.get("value_M",0)*1e6) for g in gatekeepers)
    gs = gatekeepers[0]["strike"]
    if strongest > kv * 0.5:
        return 3, {"score": 3, "situation": "strong_gatekeeper", "strike": gs,
                   "trim": "TRIM 1/3 AT GATEKEEPER"}
    return 7, {"score": 7, "situation": "weak_gatekeeper", "strike": gs, "trim": "MONITOR"}


# === SWING FACTORS (VEX-ready) ===

def grade_vex_direction(price, vex_nodes, direction="LONG"):
    """VEX/Vanna alignment with trade direction (0-25). Returns 0 if no VEX data."""
    if not vex_nodes or price <= 0:
        return 0, {"score": 0, "reason": "no VEX data (awaiting vanna integration)"}
    up = sum(n.get("t",0) for n in vex_nodes if n.get("s",0) > price)
    dn = sum(n.get("t",0) for n in vex_nodes if n.get("s",0) < price)
    vd = 1 if (up+dn) > 0 else -1
    aligned = (direction=="LONG" and vd==1) or (direction=="SHORT" and vd==-1)
    return (25 if aligned else 0), {"score": 25 if aligned else 0,
            "alignment": "aligned" if aligned else "opposed",
            "upside_M": round(up/1e6,2), "downside_M": round(dn/1e6,2)}

def grade_vex_significance(vex_nodes):
    """VEX king dominance (0-20). Returns 0 if no VEX data."""
    if not vex_nodes: return 0, {"score": 0, "reason": "no VEX data"}
    mx = max(abs(n.get("t",0)) for n in vex_nodes)
    total = sum(abs(n.get("t",0)) for n in vex_nodes)
    if total == 0: return 0, {"score": 0}
    sig = mx / total
    return round(20*sig,1), {"score": round(20*sig,1), "significance_pct": round(sig*100,1)}

def grade_gex_vex_alignment(nodes, vex_nodes, price, timeframe="intraday"):
    """GEX-VEX agreement on direction (0-15 intraday, 0-20 swing). 0 if no VEX."""
    if not nodes or not vex_nodes: return 0, {"score": 0, "reason": "no VEX data"}
    gb = sum(n.get("t",0) for n in nodes if n.get("s",0) < price)
    ga = sum(n.get("t",0) for n in nodes if n.get("s",0) > price)
    vb = sum(n.get("t",0) for n in vex_nodes if n.get("s",0) < price)
    va = sum(n.get("t",0) for n in vex_nodes if n.get("s",0) > price)
    gd, vd = (1 if gb>ga else -1), (1 if vb>va else -1)
    aligned = gd == vd
    base = 20 if timeframe=="swing" else 15
    if aligned:
        strength = abs(gb-ga)/(abs(gb)+abs(ga)+1)
        s = base * (0.5 + strength*0.5)
    else:
        s = base * 0.25
    at = ("bullish" if gd==1 else "bearish") + ("_aligned" if aligned else "_divergent")
    return round(s,1), {"score": round(s,1), "alignment": at, "aligned": aligned}

def grade_dte(expiry, entry_date=None):
    """Days to expiry scoring for swing (0-10)."""
    if not expiry: return 5, {"score": 5, "dte": None}
    entry = entry_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        dte = (datetime.strptime(expiry,"%Y-%m-%d") - datetime.strptime(entry,"%Y-%m-%d")).days
    except Exception:
        return 5, {"score": 5, "dte": None}
    if dte <= 3: return 2, {"score": 2, "dte": dte, "cat": "very_short"}
    if dte <= 7: return 5, {"score": 5, "dte": dte, "cat": "short"}
    if dte <= 14: return 8, {"score": 8, "dte": dte, "cat": "medium"}
    return 10, {"score": 10, "dte": dte, "cat": "long"}

def grade_king_stability(current_king, previous_king=None):
    """Has king node moved since last capture? (0-15)."""
    if not current_king: return 5, {"score": 5, "stability": "no_king"}
    ks = current_king.get("strike",0)
    if previous_king is None:
        return 12, {"score": 12, "stability": "first_capture", "king": ks}
    unchanged = ks == previous_king.get("strike",0)
    s = 15 if unchanged else 7
    return s, {"score": s, "stability": "stable" if unchanged else "shifted", "king": ks}


# ============================================================================
# MAIN DUAL-TIMEFRAME GRADER
# ============================================================================

def grade_dual(ticker, price, gex_nodes, vex_nodes=None, king_node=None,
               velocity=None, trinity_data=None, direction="LONG",
               expiry=None, entry_date=None, historical_sr=None,
               previous_king=None):
    """
    Calculate INTRADAY + SWING grades with full breakdown.

    INTRADAY max: 25+25+15+15+15+15+15+10+10 = 145 base + pattern bonus/penalty
    SWING max: 25+20+15+15+10+15+20 = 120 base (VEX-dependent factors = 0 without vanna)
    """
    vex_nodes = vex_nodes or []
    velocity = velocity or {}
    trinity_data = trinity_data or {}

    # --- INTRADAY ---
    bounce_s, bounce_d = grade_bounce_zone(price, gex_nodes)
    king_s, king_d = grade_king_quality(price, king_node, direction)
    conc_s, conc_d = grade_node_concentration(gex_nodes)
    range_s, range_d = grade_tradeable_range(price, gex_nodes, king_node)
    fresh_s, fresh_d = grade_node_freshness(price, gex_nodes)
    vel_s, vel_d = grade_velocity(velocity, direction)
    trin_s, trin_d = grade_trinity(trinity_data, ticker)
    tod_s, tod_phase = get_time_of_day_score()
    hist_s, hist_d = grade_hist_sr(price, historical_sr)

    # Penalties & patterns
    pin_s, pin_d = detect_pinned(price, gex_nodes)
    pattern, pat_s, pat_d = detect_pattern(price, gex_nodes)

    # Gatekeepers (informational — doesn't affect score, but in report)
    gk_list, gk_info = find_gatekeepers(price, gex_nodes, king_node)
    gk_s, gk_d = grade_gatekeeper(price, gk_list, king_node)

    intraday_raw = (bounce_s + king_s + conc_s + range_s + fresh_s +
                    vel_s + trin_s + tod_s + hist_s)
    intraday_total = max(0, intraday_raw + pin_s + pat_s)

    # --- SWING ---
    vex_dir_s, vex_dir_d = grade_vex_direction(price, vex_nodes, direction)
    vex_sig_s, vex_sig_d = grade_vex_significance(vex_nodes)
    gvex_s, gvex_d = grade_gex_vex_alignment(gex_nodes, vex_nodes, price, "swing")
    dte_s, dte_d = grade_dte(expiry, entry_date)
    stab_s, stab_d = grade_king_stability(king_node, previous_king)
    # Reuse some intraday factors at reduced weight for swing
    swing_fresh = round(fresh_s * 0.7, 1)
    swing_hist = round(min(hist_s * 1.5, 15), 1)
    swing_trin = round(trin_s * 0.8, 1)

    # If no VEX data, swing max is reduced — grade accordingly
    has_vex = bool(vex_nodes)
    swing_total = (vex_dir_s + vex_sig_s + gvex_s + dte_s + stab_s +
                   swing_fresh + swing_hist + swing_trin)

    # --- GRADING ---
    opex, opex_desc = is_opex_week()

    def letter(score, max_score):
        if max_score <= 0: return "N/A"
        pct = score / max_score * 100
        if pct >= 75: return "A+"
        if pct >= 60: return "A"
        if pct >= 50: return "B+"
        if pct >= 35: return "B"
        if pct >= 20: return "C"
        return "F"

    # Intraday max = 145 + possible bonuses
    intra_max = 145
    # Swing max depends on VEX availability
    swing_max = 120 if has_vex else 55  # Without VEX: dte+stab+fresh+hist+trin

    return {
        "ticker": ticker,
        "price": price,
        "direction": direction,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "opex_week": opex,
        "opex_description": opex_desc,
        "pattern": pattern,
        "pattern_details": pat_d,
        "has_vex_data": has_vex,
        "gatekeepers": {"nodes": gk_list, **gk_info, **gk_d},
        "pinned": pin_d,
        "intraday": {
            "score": round(intraday_total, 1),
            "max": intra_max,
            "pct": round(intraday_total / intra_max * 100, 1),
            "grade": letter(intraday_total, intra_max),
            "breakdown": {
                "bounce_zone": {"max": 25, **bounce_d},
                "king_quality": {"max": 25, **king_d},
                "concentration": {"max": 15, **conc_d},
                "tradeable_range": {"max": 15, **range_d},
                "node_freshness": {"max": 15, **fresh_d},
                "velocity": {"max": 15, **vel_d},
                "trinity": {"max": 15, **trin_d},
                "time_of_day": {"max": 10, "score": tod_s, "phase": tod_phase},
                "historical_sr": {"max": 10, **hist_d},
                "pattern_adj": pat_d,
                "pinned_adj": pin_d,
            }
        },
        "swing": {
            "score": round(swing_total, 1),
            "max": swing_max,
            "pct": round(swing_total / swing_max * 100, 1) if swing_max > 0 else 0,
            "grade": letter(swing_total, swing_max),
            "note": "VEX factors inactive — awaiting vanna integration" if not has_vex else None,
            "breakdown": {
                "vex_direction": {"max": 25, **vex_dir_d},
                "vex_significance": {"max": 20, **vex_sig_d},
                "gex_vex_alignment": {"max": 20, **gvex_d},
                "dte": {"max": 10, **dte_d},
                "king_stability": {"max": 15, **stab_d},
                "node_freshness": {"max": 10, "score": swing_fresh},
                "historical_sr": {"max": 15, "score": swing_hist},
                "trinity": {"max": 12, "score": swing_trin},
            }
        },
    }


# ============================================================================
# REPORT FORMATTING
# ============================================================================

def format_grade_report(data):
    """Human-readable grade report for Discord / terminal."""
    t = data["ticker"]
    i = data["intraday"]
    s = data["swing"]
    ts = data.get("timestamp", "")[:16]

    lines = [f"**{t}** ${data.get('price',0):,.2f} | {data.get('direction','?')} | {ts}"]

    # Warnings
    warns = []
    if data.get("opex_week"): warns.append(f"⚠️ {data['opex_description']}")
    if data.get("pattern") == "rainbow_road": warns.append("🌈 RAINBOW ROAD — AVOID")
    elif data.get("pattern") == "stacked": warns.append("⚡ STACKED — vol spring")
    if data.get("pinned", {}).get("pinned"): warns.append("📌 PINNED between walls")
    if warns: lines.append(" | ".join(warns))

    # Intraday
    ib = i["breakdown"]
    lines.append(f"\n**INTRADAY: {i['score']}/{i['max']} ({i['pct']}%) — {i['grade']}**")
    lines.append(f"  Bounce Zone:    {ib['bounce_zone']['score']}/{ib['bounce_zone']['max']}"
                 f"  (nearest ${ib['bounce_zone'].get('nearest_strike','?')} @ {ib['bounce_zone'].get('dist_pct','?')}%)")
    lines.append(f"  King Quality:   {ib['king_quality']['score']}/{ib['king_quality']['max']}"
                 f"  (${ib['king_quality'].get('king_strike','?')} {ib['king_quality'].get('alignment','?')})")
    lines.append(f"  Concentration:  {ib['concentration']['score']}/{ib['concentration']['max']}"
                 f"  ({ib['concentration'].get('dominance','?')}x dominance)")
    lines.append(f"  Tradeable Range:{ib['tradeable_range']['score']}/{ib['tradeable_range']['max']}"
                 f"  ({ib['tradeable_range'].get('range_pct','?')}% range)")
    lines.append(f"  Node Freshness: {ib['node_freshness']['score']}/{ib['node_freshness']['max']}"
                 f"  ({ib['node_freshness'].get('freshness','?')})")
    lines.append(f"  Velocity:       {ib['velocity']['score']}/{ib['velocity']['max']}")
    lines.append(f"  Trinity:        {ib['trinity']['score']}/{ib['trinity']['max']}"
                 f"  ({ib['trinity'].get('alignment','?')})")
    lines.append(f"  Time of Day:    {ib['time_of_day']['score']}/{ib['time_of_day']['max']}"
                 f"  ({ib['time_of_day']['phase']})")
    lines.append(f"  Historical S/R: {ib['historical_sr']['score']}/{ib['historical_sr']['max']}")

    # Gatekeepers
    gk = data.get("gatekeepers", {})
    if gk.get("nodes"):
        gk_strs = [f"${g['strike']} ({g['value_M']}M {g['type']})" for g in gk["nodes"]]
        lines.append(f"  Gatekeepers:    {', '.join(gk_strs)}")
        lines.append(f"  Gatekeeper Sit: {gk.get('situation','?')} — {gk.get('trim','')}")

    # Swing
    sb = s["breakdown"]
    lines.append(f"\n**SWING: {s['score']}/{s['max']} ({s['pct']}%) — {s['grade']}**")
    if s.get("note"):
        lines.append(f"  ⏳ {s['note']}")
    lines.append(f"  VEX Direction:  {sb['vex_direction']['score']}/{sb['vex_direction']['max']}")
    lines.append(f"  VEX Significance:{sb['vex_significance']['score']}/{sb['vex_significance']['max']}")
    lines.append(f"  GEX/VEX Align:  {sb['gex_vex_alignment']['score']}/{sb['gex_vex_alignment']['max']}")
    lines.append(f"  DTE:            {sb['dte']['score']}/{sb['dte']['max']}")
    lines.append(f"  King Stability: {sb['king_stability']['score']}/{sb['king_stability']['max']}"
                 f"  ({sb['king_stability'].get('stability','?')})")
    lines.append(f"  Node Freshness: {sb['node_freshness']['score']}/{sb['node_freshness']['max']}")
    lines.append(f"  Historical S/R: {sb['historical_sr']['score']}/{sb['historical_sr']['max']}")
    lines.append(f"  Trinity:        {sb['trinity']['score']}/{sb['trinity']['max']}")

    return "\n".join(lines)


def should_escalate_to_claude(grade_result, min_intraday_pct=25):
    """
    Pre-filter: should this capture be sent to Claude for full analysis?

    Returns (bool, reason).
    Below threshold = skip Claude = save tokens.
    """
    i = grade_result.get("intraday", {})
    pct = i.get("pct", 0)
    pattern = grade_result.get("pattern", "")
    pinned = grade_result.get("pinned", {}).get("pinned", False)

    if pattern == "rainbow_road":
        return False, "Rainbow Road — no tradeable structure"
    if pinned and pct < 35:
        return False, f"Pinned + low score ({pct}%) — chop zone"
    if pct < min_intraday_pct:
        return False, f"Intraday score too low ({pct}%) — below {min_intraday_pct}% threshold"
    return True, f"Score {pct}% passes threshold"
