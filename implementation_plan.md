# Jump Trading Probability Cup — Implementation Plan v6 (Final)

100% free. Fully automated. Serverless via GitHub Actions.

---

## Background

**Competition**: Jump Trading Probability Cup (FIFA World Cup 2026, 104 matches, ~10 binary markets each).  
**Prediction range**: Integer **1–99**. **Scoring**: $\text{RBP} = (\text{crowd\_brier} - \text{user\_brier}) \times 100$.  
**Stage weights**: Group 1×, Knockout 2×, Final 3×. **2 bots** per account.

---

## Core Design Principle: Two-Phase Data Collection

```
═══════════════════════════════════════════════════════════════════════
  EXTENSIVE COLLECTION (every 6 hours, GitHub Actions)
  Purpose: Keep our knowledge base fresh at all times
═══════════════════════════════════════════════════════════════════════
  • Scrape ALL RSS feeds (Google News, BBC, ESPN) for upcoming matches
  • Fetch team stats, standings, fixtures from API-Football + football-data.org
  • Summarize news per match via Gemini 3.1 Flash Lite
  • Extract structured stats (injuries, lineups) via Gemma 4 31B
  • Update team/player rolling averages in database
  • Update match schedule from SportsPredict API
  • NO simulations. NO predictions. Just data gathering.

═══════════════════════════════════════════════════════════════════════
  QUICK REFRESH + PREDICT (T-45min before match OR on query bot request)
  Purpose: Get latest-possible data, then simulate and predict
═══════════════════════════════════════════════════════════════════════
  • Quick re-check: lineups, injuries, last-minute news (fast, targeted)
  • Update news briefing if anything changed
  • Run FULL simulations (Poisson + NegBinom + 10K Monte Carlo)
  • Generate predictions via Gemini 3.5 Flash (Bot 1 + Bot 2)
  • Submit/PATCH predictions to SportsPredict API
```

---

## Architecture: GitHub Actions + Firebase Firestore

We use **GitHub Actions** for scheduling and compute, and **Firebase Firestore** for database persistence. This setup requires **no credit card** and is completely free.

### GitHub Actions Workflows (`.github/workflows/`)

GitHub Actions rounds up **every job run to the nearest minute** for billing purposes on private repositories. Public repositories have unlimited free minutes. To guarantee we stay under the 2,000 minutes/month limit on a **private repository**, we use the following schedules:

1. **`collect.yml`** (`schedule: "0 */6 * * *"`): Runs the extensive collection every 6 hours.
2. **`predict.yml`** (`schedule: "*/30 * * * *"`): Runs every 30 minutes. It checks Firestore for any match starting in the next 45 minutes. (Since lineups are typically announced 60 mins before kickoff, a T-45m check perfectly captures the confirmed lineups). If found, it runs the Quick Refresh + Predict cycle. If not, it exits immediately.
3. **`calibrate.yml`** (`schedule: "0 0 * * *"`): Runs daily at midnight UTC. Fetches settled results and runs calibration analysis.
4. **`manual.yml`** (`workflow_dispatch`): Allows manual triggering of any stage.

### GitHub Actions Minutes Budget Calculation

*GitHub rounds up each run to the nearest minute. Below is the maximum usage assuming a 30-day month and a private repository.*

| Workflow | Frequency | Monthly Runs | Billed Mins / Run | Monthly Total |
|---|---|---|---|---|
| `predict.yml` (no match) | Every 30 mins | ~1,336 runs | 1 min (rounded up) | **1,336 min** |
| `predict.yml` (match day) | 104 matches/mo | 104 runs | 2 min (pipeline) | **208 min** |
| `collect.yml` | Every 6 hours | 120 runs | 2 min (pipeline) | **240 min** |
| `calibrate.yml` | Daily | 30 runs | 1 min | **30 min** |
| **Total Usage** | | | | **~1,814 / 2,000 min** ✅ |

**Conclusion:** We are safely under the 2,000-minute free limit, even with rounding. (If you make the repository public, usage is completely unlimited).

### Database: Firebase Firestore

Firestore's Spark plan is free forever (no credit card).
- Free limit: 50K reads/day, 20K writes/day, 1 GiB storage.
- Our usage: ~2,000 reads/day, ~500 writes/day.
- Both GitHub Actions and your local Query Bot will connect to this remote database using a Firebase service account key.

---

## Gemini Model Allocation

| Role | Model | RPD | RPM | Calls/Day |
|---|---|:---:|:---:|:---:|
| Bot 1 & 2 Predictions (T-45min) | **Gemini 3.5 Flash** | 20 | 5 | ≤8 (1 run × 2 bots × 4 matches) |
| News Summary, Market Classify, Query Bot | **Gemini 3.1 Flash Lite** | 500 | 15 | ≤40 |
| Stats Extraction, Calibration Analysis | **Gemma 4 31B** | 1,500 | 15 | ≤20 |

---

## Local Query Bot

The Query Bot is a local FastAPI server (`python src/query_bot.py`) that you run on your own PC when you want to interact with the system.

**Key Features:**
- Connects to the **same remote Firestore database** as the GitHub Actions.
- When you ask a question about a match via the `/api/ask` endpoint, the Query Bot will automatically **trigger a Quick Refresh**, **run fresh simulations**, and **generate new predictions**, storing the results in Firestore before answering your question using the freshest data.
- Does not need to be running 24/7. Start it only when you want to view dashboards or ask questions.

---

## Proposed Changes

### Component 1: Setup & GitHub Actions

#### [NEW] [.github/workflows/collect.yml](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/.github/workflows/collect.yml)
#### [NEW] [.github/workflows/predict.yml](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/.github/workflows/predict.yml)
#### [NEW] [.github/workflows/calibrate.yml](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/.github/workflows/calibrate.yml)
#### [NEW] [.github/workflows/manual.yml](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/.github/workflows/manual.yml)
#### [NEW] [requirements.txt](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/requirements.txt)
```text
requests
scipy
numpy
google-genai
firebase-admin
beautifulsoup4
feedparser
python-dotenv
fastapi
uvicorn
```

### Component 2: Persistence (Firebase Firestore)

#### [NEW] [src/database.py](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/src/database.py)
Uses `firebase-admin` to connect to Firestore. Stores all state securely in the cloud.

### Component 3: Data Collector (Two Phases)

#### [NEW] [src/collector.py](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/src/collector.py)
- `extensive_collect()`: Run by `collect.yml`.
- `quick_refresh()`: Run by `predict.yml` and Local Query Bot.

### Component 4: News Scraper

#### [NEW] [src/news_scraper.py](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/src/news_scraper.py)
Two modes matching the two-phase design: `scrape_all_feeds()` and `quick_scan()`.

### Component 5: Market Classifier

#### [NEW] [src/market_classifier.py](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/src/market_classifier.py)
Regex-first, Gemini 3.1 Flash Lite fallback.

### Component 6: Simulation Engine

#### [NEW] [src/engine.py](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/src/engine.py)
Poisson + Negative Binomial + 10K Monte Carlo.

### Component 7: AI Predictor

#### [NEW] [src/predictor.py](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/src/predictor.py)
Bot 1 (Calibrated Baseline) + Bot 2 (Edge Hunter) using Gemini 3.5 Flash.

### Component 8: Submitter

#### [NEW] [src/submitter.py](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/src/submitter.py)
SportsPredict API client with retry logic, batch submit, PATCH updates.

### Component 9: Calibrator

#### [NEW] [src/calibrator.py](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/src/calibrator.py)
Post-match stats update + calibration analysis via Gemma 4 31B.

### Component 10: Local Query Bot

#### [NEW] [src/query_bot.py](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/src/query_bot.py)
FastAPI application for local use. Includes logic to perform quick refresh and re-run simulations on query.

```python
@app.post("/api/ask")
async def ask_question(body: dict):
    """Natural language questions about predictions.
    Triggers quick refresh + simulation + prediction if match is upcoming."""
    question = body["question"]
    match_id = parse_match_from_question(question)
    
    if match_id:
        # 1. Quick refresh (latest news + injuries)
        collector.quick_refresh(match_id)
        
        # 2. Re-run simulations
        match_data = db.get_match(match_id)
        classified = db.get_markets(match_id)
        sim_results = engine.simulate_match(match_data, classified)
        db.save_simulations(match_id, sim_results)
        
        # 3. Generate predictions (Bot 1 + Bot 2)
        news = db.get_news(match_id)
        structured = db.get_structured_news(match_id)
        bot1_preds = predictor.predict(1, sim_results, news, structured, classified, match_data)
        time.sleep(12) # Respect RPM
        bot2_preds = predictor.predict(2, sim_results, news, structured, classified, match_data)
        
        # Note: Do not submit to SportsPredict here, rely on predict.yml for official submission
        db.save_predictions_local_cache(match_id, bot1_preds, bot2_preds)

    # Generate answer via Gemini 3.1 Flash Lite
    context = build_query_context(match_id, question)
    answer = ai.answer_query(question, context)
    
    return {"answer": answer, "match_id": match_id}
```

### Component 11: Orchestrator (Action Runner)

#### [NEW] [src/main.py](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/src/main.py)
CLI entry point for GitHub Actions.
```bash
python src/main.py collect
python src/main.py predict
python src/main.py calibrate
```

### Component 12: Bootstrap

#### [NEW] [src/bootstrap.py](file:///e:/JumpTrading_SportsPredict_ProbabilityCompetition/src/bootstrap.py)
One-time setup script to populate Firestore.

---

## File Structure (Final)

```text
e:\JumpTrading_SportsPredict_ProbabilityCompetition\
├── .github/
│   └── workflows/
│       ├── collect.yml              # Runs src/main.py collect (every 6h)
│       ├── predict.yml              # Runs src/main.py predict (every 30m)
│       ├── calibrate.yml            # Runs src/main.py calibrate (daily)
│       └── manual.yml               # Manual trigger from UI
├── .env.example                     # Env var template
├── .gitignore                       # Git ignore file
├── requirements.txt                 # Python dependencies
│
├── src/
│   ├── __init__.py
│   ├── config.py                    # Configuration & constants
│   ├── database.py                  # Firebase Firestore persistence layer
│   ├── collector.py                 # Two-phase data collection
│   ├── news_scraper.py              # RSS scraping
│   ├── market_classifier.py         # Question type classification
│   ├── engine.py                    # Poisson / NegBinom / Monte Carlo
│   ├── predictor.py                 # Gemini AI predictions
│   ├── submitter.py                 # SportsPredict API client
│   ├── calibrator.py                # Post-match calibration
│   ├── bootstrap.py                 # One-time data population
│   ├── query_bot.py                 # Local FastAPI server
│   └── main.py                      # CLI entry point for Actions
│
└── data/                            # Local cache/historical data
```

---

## Verification Plan
1. Run `src/bootstrap.py` locally to populate Firebase Firestore.
2. Push code to GitHub repository and configure Secrets (API Keys, Firebase credentials).
3. Monitor GitHub Actions tab to ensure `predict.yml` runs successfully without errors.
4. Run `src/query_bot.py` locally and verify the dashboard pulls data from Firestore correctly.
