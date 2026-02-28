# Claude Analysis Engine — Training & Architecture Overview

*Prepared for Justin — Feb 28, 2026*

---

## The Big Picture

There's no "training a Claude instance" in the traditional ML sense. You don't fine-tune Claude or create a persistent copy that remembers things between API calls. Instead, you **build intelligence through architecture** — a carefully constructed system prompt, cached reference knowledge, and a structured pipeline that feeds Claude exactly the right context at the right moment.

Think of it as: **Claude is the brain. We build the body around it.**

```
Chrome Extension (eyes)
    → Scraper JSON + Screenshot
    → Grader v3 (reflexes — instant, deterministic)
    → Claude Analysis (brain — pattern recognition, reasoning)
    → Greeks from OpenD (nervous system — contract-level data)
    → Contract Selector (decision-making)
    → Discord Alert (mouth)
```

---

## Part 1: How to "Train" Claude for Options Analysis

### What Claude Actually Does Per Request

Every API call to Claude is **stateless** — it has zero memory of previous calls. Its "knowledge" for each request comes entirely from:

1. **System Prompt** — permanent instructions defining who it is and how to think
2. **Cached Reference Context** — large knowledge base loaded via prompt caching (cheap after first call)
3. **Per-Request Context** — the specific capture data, grades, Greeks, and market state for this moment

The art is in constructing these three layers so Claude has everything it needs without burning excessive tokens.

### Layer 1: System Prompt (~2,000–4,000 tokens)

This is the "personality and methodology" layer. It doesn't change between captures — it defines *how* Claude thinks about options trading. Our current `ANALYSIS_SYSTEM_PROMPT` in `analyzer.py` is a solid start. It covers:

- Heatseeker node types and their meanings
- King Nodes, Gatekeepers, node interaction rules
- Pattern recognition (Whipsaw, Rainbow Road, Gatekeeper, Trend, Rug)
- Cross-index confluence requirements
- VIX regime interpretation
- Rate of change signals
- The Ten Commandments
- Day type classification

**What to add for contract selection:**

```
When recommending a specific options contract, evaluate using ALL available Greeks:

DELTA (Δ): Probability proxy & directional exposure
- 0DTE: Prefer 0.30-0.50 delta for directional, 0.15-0.25 for lottery plays
- Higher delta = more expensive, more likely profitable, lower % return
- Consider: if king is 0.5% away, you need enough delta to capture that move

GAMMA (Γ): Rate of delta change — your accelerator
- High gamma = contract value changes rapidly with underlying movement
- 0DTE gamma is EXTREMELY high near ATM — this is your edge AND your risk
- Near expiration: gamma concentrates at ATM, making ATM options explosive
- Use with Heatseeker: if price is approaching a bounce zone with high gamma, 
  the option will gain value rapidly if the bounce plays out

THETA (Θ): Time decay — your enemy on 0DTE
- 0DTE theta is brutal. A $2.00 option can lose $0.50/hour near close
- Enter early (10 AM-12 PM ET) to minimize theta damage
- Take profits quickly — don't hold for the last 20%
- If king is far from price and it's after 2 PM, theta likely kills the trade

VEGA (ν): Volatility sensitivity
- Less critical for 0DTE (vol is what it is intraday)
- More important for swing: if VIX king suggests vol mean-reversion,
  vega exposure matters for multi-day holds
- Selling premium? Watch vega — a VIX spike kills short vol positions

VANNA: Delta sensitivity to volatility changes
- When we have vanna data from Skylit: vanna shows WHERE vol changes
  will move delta, creating secondary directional forces
- Positive vanna + vol dropping = bullish delta shift
- Negative vanna + vol rising = bearish delta shift
- Cross-reference with VIX gamma king for expected vol direction

CHARM: Delta decay over time (delta's theta)
- Charm tells you how delta shifts as time passes
- Critical for 0DTE: an OTM call's delta drops throughout the day
  even if underlying doesn't move
- If you expect a late-day move to king, you need MORE delta now
  to still have enough delta later when the move happens

RHO (ρ): Interest rate sensitivity
- Negligible for 0DTE, minor for swing
- Include in data for completeness but don't weight in scoring

CONTRACT SELECTION RULES:
1. Start with the trade thesis (direction, target strike from king/gatekeeper analysis)
2. Find the option chain from OpenD for that expiry
3. Score contracts by: expected profit vs theta cost vs probability (delta)
4. Prefer options with bid-ask spread < 10% of premium (liquidity filter)
5. For 0DTE: ATM or 1 strike OTM. Avoid deep OTM lottery tickets unless
   the setup is exceptional (A+ grade, full confluence, clear air pocket to king)
6. Size: never risk more than 2% of account per trade
7. Always define exit before entry: profit target, stop loss, time stop

OUTPUT FORMAT for contract recommendation:
{
  "contract": "SPY 2026-03-03 690C",
  "underlying": "SPY",
  "strike": 690,
  "expiry": "2026-03-03",
  "type": "call",
  "entry_price_range": [1.50, 1.80],
  "greeks_at_entry": {
    "delta": 0.42,
    "gamma": 0.08,
    "theta": -0.35,
    "vega": 0.12,
    "implied_vol": 0.18
  },
  "profit_target": 2.70,
  "stop_loss": 0.90,
  "time_stop": "14:30 ET",
  "risk_reward": "1:2",
  "confidence": 8,
  "reasoning": "King at $690 with full trinity alignment..."
}
```

### Layer 2: Cached Reference Knowledge (~15,000–30,000 tokens)

This is the big win for cost optimization. Anthropic's **prompt caching** lets you load a large knowledge base once, and subsequent calls within 5 minutes (or 1 hour with extended TTL) read from cache at **90% discount**.

**What goes in the cached reference:**

1. **Full Skylit/Heatseeker Documentation** (~13KB / ~4,000 tokens)
   - We already have this in `research/skylit-docs.md`
   - Core concepts, patterns, node types, patternpedia, Ten Commandments
   - Case studies and examples

2. **Options Greeks Deep Knowledge** (~5,000-8,000 tokens)
   - Detailed explanation of each Greek and how it applies to 0DTE
   - Gamma exposure dynamics near expiration
   - Vanna-charm interaction effects
   - How dealer hedging flows create the patterns Heatseeker shows
   - Why gamma exposure at a strike creates a "magnet" or "wall"

3. **Justin's Trading Rules & Learnings** (~2,000-5,000 tokens)
   - This is where your accumulated knowledge goes
   - Lessons from past trades (what worked, what didn't)
   - Market-specific observations (e.g., "SPY pins more often on Fridays")
   - Personal risk parameters and sizing rules
   - Time-of-day patterns you've observed
   - Specific Heatseeker patterns you've verified through experience

4. **Historical Context** (~2,000 tokens)
   - Recent day types and how they played out
   - Running statistics (win rate, average R:R, common failure modes)
   - What the grader said vs what actually happened (calibration)

**How caching works in practice:**

```python
# First call of the session: writes cache (~$0.006 per 1K tokens for Sonnet)
# Subsequent calls within 5 min: reads cache (~$0.0003 per 1K tokens — 90% savings!)

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=2000,
    system=[
        {
            "type": "text",
            "text": ANALYSIS_SYSTEM_PROMPT,  # ~3,000 tokens
        },
        {
            "type": "text",
            "text": REFERENCE_KNOWLEDGE,      # ~20,000 tokens (Skylit docs + Greeks + learnings)
            "cache_control": {"type": "ephemeral"}  # Cache this block
        }
    ],
    messages=[{"role": "user", "content": per_request_context}]
)
```

**Cost math with caching (Sonnet):**
- Reference knowledge: ~20,000 tokens
- First call: 20K × $3.75/MTok = $0.075 (cache write)
- Subsequent calls (within 5 min): 20K × $0.30/MTok = $0.006 (cache read!)
- Per-request context: ~3,000 tokens × $3/MTok = $0.009
- Output: ~1,000 tokens × $15/MTok = $0.015
- **Total per analysis after first: ~$0.03** vs ~$0.09 without caching

With 5-min captures during a 6-hour trading day, that's ~72 captures. Even if all trigger Claude (they won't — grader filters most), that's 72 × $0.03 = **~$2.16/day for Sonnet**.

### Layer 3: Per-Request Context (~2,000–4,000 tokens)

This changes every capture. It includes:

1. **Grader Results** — quantitative scores from grader v3 (via `grade_context_for_claude()`)
2. **Scraped Node Data** — the actual GEX values from all 4 panels
3. **Market Data** — current SPY/QQQ/VIX prices from OpenD/yfinance
4. **Rate of Change** — how nodes shifted since last capture
5. **Confluence State** — current cross-index agreement level
6. **Market Regime** — trend/levels/whipsaw classification
7. **Option Chain + Greeks** — when Claude needs to pick a contract (new!)
8. **Previous Analysis Summary** — what Claude said last time (continuity)

---

## Part 2: Model Selection Strategy

### Recommended Tiered Approach

| Tier | Model | When | Cost | Purpose |
|------|-------|------|------|---------|
| **Filter** | Grader v3 | Every capture | $0.00 | Deterministic scoring — skip bad setups |
| **Triage** | Haiku 4.5 | Grade ≥ B | ~$0.003 | "Has anything meaningful changed?" |
| **Analysis** | Sonnet 4.5 | Triage escalates | ~$0.03 | Full pattern analysis + trade thesis |
| **Contract** | Sonnet 4.5 | Thesis is tradeable | ~$0.03 | Greeks analysis + specific contract pick |
| **Override** | Opus 4.5 | Unusual conditions | ~$0.15 | Complex/ambiguous situations only |

**Why Sonnet, not Opus, for most analysis?**
- Opus 4.5 is $5/$25 per MTok (input/output) — 1.7x Sonnet's cost
- For structured data analysis with clear rules, Sonnet performs comparably
- Opus adds value for ambiguous situations, novel patterns, or complex multi-factor reasoning
- Budget recommendation: Sonnet for 95% of calls, Opus for the 5% edge cases

**When to escalate to Opus:**
- Contradictory signals (e.g., SPXW bullish, SPY bearish, QQQ unclear)
- Novel pattern the system hasn't seen (grader scores don't match visual)
- High-stakes decision (unusually large position, OPEX week, extreme VIX)
- System self-check: periodic "review the last 10 trades" analysis

### Cost Projections ($100/mo budget)

**Conservative scenario (20 trading days, 6 hrs/day, 5-min captures):**
- 72 captures/day × 20 days = 1,440 captures/month
- Grader filters ~60%: 576 sent to Haiku triage
- Haiku escalates ~40%: 230 sent to Sonnet analysis
- Sonnet recommends trade ~30%: 69 sent to contract selection
- Opus overrides: ~5 per month

| Component | Calls/mo | Cost/call | Monthly |
|-----------|----------|-----------|---------|
| Grader | 1,440 | $0.00 | $0.00 |
| Haiku triage | 576 | $0.003 | $1.73 |
| Sonnet analysis | 230 | $0.03 | $6.90 |
| Sonnet contract | 69 | $0.03 | $2.07 |
| Opus override | 5 | $0.15 | $0.75 |
| **Total** | | | **~$11.45/mo** |

Well within budget. Even at 2x the capture rate, you're under $25/mo.

---

## Part 3: The Knowledge Base — What to Seed

### File: `knowledge/heatseeker-reference.md` (auto-loaded into cache)

You already have `research/skylit-docs.md`. This becomes the core cached reference. Add sections for:

1. **Pattern Recognition Guide** — for each of the 5 Heatseeker patterns, include:
   - Visual description
   - Entry/exit rules
   - Historical success rates (as you collect them)
   - Common traps and failure modes

2. **Node Behavior Rules**
   - 1st touch: 100% strength
   - 2nd touch: ~66% strength (use for scale-in, not fresh entry)
   - 3rd+ touch: ~33% (node is likely broken)
   - King shift = full thesis reset
   - Reshuffle = stand aside

3. **Cross-Index Rules**
   - "Would this thesis hold on QQQ if I'm trading SPY?"
   - Floor on SPX prevents rug on QQQ
   - Ceiling on SPY prevents rally on SPX

### File: `knowledge/greeks-reference.md` (auto-loaded into cache)

Deep knowledge on all 7 Greeks as they apply to 0DTE and short-dated options:

- **Delta**: probability proxy, directional exposure, how it changes intraday
- **Gamma**: the accelerator, why it's king for 0DTE, gamma squeeze mechanics
- **Theta**: the killer, time decay curves, when it bites hardest
- **Vega**: vol sensitivity, less important for 0DTE, critical for swing
- **Vanna**: delta's response to vol changes, cross-ref with VIX gamma
- **Charm**: delta decay over time, why morning entries need less delta than afternoon
- **Rho**: interest rate sensitivity (minor but included for completeness)

Also include:
- How dealer gamma hedging creates the flows Heatseeker shows
- Why positive gamma = absorption (dealers buy dips, sell rips = pinning)
- Why negative gamma = amplification (dealers sell into dips, buy into rips = trend)
- Gamma flip line and its significance
- Open interest dynamics

### File: `knowledge/trading-rules.md` (your personal learnings)

This is the file YOU maintain. It starts sparse and grows with experience:

```markdown
# Justin's Trading Rules & Learnings

## Hard Rules (non-negotiable)
- Max 2% of account per trade
- No new positions after 3:00 PM ET
- Full trinity confluence required for >1% account size
- Always define exit before entry

## Lessons Learned
- (add as you go)
- "SPXW king at round numbers (5900, 6000) tends to be stronger"
- "When VIX is dropping and SPY nodes are accumulating, the move is real"
- "Friday afternoon pins happen 70# Claude Training Architecture — Part 2: Implementation & Pipeline

---

## Part 4: The Contract Selection Pipeline

### What Happens When a Capture Exceeds Threshold

```
1. CAPTURE arrives (screenshot + scraped JSON)
        ↓
2. GRADER scores all panels (instant, free)
   Result: SPXW 72% (A), SPY 65% (A), QQQ 48% (B)
        ↓
3. HAIKU TRIAGE (cheap, fast — $0.003)
   "Has anything changed meaningfully since last capture?"
   Result: "Yes — SPY king shifted from $688 to $690, nodes accumulating"
        ↓
4. SONNET ANALYSIS with cached knowledge (the "brain" — $0.03)
   Input: grader scores + scraped data + market data + VIX + confluence + regime
   Cached: Heatseeker docs + Greeks reference + your trading rules
   Result: "Bullish thesis on SPY. King at $690, full confluence,
            price at $686 with bounce zone. Enter on rejection at $686."
        ↓
5. GREEKS FETCH from OpenD (free — just API call)
   Get option chain for SPY 0DTE
   For strikes $685-$692, fetch: delta, gamma, theta, vega, IV, bid, ask, volume, OI
        ↓
6. CONTRACT SELECTION via Sonnet ($0.03)
   Input: trade thesis + full option chain with Greeks + account balance
   Output: specific contract recommendation with entry/exit/sizing
        ↓
7. DISCORD ALERT
   "🟢 SPY LONG | $687 Call @ $1.65 | Target $2.80 | Stop $0.95
    Grade: A (65%) | Confluence: STRONG | King: $690
    Delta: 0.42 | Gamma: 0.08 | Theta: -0.35
    R:R 1:1.7 | Confidence: 7/10"
```

### Step 5 Detail: Fetching Greeks from OpenD

The moomoo `get_market_snapshot()` function returns Greeks for option contracts. Here's how we'll use it:

```python
# In market_data.py — new function

def get_option_chain_with_greeks(underlying: str, expiry: str, 
                                  strike_range: tuple = None) -> list:
    """
    Fetch option chain with Greeks for contract selection.
    
    Args:
        underlying: "US.SPY" or "US.QQQ"
        expiry: "2026-03-03" (YYYY-MM-DD)
        strike_range: (low, high) to filter strikes near price
    
    Returns: list of dicts with strike, type, bid, ask, last, volume, OI,
             delta, gamma, theta, vega, rho, implied_vol
    """
    # Step 1: Get option chain codes
    ret, data = quote_ctx.get_option_chain(
        code=underlying,
        start=expiry,
        end=expiry
    )
    # data contains option codes like "US.SPY260303C687000"
    
    # Step 2: Filter to strikes near our target
    if strike_range:
        filtered = [code for code in data if low <= strike <= high]
    
    # Step 3: Get snapshot with Greeks for each option
    # get_market_snapshot returns: 
    #   last_price, bid, ask, volume, open_interest,
    #   option_implied_volatility, option_delta, option_gamma,
    #   option_theta, option_vega, option_rho
    ret, snapshot = quote_ctx.get_market_snapshot(filtered_codes)
    
    # Step 4: Format for Claude
    contracts = []
    for row in snapshot.iterrows():
        contracts.append({
            "code": row["code"],
            "strike": row["option_strike"],
            "type": "call" if row["option_type"] == "CALL" else "put",
            "expiry": expiry,
            "last": row["last_price"],
            "bid": row["bid_price"],
            "ask": row["ask_price"],
            "spread_pct": (row["ask_price"] - row["bid_price"]) / row["ask_price"] * 100,
            "volume": row["volume"],
            "open_interest": row["open_interest"],
            "greeks": {
                "delta": row["option_delta"],
                "gamma": row["option_gamma"],
                "theta": row["option_theta"],
                "vega": row["option_vega"],
                "rho": row["option_rho"],
                "iv": row["option_implied_volatility"],
            }
        })
    
    return contracts
```

**Important moomoo constraint:** `get_market_snapshot()` has a rate limit of 60 requests per 30 seconds. For a typical 0DTE chain with ~20 relevant strikes (calls + puts), that's 1 request (you can batch up to ~400 codes per call). No issue.

**Subscription note:** Snapshot calls don't consume subscription quota — only `subscribe()` does. This is perfect for our use case since we only need Greeks at the moment of contract selection, not streaming.

### Step 6 Detail: Contract Selection Prompt

This is a separate, focused Claude call. It gets the trade thesis from step 4 and the full Greeks data from step 5:

```python
CONTRACT_SELECTION_PROMPT = """Given the following trade thesis and option chain data,
select the optimal contract.

TRADE THESIS:
{thesis}

OPTION CHAIN (0DTE {underlying}, {expiry}):
{option_chain_json}

ACCOUNT CONTEXT:
- Balance: ${balance}
- Max risk per trade: 2% = ${max_risk}
- Current positions: {positions}

Select the best contract considering:
1. Delta matches conviction level (higher confidence = higher delta)
2. Gamma provides enough acceleration for the expected move
3. Theta is manageable given expected time-to-target
4. Bid-ask spread is < 10% of premium (liquidity)
5. Volume > 100 (sufficient liquidity)
6. Contract price allows proper sizing within risk limits
7. If vanna data available: does vanna alignment boost or hurt this delta exposure?
8. Charm consideration: will delta decay before the expected move completes?

Return JSON with your contract recommendation and full reasoning."""
```

### Step 7 Detail: Discord Alert Format

```python
# In a new alerts.py module

def format_discord_alert(analysis, contract, grade):
    """Format a Discord DM alert for a trade recommendation."""
    
    direction = "🟢 LONG" if contract["type"] == "call" else "🔴 SHORT"
    ticker = contract["underlying"]
    strike = contract["strike"]
    
    alert = f"""**{direction} {ticker}** | {contract['expiry']}
    
**Contract:** ${strike} {'Call' if contract['type']=='call' else 'Put'} @ ${contract['entry_price']:.2f}
**Target:** ${contract['profit_target']:.2f} ({contract['target_pct']:.0f}% gain)
**Stop:** ${contract['stop_loss']:.2f} ({contract['stop_pct']:.0f}% loss)
**R:R:** {contract['risk_reward']}

**Greeks:**
Δ {contract['greeks']['delta']:.2f} | Γ {contract['greeks']['gamma']:.3f} | Θ {contract['greeks']['theta']:.2f} | ν {contract['greeks']['vega']:.3f} | IV {contract['greeks']['iv']:.1f}%

**Heatseeker:**
Grade: {grade['intraday']['grade']} ({grade['intraday']['pct']:.0f}%)
King: ${grade['intraday']['breakdown']['king_quality']['king_strike']}
Confluence: {grade['intraday']['breakdown']['trinity']['alignment']}
Pattern: {grade.get('pattern', 'mixed')}

**Confidence:** {'🟢' * contract['confidence']}{'⚪' * (10-contract['confidence'])} {contract['confidence']}/10

**Thesis:** {contract['reasoning'][:200]}"""
    
    return alert
```

---

## Part 5: Setting Up the Knowledge Base Files

### Directory Structure

```
heatseeker-system/
  backend/
    knowledge/                    ← NEW: cached knowledge base
      heatseeker-reference.md     ← Skylit docs (already have this)
      greeks-reference.md         ← Deep Greeks knowledge
      trading-rules.md            ← YOUR personal rules & learnings
      market-patterns.md          ← Historical patterns observed
    prompts/                      ← NEW: prompt templates
      system-analysis.md          ← Main analysis system prompt
      system-contract.md          ← Contract selection system prompt  
      system-triage.md            ← Triage system prompt
    analyzer.py                   ← Updated to use knowledge/ and prompts/
    contract_selector.py          ← NEW: Greeks + contract selection
    alerts.py                     ← NEW: Discord alert formatting
    ...
```

### How to Add Your Knowledge

The `knowledge/trading-rules.md` file is yours to maintain. Every time you learn something from a trade, add it. Claude reads this at the start of every analysis. Over time, it becomes your edge.

**Format it for Claude** — not for humans. Be specific and actionable:

```markdown
❌ "Sometimes SPY pins on Fridays"
✅ "SPY pins within 0.3% of the largest positive gamma node 73% of Fridays 
    when VIX is below 20. Weight Friday pin setups 1.5x on the king quality score."

❌ "Be careful with QQQ"
✅ "QQQ king nodes are less reliable than SPY when QQQ has more than 4 nodes 
    above $5M absolute value (scattered structure). Require A grade minimum 
    for QQQ trades, vs B+ for SPY."
```

### Feeding Additional Knowledge

You mentioned you're "still collecting additional knowledge and learnings." Here's how to add them:

1. **Heatseeker patterns you observe** → Add to `knowledge/market-patterns.md`
2. **YouTube/Twitter learnings from Glitch, Giul, etc.** → Distill key rules into `knowledge/trading-rules.md`
3. **Backtesting results** → When we have grade vs outcome data, add to `knowledge/market-patterns.md`
4. **New Greeks insights** → Add to `knowledge/greeks-reference.md`
5. **Market structure learnings** → Add to the system prompt's VIX/regime sections

The knowledge files are **loaded into the cached context block**, so they cost almost nothing to include after the first call (90% discount on cache reads). Don't worry about length — 30K tokens of cached reference costs ~$0.009 per call to read.

---

## Part 6: Implementation Roadmap

### Phase 1: Knowledge Base Setup (this week)
- [ ] Create `knowledge/` directory with reference files
- [ ] Move Skylit docs into `knowledge/heatseeker-reference.md`
- [ ] Write `knowledge/greeks-reference.md` (comprehensive Greeks guide)
- [ ] Create `knowledge/trading-rules.md` (starter template for Justin)
- [ ] Refactor `analyzer.py` to load knowledge files into cached system prompt
- [ ] Add explicit cache breakpoints for the knowledge block

### Phase 2: Greeks Pipeline (after OpenD is configured)
- [ ] Add `get_option_chain_with_greeks()` to `market_data.py`
- [ ] Build `contract_selector.py` — takes thesis + Greeks → contract recommendation
- [ ] Test with paper trading option chain data
- [ ] Validate Greeks values match moomoo app display

### Phase 3: Alert System
- [ ] Build `alerts.py` — format Discord DM alerts
- [ ] Integrate with OpenClaw's Discord messaging (Skylark sends the alert)
- [ ] Add alert toggles (enable/disable, quiet hours, confidence threshold)
- [ ] Test end-to-end: capture → grade → analyze → contract → Discord DM

### Phase 4: Learning Loop (ongoing)
- [ ] After each trading day, review trades vs recommendations
- [ ] Update `trading-rules.md` with new learnings
- [ ] Track grader accuracy: did A-graded captures produce winning trades?
- [ ] Adjust grader thresholds based on data
- [ ] Monthly: review full month's recommendations vs outcomes, tune system

---

## Part 7: Key Decisions to Make

### 1. Model for Analysis: Sonnet vs Opus

**Recommendation: Start with Sonnet 4.5 ($3/$15 per MTok)**

Sonnet is excellent at structured analysis with clear rules. Opus adds reasoning depth but at 1.7x cost. Start with Sonnet, track accuracy, escalate to Opus only for ambiguous situations.

You said "Opus" — we can absolutely use Opus for the main analysis if you prefer the extra reasoning power. At ~$0.09/call instead of ~$0.03/call, the monthly difference is:
- 230 analyses/mo × $0.06 delta = **~$14/mo extra** for Opus everywhere
- Total: ~$25/mo instead of ~$11/mo — both well within budget

If you want the best reasoning regardless of the small cost difference, Opus is a fine choice.

### 2. When to Fetch Greeks

**Recommendation: Only when Claude recommends a trade**

Don't fetch the full option chain every capture — that wastes OpenD rate limit budget. Only fetch when:
1. Grader passes threshold (A grade)
2. Claude analysis produces a clear directional thesis
3. Claude says "trade this" → THEN fetch Greeks → THEN pick contract

### 3. How Much Knowledge to Cache

**Recommendation: Start at ~15K tokens, grow to ~30K**

- Skylit docs: ~4K tokens
- Greeks reference: ~5K tokens
- Trading rules: ~2K tokens (growing)
- Historical patterns: ~2K tokens
- Total: ~13K tokens initially

As you add learnings, this grows. The 1-hour cache TTL ($6/MTok for writes) is worth it if you're capturing every 5 minutes — the cache stays warm all trading day for one write cost.

### 4. Alert Confidence Threshold

**Recommendation: Start at confidence ≥ 7/10**

Only send Discord alerts when Claude's confidence is 7+ out of 10. Lower confidence = log it but don't alert. You can adjust this threshold as you calibrate trust in the system.

---

## Summary

There is no "trained Claude instance" — instead, you build a **knowledge-augmented pipeline**:

1. **System prompt** = Claude's methodology (~3K tokens, always sent)
2. **Cached knowledge base** = Skylit docs + Greeks + your rules (~15-30K tokens, cached at 90% discount)
3. **Per-request context** = grader scores + scraped data + market state (~3K tokens, fresh each call)
4. **Greeks pipeline** = OpenD option chain fetched only when needed
5. **Contract selector** = focused Claude call with thesis + Greeks → specific recommendation
6. **Discord alerts** = formatted recommendation sent to your DM

The system gets smarter as YOU add learnings to `knowledge/trading-rules.md`. Claude doesn't learn between calls — but your knowledge base does.

Total estimated cost: **$11-25/month** depending on model choice. Well within $100/mo budget.
