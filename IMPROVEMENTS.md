# Probability Cup — Performance Improvement Plan

**Goal:** dramatically raise our Smart Rating (cumulative Relative Brier Points percentile) on the Jump Trading Probability Cup. Everything proposed here is **100% free**.

This document (1) explains the competition and what actually drives score, (2) diagnoses *why the current system scores poorly* with concrete file references, and (3) lays out a prioritized set of changes. Implementation comes after you approve the plan.

---

## 1. How the competition actually works (and what that means for us)

- **What it is:** binary (yes/no) probability forecasting on FIFA World Cup 2026 matches. ~72 group-stage matches (up to ~104 total), **~10 markets per match**. We submit an integer **1–99** per market before kickoff (`closingtime` = match start). We can **revise with `PATCH` until close**; the *last* value at close is scored.
- **Scoring:** per settled market, Brier = `(p − o)²` (p = our prob as 0–1, o = outcome 0/1). Then
  **`RBP = (crowd_brier − user_brier) × 100`**. Cumulative RBP → **percentile vs all participants** (Smart Rating).
- **Stage weights:** group **1×**, knockout **2×**, final **3×**.
- **We are scored *relative to the crowd*, and we cannot see the crowd's prices** (probability markets return no `currentprice`). The crowd is a mix of casual humans and *clueless LLM bots* (the MCP path). That is our opportunity: **the bar is the crowd's calibration, not perfection.**

### The math that should drive every decision

Because the crowd term in RBP doesn't depend on our `p`, **maximizing expected RBP is exactly minimizing our own expected Brier.** Minimizing `q(1−p)² + (1−q)p²` gives `p* = q`: **submit your honest, calibrated probability.** Brier is *strictly proper* — naïve shading toward or away from the extremes only *hurts* expected score.

Three consequences that the current code gets wrong:

1. **Don't artificially compress to 15–85.** That only makes sense as *calibration shrinkage* when the model is over-confident — not as a blanket rule. Capping kills RBP on markets that genuinely are near-certain (e.g. a heavy favorite scoring ≥1 goal).
2. **Edge = (crowd is wrong) × (we are right).** RBP grows with the *squared distance between crowd and truth* in our favor. So the money is in markets where the crowd is *predictably miscalibrated*:
   - **Compound "A AND B" markets:** humans/uninformed bots overestimate conjunctions → true joint prob is low → **shade down**.
   - **Name-anchored coin-flips** ("more 2nd-half corners/SoT than the other team"): crowd drifts to 60–70% on the famous team; truth ≈ 50–55% → **pull toward base rate**.
   - **Structural base rates** the crowd ignores: 2nd halves average *more* goals/corners/cards than 1st halves (fatigue, chasing) → "will 2nd half have more X than 1st" is **>50%** by default.
3. **Rank objective, not mean:** Smart Rating is a percentile. Defend a lead by hugging consensus; take more variance on our *highest-conviction* edges when climbing, scaled down in 2×/3× matches where the convex penalty is multiplied.

---

## 2. Why we're scoring poorly — root-cause diagnosis

These are the concrete defects, roughly in order of how much they hurt us.

### 2.1 The simulation engine produces 0.50 for ~70% of markets (critical)
`src/engine.py` only knows **four** market types in `_extract_market_probability` (`match_result`, `total_goals`, `both_teams_score`, `corners_threshold`). Everything else returns the hard-coded default **`prob = 0.50`**. Worse, `_simulate_single_match` only generates **goals, corners, cards, penalty, red card** — it never simulates **shots, shots on target, offsides, fouls**, even though `_calculate_params` computes lambdas for them.

The real markets (from `data/predictions/IRQ_vs_NOR_*.md`) are dominated by exactly the unsupported types: fouls comparison, offsides count, shots-on-target threshold/comparison (often half-restricted), team-to-score, half-specific goals, player goal/assist, penalty-or-red. **For most markets the "Monte Carlo" is feeding the AI a meaningless 0.50.**

### 2.2 `match_result` ignores which team the question is about (bug)
`_extract_market_probability` computes `P(home_goals > away_goals)` for *every* `match_result` market. If the question is "Will *Norway* (away) win?", it still returns the *home* win prob. Draw handling is also wrong for a single-team "to win" question.

### 2.3 If the AI returns an empty list, **every market becomes 50%** (critical, silent)
In `predictor.py::predict`, `generate_predictions` swallows its own exceptions and returns `[]`. The fallback sim (`_fallback_predictions`) only runs on a *raised* exception — so an empty return goes straight to `_validate_and_clamp([])`, which **fills all markets with 50** and a "Fallback prediction" note. A single JSON-parse failure, quota hit, or **non-existent model ID** ⇒ a whole match submitted at 50/50 ⇒ guaranteed ≈0 RBP. This may be silently happening on many matches.

### 2.4 Model IDs may not exist on the free tier (critical to verify)
`config.py` uses `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `gemma-4-31b-it`. If any of these aren't valid free-tier model names, calls fail → §2.3 path → 50/50. **Must be verified against the live Gemini API**, with a real fallback chain.

### 2.5 The prompts contain a false "magic number" and misframe the strategy
Both bot prompts in `predictor.py` tell the model to detect a **"hardcoded fallback baseline of exactly 1.5 Goals Scored and 1.0 Goals Conceded."** The engine's actual defaults are **1.2** (no team) or **1.25/1.25** (missing keys) — *never* 1.5/1.0. The model is hunting for a signal that can never appear. The prompts also enshrine the 15–85 compression (§1.1) and tell Flash it has "15 minutes to think" (it doesn't).

### 2.6 We have almost no real data — and zero market/odds signal (the biggest lever)
- Per your note, web scraping effectively only works for **Wikipedia**; FBref blocks scrapers, so `scrape_team_stats_fbref` almost always falls through to a thin Wikipedia goals-for/against parse. The granular per-team rates the engine needs (corners, fouls, offsides, shots, SoT) are **not being collected** — they sit at defaults.
- News is just **RSS headline titles+descriptions**, AI-summarized. No lineups feed, no real injury feed, no xG.
- **There is no bookmaker-odds / market-consensus signal at all.** Devigged odds are the single most predictive *free* input for match-result/totals/BTTS and are the best available proxy for "the crowd." Its absence is the biggest miss.

### 2.7 The calibration loop is a no-op (high leverage, currently 0%)
`src/calibrator.py::run_full_calibration` fetches `/results` and then **does nothing** — no Brier computed, no team rates updated from actual outcomes, no per-market-type bias correction. The comments literally describe the intended logic as a TODO. Calibration is the *cheapest* path to RBP (it raises score without better raw prediction) and it's completely unimplemented.

### 2.8 Submit-once, never refine
`main.py` marks a match `predicted_final` and skips it forever. We never `PATCH` to incorporate confirmed lineups (which land ~60 min pre-kickoff). The API explicitly rewards late refinement (last value at close is scored).

### 2.9 The two bots aren't meaningfully different
Bot 2's "edge" in the fallback is literally `±0.03` off the sim; via the AI it shares the same garbage sim + same data. We're spending our 2-bot budget on near-duplicates instead of two genuinely different strategies (e.g. model-anchored vs crowd-divergence).

### 2.10 Smaller issues
- `get_upcoming_matches` triggers off `opening_time` within `[0, window]`; if a cycle is missed the match falls out of the window and is **never predicted**. Markets also close at kickoff, so the T-0…T-60 window risks racing the close.
- `_validate_and_clamp` fills *missing* markets with 50 rather than the sim/base-rate value.
- `total_goals`/`corners_threshold` grab the **first integer** in the question as the threshold — fine for "3 or more total goals," but fragile for questions with other embedded numbers.
- No base-rate priors anywhere (every unknown defaults to 50 or an arbitrary constant).

---

## 3. The improvement plan (prioritized by impact ÷ effort)

### Tier 0 — Stop the bleeding (correctness; do first, ~1 day)
- **0.1** Fix the empty-list trap (§2.3): when the AI yields nothing/partial, fall back to the **quant model / base rate per market**, never blanket 50. Make `_validate_and_clamp` backfill missing markets from the model, not 50.
- **0.2** Verify Gemini model IDs against the live API; pin to confirmed free-tier models with a real fallback chain; **log which model actually answered**. Add a startup self-test.
- **0.3** Fix `match_result` to read the *named* team and compute that team's win prob (and handle draw-as-no). Generally, make market scoring team-aware.
- **0.4** Remove the false 1.5/1.0 instruction from prompts; make the "is the model blind?" signal a real flag passed in data (e.g. `data_quality: "prior_only" | "modeled"`).

### Tier 1 — Free data that actually moves Brier (the biggest lever, ~2–3 days)
This is where most of the score lives. Concrete, free sources:

- **1.1 National-team results dataset (free, the keystone):**
  `martj42/international_results` (GitHub, CC0) — every international match since 1872, updated continuously: `results.csv`, `shootouts.csv`, **`goalscorers.csv`**. Commit a snapshot + refresh in `collect`. From it we compute *per national team*: recent form, goals for/against rates, BTTS rate, over/under rates, clean-sheet rate, 1st-vs-2nd-half goal splits — i.e. **real Poisson inputs for actual national teams**, which FBref never gave us. `goalscorers.csv` gives **player anytime-scorer base rates** for the player markets.
- **1.2 Elo ratings (free):** `eloratings.net` (downloadable) or compute Elo ourselves from 1.1. Elo difference → calibrated win/draw/loss and an expected-goals supremacy, the strongest cheap prior for match-result, team-to-score, and totals — and it works from match 1 (no in-tournament data needed). **This directly fixes the early-tournament "engine is blind" problem.**
- **1.3 Bookmaker odds — the crowd proxy (free tier):** `the-odds-api.com` free tier = 500 req/month, soccer incl. World Cup, markets `h2h` / `totals` / `btts`. **Devig** (remove the overround) → true implied probabilities for result/totals/BTTS. 104 matches × a couple refreshes fits inside 500/mo. This is both a top-quality signal *and* our best estimate of the crowd to diverge from. (Note: free tier won't cover exotic props — those stay model+base-rate driven.)
- **1.4 Structural base-rate table (free, static):** precompute base rates for the exotic/mechanical markets (penalty-or-red ≈ X%, ≥N cards, offsides ≥2, 2nd-half > 1st-half goals/corners, etc.) from 1.1 and public football analytics. These are strong priors that beat 50% with zero per-match data.
- **1.5 Keep RSS/news only as a qualitative overlay** for injuries/lineups/motivation — not as the stats backbone. Optionally add **Gemini Google-Search grounding** (free within Gemini quota) to fetch confirmed lineups at T-60 instead of fragile scraping.

- **1.6 Reddit public-sentiment signal (free, and strategically the best fit for this competition).**
  Because RBP scores us *relative to the crowd* and the API hides the crowd's prices, **our hardest problem is modeling the crowd** — and Reddit is the best free proxy for public sentiment we can get. It plays two roles:

  **(a) Crowd model (the core use).** Scrape match-relevant discussion and quantify what the public believes and how strongly, then **fade predictable public bias** — exactly what wins RBP. Public biases to target: recency bias, **star-player / big-nation over-hype**, narrative-driven over/under leans, and **over-pricing of compound "A AND B" bets**. This is the literal data source for Bot 2's "model the naïve crowd and bet the gap" mandate (§3.2, §4.3) — it stops being guesswork.

  **(b) Fast qualitative info.** Match threads post ~1h pre-kickoff with **confirmed lineups, late injuries, suspensions, weather, motivation/rotation intel** — ideal for the T-60 `PATCH` cycle (§6.1).

  **Sources (most useful first):** `r/SoccerBetting` (value/consensus picks — the sharpest read on public lean), `r/soccer` (pre-match + match threads, news — the highest-volume soccer sub), `r/worldcup`, `r/football` (active but smaller/more casual & international than r/soccer — secondary signal), and national-team subs.

  > **Verification note:** Reddit now **blocks unauthenticated/raw requests** (an automated `about.json` fetch from this environment returned **HTTP 403** and served the web-app HTML). `r/football` does exist and is active, but this 403 is exactly why we should collect via the **official Reddit API (PRAW/OAuth)** below rather than raw scraping. Confirm each subreddit's live activity once the API app is registered.

  **Free, ToS-safe collection (two paths, auto-selected):**
  - *Primary:* the **official Reddit API via PRAW** (read-only: `client_id`/`secret`/`user_agent`, no username/password) — used when Reddit credentials are configured.
  - *Fallback (no credentials needed):* **Gemini Google-Search grounding** queried over the SAME subreddits (`r/SoccerBetting`, `r/soccer`, `r/worldcup`, `r/football`), returning the same structured sentiment JSON. Runs on the separate 1500/day grounding quota, is robust from datacenter IPs (Gemini is the client, not us scraping Reddit), and sidesteps Reddit app-registration entirely. `quick_refresh` tries PRAW first, then falls back to grounding.

  Only fetch for matches inside the prediction window to respect rate limits.

  **Turning it into a signal:** collect post titles + top (upvote-weighted) comments, then run a new `extract_sentiment()` AI pass → structured JSON per match: `public_favorite`, `lean_strength` (0–1), `hype_level`, `betting_consensus`, `key_info[]` (lineups/injuries with a `credibility` flag), and per-market public leans where present. Weight by subreddit reliability and upvotes; dedupe.

  **How we exploit it (concrete):**
  - When Reddit is **euphoric about a favorite/star** (esp. player anytime-scorer markets), the crowd's submitted probs are likely too extreme → our honest calibrated prob is closer to truth → large RBP when we're right. **Fade the hype** in proportion to `lean_strength × hype_level`.
  - When Reddit consensus **agrees with both our model and the odds**, treat it as confirmation → modest confidence boost.
  - Feed `betting_consensus` into Bot 2 as the explicit crowd estimate to diverge from; size the divergence by stage weight (smaller in 2×/3×) and our standing (§3.3).

  **Honest limitations (so we don't over-trust it):** Reddit is a *correlated proxy* for the SportsPredict crowd (humans + LLM bots), not the crowd itself — directional, not precise. It's noisy (needs upvote-weighting + AI filtering) and says little about obscure props (offsides, 2nd-half corner/SoT comparisons), so its value concentrates on **result / totals / BTTS / player** markets. Use it to *tilt*, never to override the quant model + odds.

> Note: we will *not* revive API-Football / football-data (they gave no benefit). The datasets above are different in kind — national-team-complete, odds, base rates, and crowd sentiment.

### Tier 2 — A real modeling engine (~2–3 days)
- **2.1** Replace the ad-hoc Poisson with a **bivariate/Dixon–Coles goals model** seeded by Elo (1.2) + team rates (1.1) + odds (1.3, blended/anchored). Output a full joint distribution of (home goals, away goals) **by half**.
- **2.2** Implement a **market-mapping layer that covers every observed type**: match_result (team-aware), total_goals (≥N), BTTS, half-comparison, half-specific team goal, corners threshold/comparison (with half split), cards ≥N, fouls comparison, offsides ≥N, SoT threshold/comparison (half), penalty-or-red, player goal/assist, player SoT, **compound AND/OR** (combine sub-probabilities with correlation, *not* naïve independence — and remember the crowd over-prices these).
- **2.3** Where we lack a real distribution (some props), fall back to the **base-rate table (1.4)** tilted by team strength — never 0.50.
- **2.4** Simulate shots/SoT/offsides/fouls (currently missing) or model them analytically from rates.

### Tier 3 — Probability strategy under crowd-relative Brier (~0.5 day)
- **3.1** Submit **honest calibrated probabilities**; drop the blanket 15–85 clamp (keep only a tiny 1–99 safety clamp).
- **3.2** Apply **crowd-divergence rules** as a deliberate, small post-process: shade compound-AND down; pull name-anchored coin-flips toward base rate; apply 2nd-half structural priors.
- **3.3** Scale aggressiveness by **stage weight** (tighter in 2×/3×) and by **standing** (variance-seek when climbing, hug consensus to defend).

### Tier 4 — AI redesign (the LLM as adjuster, not oracle) (~1 day)
- **4.1** Reposition the AI: it receives the **quant model output + devigged odds + base rates + news**, and only *adjusts* for qualitative factors (injuries, lineups, motivation, weather). It does not invent base numbers.
- **4.2** Rewrite both prompts: remove false magic numbers and fake "15-minute thinking"; give the model the **market semantics**, the **model probability**, the **base rate**, and an explicit instruction to output *honest* probabilities + a confidence. Use structured JSON output with per-market reasoning.
- **4.3** Make the two bots genuinely different: **Bot 1 = model/odds-anchored calibrated**; **Bot 2 = crowd-divergence/contrarian** that models the crowd from **real Reddit sentiment (§1.6)** + odds and bets the measured gap (rather than imagining what the crowd thinks). Two distinct leaderboard entries with distinct edges.

### Tier 5 — Make calibration real (highest leverage-per-line) (~1 day)
- **5.1** Implement `calibrator.py`: pull `/results`, compute our Brier per market, **track reliability by market type and probability bucket**, and fit an **isotonic/Platt recalibration** applied to future submissions.
- **5.2** Update **team rate estimates from actual settled match stats** (rolling averages) so the model learns through the tournament.
- **5.3** Detect systematic bias per market type (e.g. "we over-predict totals in group stage") and feed a correction back into Tier 2/3. Persist all of this in Firestore and surface it.

### Tier 6 — Submission timing & refinement (~0.5 day)
- **6.1** Predict **early** to lock a position on every market (capture base-rate edge even if a cycle is later missed — fixes §2.10), then **`PATCH`** at T-60…T-75 once lineups are confirmed.
- **6.2** Allow re-prediction (drop the permanent `predicted_final` lock; track `last_submitted` / `last_patched` instead) and guarantee no match is ever left unpredicted before close.
- **6.3** Spend more compute/care on **knockout (2×) and final (3×)** matches.

### Tier 7 — Hygiene
- **7.1** Threshold parsing: parse "N or more / over N.5 / at least N" robustly instead of "first integer."
- **7.2** Confirm `opening_time` vs `closing_time` semantics from the live API and trigger off the correct one relative to kickoff.
- **7.3** Secrets are correctly gitignored (`.env`, both credential files) — verify they were never committed in history (`git log` for those paths) and rotate if they were.

---

## 4. Proposed pipeline (target architecture)

```
COLLECT (every 3h)
  • Refresh international results + goalscorers (martj42)  → team & player base rates
  • Refresh / recompute Elo                                → strength priors
  • Pull devigged bookmaker odds (the-odds-api, budgeted)  → crowd proxy + strong signal
  • Refresh news/lineups (RSS + optional Gemini grounding) → qualitative overlay
  • Scrape Reddit (r/SoccerBetting, r/soccer, r/worldcup, r/football) → public-sentiment / crowd model
  • Persist everything to Firestore

PREDICT (every 30m; acts on matches nearing close)
  • Build per-match goals model (Dixon–Coles seeded by Elo+rates, anchored to odds)
  • Map ALL ~10 market types → model probabilities (base-rate fallback, never 0.50)
  • Refresh Reddit match threads (~T-60) → confirmed lineups + live public lean
  • Bot 1 (calibrated/odds-anchored) + Bot 2 (crowd-divergence vs Reddit sentiment) via AI adjuster
  • Apply calibration correction (Tier 5) + strategy rules (Tier 3)
  • Submit batch early; PATCH at T-60 after lineups
  • Apply recalibration learned from settled results

CALIBRATE (daily)
  • Score settled results, compute our Brier, update reliability curves
  • Update team rolling rates from actual match stats
  • Refit isotonic/Platt; detect & store per-type bias
```

---

## 5. Suggested order of execution

1. **Tier 0** (correctness — quick, stops silent 50/50 disasters).
2. **Tier 1.1 + 1.2** (results dataset + Elo) — turns the engine from blind to informed for national teams.
3. **Tier 2** (engine covers all markets, no more 0.50).
4. **Tier 1.3** (odds) + **Tier 3** (strategy) — adds the crowd signal and correct probability handling.
5. **Tier 5** (calibration loop) — compounding gains as results settle.
6. **Tier 4** (AI redesign) + **Tier 6** (timing/PATCH) + **Tier 7** (hygiene).

## 6. How we'll measure improvement
- Compute our own **cumulative RBP** from `GET /results` (the API gives per-market Brier; we estimate `crowd_brier` from our RBP sign over time) and track it per market type and per stage.
- Watch the **reliability curve** (predicted vs realized frequency) converge as calibration kicks in.
- Compare **Bot 1 vs Bot 2** RBP to confirm the two strategies are genuinely diversified.

---

**Bottom line:** the system is currently (a) feeding the AI 0.50 for most markets, (b) at risk of submitting whole matches at 50/50 silently, (c) using no odds/Elo/base-rate signal, (d) compressing away real edge, and (e) never learning from results. Fixing those — all with free data — is what turns a near-random bot into one that can consistently beat a crowd of casual humans and clueless LLM bots, which is exactly what RBP rewards.
