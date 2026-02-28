"""
Heatseeker Trading System — Analysis Engine

Sends heatmap captures to Claude for analysis.
Tiered approach:
- Quick triage: "Has anything meaningful changed?" (cheap/fast)
- Full analysis: Pattern recognition, confluence, trade recommendation
"""

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic

from config import Config


# ─── System Prompts ───────────────────────────────────────────────

TRIAGE_SYSTEM_PROMPT = """You are an expert options trader analyzing Skylit Heatseeker dealer positioning heatmaps.

Your role in this message is TRIAGE ONLY. Look at the heatmap screenshot and answer:
1. Has anything meaningful changed compared to what you'd expect for a normal trading day?
2. Are there any notable node formations (King Nodes, Gatekeepers, clusters)?
3. Is there cross-index confluence visible (if Trinity Mode showing SPX/SPY/QQQ)?

Respond in JSON format:
{
  "significant_change": true/false,
  "confidence": 0.0-1.0,
  "summary": "one-line description",
  "escalate": true/false,
  "reason": "why escalate or not"
}

Be conservative — only set escalate=true if there's something worth a deeper look.
"""

ANALYSIS_SYSTEM_PROMPT = """You are an expert options trader analyzing Skylit Heatseeker dealer positioning heatmaps for 0DTE (zero days to expiration) options trading.

You have deep knowledge of:
- Heatseeker node types: positive gamma (yellow/green = absorption), negative gamma (purple/blue = amplification)
- King Nodes (highest absolute value — primary price target)
- Gatekeeper Nodes (barriers that reject price)
- Node interaction: 1st touch strongest, 2nd ~66%, 3rd+ ~33%
- Robinhood Power Hour (3:30 PM ET) forced flow effects
- Rate of change: rapid accumulation = strong pull, rapid unwinding = weakening
- Rolling ceilings (bearish) and rolling floors (bullish)
- Air pockets (low volume zones — fast price movement)
- Cross-index confluence: SPX, SPY, QQQ MUST agree for high-confidence trades
- The Ten Commandments: protect capital, only trade reversals at edges, asymmetric R:R, go long on red candles / short on green

Your analysis should cover:
1. **Current State**: What's the heatmap showing right now?
2. **Key Nodes**: Identify King Node, Gatekeepers, notable clusters with approximate values
3. **Pattern**: Which pattern matches? (Whipsaw, Rainbow Road, Gatekeeper, Trend, Rug Setup)
4. **Cross-Index Confluence**: Do SPX/SPY/QQQ agree? Any divergence?
5. **Rate of Change**: Are nodes accumulating, stable, or dissipating?
6. **Trade Thesis**: Bull/bear/pin probability breakdown
7. **Recommendation**: If there's a high-confidence setup, specify:
   - Direction (call/put)
   - Target underlying (SPY or QQQ)
   - Strike selection logic (near King Node, at Gatekeeper, etc.)
   - Entry condition ("wait for rejection at X" or "enter on pullback to Y")
   - Profit target and stop loss level
   - Confidence level (1-10)
8. **Stand Aside?**: If the map is unclear (Rainbow Road, mixed signals), say so clearly.

Also consider VIX context when provided:
- VIX < 15 (low vol): Tight ranges, pin jobs, fast theta decay
- VIX 15-20 (normal): Standard setups, nodes behave predictably
- VIX 20-25 (elevated): Wider ranges, nodes may overshoot, wider margins
- VIX 25-30 (high): Fast moves, gatekeepers less reliable, reduce size
- VIX > 30 (extreme): Maps reshuffle frequently, protect capital, only extreme R:R

When VIX gamma distribution data is provided (scraped from the 4th panel):
- The VIX heatmap shows dealer positioning in VIX options — this reveals WHERE dealers expect vol to land
- VIX King Node = expected VIX settlement target (like SPX king = price target)
- Heavy positive gamma at a VIX strike = dealers absorb vol spikes at that level (vol ceiling)
- Heavy negative gamma at a VIX strike = dealers amplify moves through that level (vol acceleration)
- If VIX gamma shows a strong floor with negative gamma below = vol unlikely to drop further → stay defensive
- If VIX gamma shows a ceiling = vol spike will be absorbed → more confident in directional trades
- Cross-reference VIX gamma king with actual VIX price: if VIX is far from king, expect mean reversion toward it

Consider the market day type when provided:
- TREND DAY: Trade with direction, enter on pullbacks, don't fade. King Node is destination.
- LEVELS DAY: Fade the edges, avoid midpoint. Play reversals at nodes. Pin jobs near close.
- WHIPSAW DAY: Reduce size or sit out. Multiple failed tests, reversals don't hold. Only extreme setups.
The day type can reclassify as the session evolves — a levels day can become a trend day on a breakout.

Also consider rate-of-change context when provided:
- Accumulation alerts: nodes building = strong directional pull
- Dissipation alerts: nodes weakening = potential explosive move or reversal
- Reshuffle alerts: thesis may be INVALIDATED — re-evaluate from scratch
- Rolling ceiling/floor: strong directional bias building
- King shift: primary target changed — reassess everything

Respond in JSON format with these fields. Be honest about uncertainty.
Do NOT force a trade if the setup isn't there. "No trade" is a valid recommendation.
"""


class HeatmapAnalyzer:
    """Sends heatmap screenshots to Claude for analysis."""

    def __init__(self):
        self.client = None
        if Config.ANTHROPIC_API_KEY:
            self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self._analysis_log = []

    def _load_image(self, image_path: str) -> Optional[str]:
        """Load image and return base64 encoded string."""
        path = Path(image_path)
        if not path.exists():
            print(f'[Analyzer] Image not found: {image_path}')
            return None

        with open(path, 'rb') as f:
            return base64.standard_b64encode(f.read()).decode('utf-8')

    def triage(self, image_path: str, market_context: dict = None) -> Optional[dict]:
        """
        Quick triage of a heatmap capture.
        Uses a cheaper/faster model to decide if full analysis is needed.
        
        Returns: { significant_change, confidence, summary, escalate, reason }
        """
        if not self.client:
            print('[Analyzer] No Anthropic API key configured')
            return None

        image_b64 = self._load_image(image_path)
        if not image_b64:
            return None

        user_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_b64
                }
            },
            {
                "type": "text",
                "text": "Triage this Heatseeker heatmap capture. Is there anything notable?"
            }
        ]

        if market_context:
            user_content.append({
                "type": "text",
                "text": f"Current market context: {json.dumps(market_context)}"
            })

        try:
            response = self.client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=500,
                system=TRIAGE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}]
            )

            text = response.content[0].text
            # Try to parse as JSON
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                # If model didn't return clean JSON, wrap it
                result = {
                    "significant_change": True,
                    "confidence": 0.5,
                    "summary": text[:200],
                    "escalate": True,
                    "reason": "Could not parse structured response"
                }

            result['_model'] = 'haiku'
            result['_timestamp'] = datetime.now(timezone.utc).isoformat()
            result['_image'] = image_path
            result['_input_tokens'] = response.usage.input_tokens
            result['_output_tokens'] = response.usage.output_tokens

            self._analysis_log.append(result)
            return result

        except Exception as e:
            print(f'[Analyzer] Triage failed: {e}')
            return None

    def analyze(self, image_path: str, market_context: dict = None,
                recent_analyses: list = None, vix_context: dict = None,
                roc_summary: dict = None, confluence_state: dict = None,
                regime: dict = None, scraped_data: dict = None,
                grade_result: dict = None, direction: str = "LONG",
                skip_if_low_grade: bool = True, min_grade_pct: float = 30.0) -> Optional[dict]:
        """
        Full analysis of a heatmap capture.
        Uses Sonnet for detailed pattern recognition and trade recommendation.
        
        Now integrates the quantitative grader:
        - If grade_result is provided, uses it as pre-filter and context enrichment
        - If scraped_data is provided but no grade_result, runs grader automatically
        - If skip_if_low_grade=True and grade % < min_grade_pct, skips Claude analysis
        
        Args:
            image_path: Path to the heatmap screenshot
            market_context: SPY/QQQ price data from OpenD
            recent_analyses: Previous triage results for continuity
            vix_context: VIX regime, level, and guidance from VIXMonitor
            roc_summary: Rate of change state from RateOfChangeTracker
            confluence_state: Cross-index confluence state
            regime: Market day type classification
            scraped_data: Structured JSON from DOM scraper (all panels incl VIX)
            grade_result: Pre-computed grade from grader (optional — computed if missing)
            direction: LONG or SHORT (for grader)
            skip_if_low_grade: Skip Claude if grade is too low (saves tokens)
            min_grade_pct: Minimum intraday grade % to proceed (default 30%)
        
        Returns: Full analysis dict with thesis, recommendation, confidence, etc.
                 Returns grade-only result (no Claude) if skipped due to low grade.
        """
        # ── Grader Integration ─────────────────────────────────────
        # Run grader if we have scraped data but no pre-computed grade
        if scraped_data and not grade_result:
            try:
                from grader_adapter import grade_all_panels, should_analyze
                all_grades = grade_all_panels(scraped_data, direction=direction)
                # Use the best panel's grade as the primary result
                best = all_grades.get("best")
                if best and best in all_grades:
                    grade_result = all_grades[best]
                    grade_result["_all_panels"] = {
                        k: v for k, v in all_grades.items()
                        if k not in ("best", "summary")
                    }
            except Exception as e:
                print(f'[Analyzer] Grader failed (non-fatal): {e}')

        # Pre-filter: skip Claude if grade is too low (saves tokens)
        if skip_if_low_grade and grade_result:
            from grader_adapter import should_analyze
            if not should_analyze(grade_result, min_pct=min_grade_pct):
                print(f'[Analyzer] Skipping Claude — grade too low '
                      f'({grade_result.get("intraday",{}).get("pct",0):.1f}% < {min_grade_pct}%)')
                # Return grade-only result without spending Claude tokens
                from grader import format_grade_report
                return {
                    "skipped_claude": True,
                    "reason": f"Grade {grade_result['intraday']['pct']:.1f}% below threshold {min_grade_pct}%",
                    "grade": grade_result,
                    "grade_report": format_grade_report(grade_result),
                    "recommendation": grade_result.get("action", {}),
                    "_model": "grader_only",
                    "_timestamp": datetime.now(timezone.utc).isoformat(),
                    "_input_tokens": 0,
                    "_output_tokens": 0,
                }

        if not self.client:
            print('[Analyzer] No Anthropic API key configured')
            # Still return grade if available
            if grade_result:
                from grader import format_grade_report
                return {
                    "skipped_claude": True,
                    "reason": "No Anthropic API key",
                    "grade": grade_result,
                    "grade_report": format_grade_report(grade_result),
                    "recommendation": grade_result.get("action", {}),
                    "_model": "grader_only",
                    "_timestamp": datetime.now(timezone.utc).isoformat(),
                    "_input_tokens": 0,
                    "_output_tokens": 0,
                }
            return None

        user_content = []

        # ── Grade Context for Claude ───────────────────────────────
        # Prepend quantitative grade summary so Claude has structured data
        if grade_result:
            try:
                from grader_adapter import grade_context_for_claude
                grade_ctx = grade_context_for_claude(grade_result)
                if grade_ctx:
                    user_content.append({
                        "type": "text",
                        "text": grade_ctx,
                    })
            except Exception as e:
                print(f'[Analyzer] Grade context formatting failed (non-fatal): {e}')

        # If we have scraped data, use it as primary input (much cheaper than vision)
        # Include screenshot only as fallback/validation
        if scraped_data and scraped_data.get('total_nodes', 0) > 0:
            user_content.append({
                "type": "text",
                "text": (
                    "Scraped heatmap data (structured JSON from DOM — primary data source):\n"
                    f"{json.dumps(scraped_data, indent=2)}"
                )
            })

            # Still include screenshot for visual validation if available
            image_b64 = self._load_image(image_path) if image_path else None
            if image_b64:
                user_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_b64
                    }
                })
                user_content.append({
                    "type": "text",
                    "text": (
                        "Above is the visual screenshot for reference. Use the structured JSON as your "
                        "primary data source — it's more precise. Use the screenshot to verify visual "
                        "patterns, color gradients, and any details the scraper might miss."
                    )
                })
            else:
                user_content.append({
                    "type": "text",
                    "text": "No screenshot available — analyze using the structured JSON data only."
                })

            user_content.append({
                "type": "text",
                "text": "Analyze this Heatseeker heatmap in detail. Provide your full assessment and trade recommendation."
            })
        else:
            # No scraped data — fall back to vision-only analysis
            image_b64 = self._load_image(image_path)
            if not image_b64:
                print('[Analyzer] No image and no scraped data — cannot analyze')
                return None

            user_content.extend([
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_b64
                    }
                },
                {
                    "type": "text",
                    "text": "Analyze this Heatseeker heatmap in detail. Provide your full assessment and trade recommendation."
                }
            ])

        if market_context:
            user_content.append({
                "type": "text",
                "text": f"Current market data (SPY/QQQ from OpenD):\n{json.dumps(market_context, indent=2)}"
            })

        if vix_context:
            user_content.append({
                "type": "text",
                "text": f"VIX context:\n{json.dumps(vix_context, indent=2)}"
            })

        if roc_summary:
            user_content.append({
                "type": "text",
                "text": f"Rate of change (recent node value trends):\n{json.dumps(roc_summary, indent=2)}"
            })

        if confluence_state:
            user_content.append({
                "type": "text",
                "text": f"Cross-index confluence state:\n{json.dumps(confluence_state, indent=2)}"
            })

        if regime:
            user_content.append({
                "type": "text",
                "text": f"Market day type classification:\n{json.dumps(regime, indent=2)}"
            })

        if recent_analyses:
            recent_summary = "\n".join([
                f"- {a.get('_timestamp', '?')}: {a.get('summary', 'no summary')}"
                for a in recent_analyses[-5:]
            ])
            user_content.append({
                "type": "text",
                "text": f"Recent triage results (for continuity):\n{recent_summary}"
            })

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                system=ANALYSIS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}]
            )

            text = response.content[0].text
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                result = {
                    "raw_analysis": text,
                    "parse_error": True
                }

            result['_model'] = 'sonnet'
            result['_timestamp'] = datetime.now(timezone.utc).isoformat()
            result['_image'] = image_path
            result['_input_tokens'] = response.usage.input_tokens
            result['_output_tokens'] = response.usage.output_tokens

            # Attach grade result if available
            if grade_result:
                result['grade'] = grade_result
                result['skipped_claude'] = False

            self._analysis_log.append(result)
            return result

        except Exception as e:
            print(f'[Analyzer] Analysis failed: {e}')
            return None

    def get_analysis_log(self) -> list:
        """Return all analyses from this session."""
        return self._analysis_log

    def get_token_usage(self) -> dict:
        """Summarize token usage across all analyses this session."""
        total_in = sum(a.get('_input_tokens', 0) for a in self._analysis_log)
        total_out = sum(a.get('_output_tokens', 0) for a in self._analysis_log)
        return {
            'total_analyses': len(self._analysis_log),
            'total_input_tokens': total_in,
            'total_output_tokens': total_out,
            'by_model': {
                'haiku': {
                    'count': sum(1 for a in self._analysis_log if a.get('_model') == 'haiku'),
                    'input_tokens': sum(a.get('_input_tokens', 0) for a in self._analysis_log if a.get('_model') == 'haiku'),
                    'output_tokens': sum(a.get('_output_tokens', 0) for a in self._analysis_log if a.get('_model') == 'haiku'),
                },
                'sonnet': {
                    'count': sum(1 for a in self._analysis_log if a.get('_model') == 'sonnet'),
                    'input_tokens': sum(a.get('_input_tokens', 0) for a in self._analysis_log if a.get('_model') == 'sonnet'),
                    'output_tokens': sum(a.get('_output_tokens', 0) for a in self._analysis_log if a.get('_model') == 'sonnet'),
                },
            }
        }


# Singleton
analyzer = HeatmapAnalyzer()
