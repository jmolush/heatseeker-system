#!/usr/bin/env python3
"""Test grader with synthetic data matching our scraper output format."""

import json
from grader import grade_dual, format_grade_report, should_escalate_to_claude
from grader_adapter import (
    grade_capture, grade_all_panels, scraper_to_grader_nodes,
    scraper_to_grader_king, grade_context_for_claude, should_analyze
)

# Synthetic scraper output matching real capture structure
SAMPLE_CAPTURE = {
    "timestamp": "2026-03-01T14:30:00Z",
    "mode": "trinity_plus",
    "panel_count": 4,
    "total_nodes": 50,
    "panels": [
        {
            "ticker": "SPXW",
            "price": 5850.0,
            "change_pct": 0.35,
            "node_count": 15,
            "king_node": {"strike": 5875, "value": 14196600, "gamma_type": "positive", "is_king": True},
            "nodes": [
                {"strike": 5875, "value": 14196600, "gamma_type": "positive", "is_king": True},
                {"strike": 5850, "value": 8500000, "gamma_type": "positive", "is_king": False},
                {"strike": 5825, "value": 6200000, "gamma_type": "negative", "is_king": False},
                {"strike": 5900, "value": 5100000, "gamma_type": "positive", "is_king": False},
                {"strike": 5800, "value": 4300000, "gamma_type": "negative", "is_king": False},
                {"strike": 5860, "value": 3951900, "gamma_type": "negative", "is_king": False},
                {"strike": 5840, "value": 3200000, "gamma_type": "positive", "is_king": False},
                {"strike": 5870, "value": 2800000, "gamma_type": "positive", "is_king": False},
                {"strike": 5810, "value": 2100000, "gamma_type": "negative", "is_king": False},
                {"strike": 5890, "value": 1800000, "gamma_type": "positive", "is_king": False},
            ]
        },
        {
            "ticker": "SPY",
            "price": 585.0,
            "change_pct": 0.32,
            "node_count": 15,
            "king_node": {"strike": 587, "value": 9800000, "gamma_type": "positive", "is_king": True},
            "nodes": [
                {"strike": 587, "value": 9800000, "gamma_type": "positive", "is_king": True},
                {"strike": 585, "value": 7200000, "gamma_type": "positive", "is_king": False},
                {"strike": 583, "value": 5500000, "gamma_type": "negative", "is_king": False},
                {"strike": 590, "value": 4100000, "gamma_type": "positive", "is_king": False},
                {"strike": 580, "value": 3800000, "gamma_type": "negative", "is_king": False},
                {"strike": 586, "value": 3200000, "gamma_type": "positive", "is_king": False},
                {"strike": 584, "value": 2900000, "gamma_type": "negative", "is_king": False},
                {"strike": 588, "value": 2500000, "gamma_type": "positive", "is_king": False},
            ]
        },
        {
            "ticker": "QQQ",
            "price": 505.0,
            "change_pct": 0.28,
            "node_count": 12,
            "king_node": {"strike": 507, "value": 7500000, "gamma_type": "positive", "is_king": True},
            "nodes": [
                {"strike": 507, "value": 7500000, "gamma_type": "positive", "is_king": True},
                {"strike": 505, "value": 5400000, "gamma_type": "positive", "is_king": False},
                {"strike": 503, "value": 4200000, "gamma_type": "negative", "is_king": False},
                {"strike": 510, "value": 3100000, "gamma_type": "positive", "is_king": False},
                {"strike": 500, "value": 2800000, "gamma_type": "negative", "is_king": False},
                {"strike": 506, "value": 2200000, "gamma_type": "positive", "is_king": False},
            ]
        },
        {
            "ticker": "VIX",
            "price": 18.5,
            "change_pct": -2.1,
            "node_count": 8,
            "king_node": {"strike": 22, "value": 10609700, "gamma_type": "negative", "is_king": True},
            "nodes": [
                {"strike": 22, "value": 10609700, "gamma_type": "negative", "is_king": True},
                {"strike": 20, "value": 5400000, "gamma_type": "negative", "is_king": False},
                {"strike": 18, "value": 4200000, "gamma_type": "positive", "is_king": False},
                {"strike": 25, "value": 3800000, "gamma_type": "negative", "is_king": False},
                {"strike": 15, "value": 2200000, "gamma_type": "positive", "is_king": False},
            ]
        }
    ]
}


def test_adapter_conversion():
    print("=" * 60)
    print("TEST: Adapter Conversion")
    print("=" * 60)
    
    spy_panel = SAMPLE_CAPTURE["panels"][1]
    nodes = scraper_to_grader_nodes(spy_panel)
    king = scraper_to_grader_king(spy_panel)
    
    print(f"SPY nodes: {len(nodes)} converted")
    print(f"  Sample: strike={nodes[0]['s']}, t={nodes[0]['t']/1e6:.1f}M")
    print(f"  Negative gamma node: strike={nodes[2]['s']}, t={nodes[2]['t']/1e6:.1f}M")
    print(f"King: strike={king['strike']}, gex={king['gex']/1e6:.1f}M")
    
    assert nodes[0]["t"] > 0, "Positive gamma should be positive"
    assert nodes[2]["t"] < 0, "Negative gamma should be negative"
    assert king["gex"] > 0, "King should be positive"
    print("✅ Adapter conversion correct\n")


def test_single_panel_grade():
    print("=" * 60)
    print("TEST: Single Panel Grade (SPY)")
    print("=" * 60)
    
    result = grade_capture(SAMPLE_CAPTURE, ticker="SPY", direction="LONG")
    assert result is not None, "Should return a result"
    
    i = result["intraday"]
    print(f"Intraday: {i['score']}/{i['max']} ({i['pct']}%) — {i['grade']}")
    
    s = result["swing"]
    print(f"Swing:    {s['score']}/{s['max']} ({s['pct']}%) — {s['grade']}")
    print(f"VEX data: {result['has_vex_data']}")
    print(f"Pattern:  {result['pattern']}")
    print(f"Pinned:   {result['pinned']['pinned']}")
    
    assert i["score"] > 0, "Should have a positive score"
    assert i["max"] > 0, "Max should be set"
    assert result["has_vex_data"] == False, "No VEX data in sample"
    print("✅ Single panel grade works\n")


def test_all_panels():
    print("=" * 60)
    print("TEST: All Panels Grade")
    print("=" * 60)
    
    results = grade_all_panels(SAMPLE_CAPTURE, direction="LONG")
    
    assert "SPXW" in results, "Should have SPXW"
    assert "SPY" in results, "Should have SPY"
    assert "QQQ" in results, "Should have QQQ"
    assert "best" in results, "Should identify best panel"
    
    for ticker in ["SPXW", "SPY", "QQQ"]:
        r = results[ticker]
        i = r["intraday"]
        print(f"{ticker}: {i['score']}/{i['max']} ({i['pct']}%) — {i['grade']}"
              f"  | escalate={r['escalate_to_claude']}")
    
    print(f"\nBest panel: {results['best']}")
    print(f"Escalate any: {results['summary']['escalate_any']}")
    print("✅ All panels grade works\n")


def test_grade_report():
    print("=" * 60)
    print("TEST: Grade Report Formatting")
    print("=" * 60)
    
    result = grade_capture(SAMPLE_CAPTURE, ticker="SPY", direction="LONG")
    report = format_grade_report(result)
    print(report)
    
    assert "SPY" in report, "Report should mention ticker"
    assert "INTRADAY" in report, "Report should have intraday section"
    assert "SWING" in report, "Report should have swing section"
    print("\n✅ Report formatting works\n")


def test_escalation_logic():
    print("=" * 60)
    print("TEST: Escalation Logic")
    print("=" * 60)
    
    result = grade_capture(SAMPLE_CAPTURE, ticker="SPY", direction="LONG")
    
    escalate, reason = should_escalate_to_claude(result)
    print(f"Escalate: {escalate} — {reason}")
    
    can_analyze = should_analyze(result, min_pct=30.0)
    print(f"Should analyze (30% threshold): {can_analyze}")
    
    can_analyze_strict = should_analyze(result, min_pct=90.0)
    print(f"Should analyze (90% threshold): {can_analyze_strict}")
    
    print("✅ Escalation logic works\n")


def test_claude_context():
    print("=" * 60)
    print("TEST: Claude Context Formatting")
    print("=" * 60)
    
    result = grade_capture(SAMPLE_CAPTURE, ticker="SPY", direction="LONG")
    ctx = grade_context_for_claude(result)
    print(ctx)
    
    assert "QUANTITATIVE" in ctx, "Should have header"
    assert "King" in ctx, "Should mention king"
    assert "Trinity" in ctx, "Should mention trinity"
    print("\n✅ Claude context works\n")


if __name__ == "__main__":
    test_adapter_conversion()
    test_single_panel_grade()
    test_all_panels()
    test_grade_report()
    test_escalation_logic()
    test_claude_context()
    print("=" * 60)
    print("ALL TESTS PASSED ✅")
    print("=" * 60)
