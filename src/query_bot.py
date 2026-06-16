import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional
import uvicorn
import logging
from src.main import AgenticSystem
from src.config import Config

logger = logging.getLogger("query_bot")

# Global reference to our system
system = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global system
    logger.info("Initializing Agentic System (Query Bot)...")
    system = AgenticSystem()
    yield
    logger.info("Shutting down Query Bot...")

app = FastAPI(title="Probability Cup Query Bot", lifespan=lifespan)

class PredictRequest(BaseModel):
    match_id: Optional[str] = None
    match_name: Optional[str] = None

@app.get("/api/status")
async def get_status():
    """System health and queue status."""
    return {
        "status": "online",
        "event_id": system.event_id,
        "upcoming_matches": [
            {"id": m.get("id"), "name": m.get("name"), "closing_time": m.get("closing_time")}
            for m in system.db.get_upcoming_matches(within_minutes=72*60)
        ]
    }

@app.get("/api/matches")
async def get_matches():
    """List all matches in DB with their IDs."""
    matches = system.db.get_all_matches()
    return [
        {"id": m.get("id"), "name": m.get("name"), "closing_time": m.get("closing_time"), "opening_time": m.get("opening_time")}
        for m in matches
    ]

@app.get("/api/dashboard")
async def get_dashboard():
    """Calibration and performance dashboard."""
    return system.calibrator.get_dashboard_data()

@app.post("/api/predict")
async def predict_match(req: PredictRequest):
    """
    Generate predictions for a match WITHOUT submitting them.
    Provide either match_id or match_name.
    Returns Bot 1 and Bot 2 predictions for all markets.
    """
    target_match = None

    if req.match_id:
        target_match = system.db.get_match(req.match_id)
    elif req.match_name:
        matches = system.db.get_all_matches()
        query = req.match_name.lower()
        for match in matches:
            name = match.get("name", "").lower()
            home = match.get("home_team_name", "").lower()
            away = match.get("away_team_name", "").lower()
            if query in name or query in home or query in away or home in query or away in query:
                target_match = match
                break

    if not target_match:
        raise HTTPException(status_code=404, detail="Match not found. Use /api/matches to see available matches.")

    match_id = target_match.get("id")
    match_name = target_match.get("name", "Unknown")
    logger.info(f"Generating predictions for {match_name} ({match_id})")

    # 1. Get Markets from SportsPredict API
    markets = system.sp_api1.get_markets(match_id)
    if not markets:
        # Try from DB cache
        markets = system.db.get_markets(match_id)
    if not markets:
        raise HTTPException(status_code=404, detail=f"No markets found for match {match_name}")

    classified = system.classifier.classify_all(markets, target_match)
    system.db.save_markets(match_id, classified)

    # 2. Simulate
    updated_match = system.db.get_match(match_id)
    home_team_stats = system.db.get_team(updated_match.get("home_team_id"))
    away_team_stats = system.db.get_team(updated_match.get("away_team_id"))
    sim_results = system.engine.simulate_match(updated_match, home_team_stats, away_team_stats, classified)
    system.db.save_simulations(match_id, sim_results)

    # 3. Generate Predictions (DO NOT submit)
    news = system.db.get_news(match_id)
    structured = system.db.get_structured_news(match_id)

    bot1_preds = system.predictor.predict(1, sim_results, news, structured, classified, updated_match)
    time.sleep(8)  # Respect Gemini rate limits
    bot2_preds = system.predictor.predict(2, sim_results, news, structured, classified, updated_match)

    # Save locally but DO NOT submit to SportsPredict
    system.db.save_predictions_local_cache(match_id, bot1_preds, bot2_preds)

    # 4. Format response
    return {
        "match": match_name,
        "match_id": match_id,
        "simulation_summary": sim_results.get("mc_summary", {}),
        "bot1_predictions": [
            {"market_id": p.get("market_id"), "probability": p.get("probability"), "reasoning": p.get("reasoning", "")}
            for p in bot1_preds
        ],
        "bot2_predictions": [
            {"market_id": p.get("market_id"), "probability": p.get("probability"), "reasoning": p.get("reasoning", "")}
            for p in bot2_preds
        ]
    }

if __name__ == "__main__":
    uvicorn.run("src.query_bot:app", host="0.0.0.0", port=8000, reload=True)
