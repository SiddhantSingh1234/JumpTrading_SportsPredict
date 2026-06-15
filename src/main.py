import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
import time
from src.database import Database
from src.submitter import SportsPredictAPI
from src.config import Config
from src.collector import DataCollector
from src.news_scraper import NewsScraper
from src.market_classifier import MarketClassifier
from src.engine import SimulationEngine
from src.predictor import Predictor
from src.calibrator import Calibrator
from src.ai_client import AIClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")

class AgenticSystem:
    def __init__(self):
        self.db = Database()
        self.sp_api1 = SportsPredictAPI(Config.BOT1_KEY)
        self.sp_api2 = SportsPredictAPI(Config.BOT2_KEY)
        self.news_scraper = NewsScraper()
        
        # Initialize Google GenAI client
        self.ai_client = AIClient(Config.GEMINI_API_KEY) if Config.GEMINI_API_KEY else None 
        
        self.collector = DataCollector(self.db, self.sp_api1, self.news_scraper, self.ai_client)
        self.classifier = MarketClassifier(self.ai_client)
        self.engine = SimulationEngine()
        self.predictor = Predictor(self.ai_client)
        self.calibrator = Calibrator(self.db, self.sp_api1, self.ai_client)
        
        self.event_id, self.lobby_id = self._init_lobby()

    def _init_lobby(self):
        # Discover event and lobby
        cached_event = self.db.get_state("event_id")
        cached_lobby = self.db.get_state("lobby_id")
        
        if cached_event and cached_lobby:
            return cached_event, cached_lobby
            
        event_id, lobby_id = self.sp_api1.discover()
        if event_id:
            self.db.save_state("event_id", event_id)
            self.db.save_state("lobby_id", lobby_id)
            # Ensure Bot 2 is also joined
            self.sp_api2.discover() 
            
        return event_id, lobby_id

    def collect(self):
        logger.info("Executing phase: EXTENSIVE COLLECT")
        if not self.event_id:
            logger.error("No event ID found. Cannot collect.")
            return
        self.collector.extensive_collect(self.event_id)

    def predict(self):
        logger.info("Executing phase: QUICK REFRESH + PREDICT")
        total_window = Config.PREDICT_WINDOW_MINUTES + Config.PREDICT_WINDOW_BUFFER
        matches = self.db.get_upcoming_matches(within_minutes=total_window)
        
        if not matches:
            logger.info(f"No matches starting within {total_window} minutes. Exiting cleanly.")
            return
            
        for match in matches:
            match_id = match.get("id")
            if self.db.is_predicted_final(match_id):
                logger.info(f"Match {match_id} already predicted. Skipping.")
                continue
                
            self._run_prediction_pipeline(match)

    def calibrate(self):
        logger.info("Executing phase: CALIBRATE")
        self.calibrator.run_full_calibration()

    def _run_prediction_pipeline(self, match):
        match_id = match.get("id")
        logger.info(f"Running full prediction pipeline for match {match_id}")
        
        # 1. Quick Refresh
        self.collector.quick_refresh(match_id)
        
        # 2. Get Markets
        markets = self.sp_api1.get_markets(match_id)
        classified = self.classifier.classify_all(markets, match)
        self.db.save_markets(match_id, classified)
        
        # 3. Simulate
        updated_match = self.db.get_match(match_id)
        home_team_stats = self.db.get_team(updated_match.get("home_team_id"))
        away_team_stats = self.db.get_team(updated_match.get("away_team_id"))
        sim_results = self.engine.simulate_match(updated_match, home_team_stats, away_team_stats, classified)
        self.db.save_simulations(match_id, sim_results)
        
        # 4. Predict
        news = self.db.get_news(match_id)
        structured = self.db.get_structured_news(match_id)
        
        bot1_preds = self.predictor.predict(1, sim_results, news, structured, classified, updated_match)
        # Delay for RPM limit
        time.sleep(12) 
        bot2_preds = self.predictor.predict(2, sim_results, news, structured, classified, updated_match)
        
        # 5. Submit
        r1 = self.sp_api1.submit_batch(bot1_preds)
        r2 = self.sp_api2.submit_batch(bot2_preds)
        
        self.db.save_predictions(match_id, 1, bot1_preds, r1)
        self.db.save_predictions(match_id, 2, bot2_preds, r2)
        
        self.db.mark_predicted(match_id)
        
        self.db.log_schedule({"action": "prediction_pipeline", "match_id": match_id, "status": "success"})
        logger.info(f"Pipeline complete for match {match_id}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/main.py [collect|predict|calibrate]")
        sys.exit(1)
        
    action = sys.argv[1]
    system = AgenticSystem()
    
    if action == "collect":
        system.collect()
    elif action == "predict":
        system.predict()
    elif action == "calibrate":
        system.calibrate()
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)
