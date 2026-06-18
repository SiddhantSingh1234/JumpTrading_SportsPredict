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
        
        # Initialize Google GenAI client (db enables cross-run daily quota tracking)
        self.ai_client = AIClient(Config.GEMINI_API_KEY, self.db) if Config.GEMINI_API_KEY else None
        
        self.collector = DataCollector(self.db, self.sp_api1, self.news_scraper, self.ai_client)
        self.classifier = MarketClassifier(self.ai_client)
        self.engine = SimulationEngine()
        self.predictor = Predictor(self.ai_client)
        self.calibrator = Calibrator(self.db, {1: self.sp_api1, 2: self.sp_api2}, self.ai_client)
        
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
        match_name = match.get("name", "Unknown Match")
        logger.info(f"Running full prediction pipeline for {match_name} ({match_id})")
        
        # 1. Quick Refresh
        self.collector.quick_refresh(match_id)
        
        # 2. Get Markets
        markets = self.sp_api1.get_markets(match_id)
        if not markets:
            logger.error(f"No markets returned from SportsPredict API for {match_name}. Skipping.")
            return
        classified = self.classifier.classify_all(markets, match)
        self.db.save_markets(match_id, classified)
        
        # 3. Simulate
        updated_match = self.db.get_match(match_id)
        # Ensure stage is set (drives stage weighting 1x/2x/3x in the prompts).
        if updated_match and not updated_match.get("stage"):
            updated_match["stage"] = Config.infer_stage(updated_match.get("opening_time"))
        home_team_stats = self.db.get_team(updated_match.get("home_team_id"))
        away_team_stats = self.db.get_team(updated_match.get("away_team_id"))
        sim_results = self.engine.simulate_match(updated_match, home_team_stats, away_team_stats, classified)
        self.db.save_simulations(match_id, sim_results)
        
        # 4. Predict
        news = self.db.get_news(match_id)
        structured = self.db.get_structured_news(match_id)
        crowd_sentiment = self.db.get_sentiment(match_id)
        # Per-bot learned recalibration maps (Bot 1 and Bot 2 calibrate separately).
        calib1 = self.db.get_state("calibration_1")
        calib2 = self.db.get_state("calibration_2")

        logger.info(f"Generating Bot 1 predictions for {match_name}...")
        bot1_preds = self.predictor.predict(1, sim_results, news, structured, classified, updated_match, crowd_sentiment, calib1)
        time.sleep(8)  # Allow rate limiter in ai_client to handle precise timing
        logger.info(f"Generating Bot 2 predictions for {match_name}...")
        bot2_preds = self.predictor.predict(2, sim_results, news, structured, classified, updated_match, crowd_sentiment, calib2)
        
        # 5. Submit to Jump Trading
        logger.info(f"Submitting Bot 1 predictions for {match_name}...")
        r1 = self.sp_api1.submit_batch(bot1_preds, self.lobby_id)
        logger.info(f"Submitting Bot 2 predictions for {match_name}...")
        r2 = self.sp_api2.submit_batch(bot2_preds, self.lobby_id)
        
        self.db.save_predictions(match_id, 1, bot1_preds, r1)
        self.db.save_predictions(match_id, 2, bot2_preds, r2)
        
        self.db.mark_predicted(match_id)
        
        # 6. Write prediction report to file
        self._write_prediction_report(match_name, match_id, classified, sim_results, bot1_preds, bot2_preds)
        
        self.db.log_schedule({"action": "prediction_pipeline", "match_id": match_id, "status": "success"})
        logger.info(f"Pipeline complete for {match_name} ({match_id})")

    def _write_prediction_report(self, match_name, match_id, markets, sim_results, bot1_preds, bot2_preds):
        """Write a readable prediction report to a markdown file."""
        import os
        from datetime import datetime
        
        report_dir = os.path.join(Config.DATA_DIR, "predictions")
        os.makedirs(report_dir, exist_ok=True)
        
        # Create filename from match name and timestamp
        safe_name = match_name.replace(" ", "_").replace("/", "-")
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(report_dir, f"{safe_name}_{timestamp}.md")
        
        # Build a lookup from market_id to question text
        market_questions = {}
        for m in markets:
            mid = str(m.get("id", ""))
            text = m.get("question_text") or m.get("question") or m.get("text", "Unknown question")
            market_questions[mid] = text
        
        # Build prediction lookup
        b1_lookup = {str(p.get("market_id")): p.get("probability", "?") for p in bot1_preds}
        b2_lookup = {str(p.get("market_id")): p.get("probability", "?") for p in bot2_preds}
        
        mc = sim_results.get("mc_summary", {})
        
        lines = [
            f"# Prediction Report: {match_name}",
            f"**Match ID:** {match_id}",
            f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "## Simulation Summary",
            f"- Home Win: {mc.get('home_win', 0):.1%}",
            f"- Draw: {mc.get('draw', 0):.1%}",
            f"- Away Win: {mc.get('away_win', 0):.1%}",
            f"- Avg Total Goals: {mc.get('avg_goals', 0):.2f}",
            "",
            "## Predictions",
            "",
            "| # | Market Question | Bot 1 (Calibrated) | Bot 2 (Edge Hunter) |",
            "|---|----------------|--------------------|--------------------|" 
        ]
        
        for i, mid in enumerate(market_questions, 1):
            question = market_questions[mid]
            b1 = b1_lookup.get(mid, "—")
            b2 = b2_lookup.get(mid, "—")
            lines.append(f"| {i} | {question} | **{b1}%** | **{b2}%** |")
        
        lines.append("")
        lines.append("---")
        lines.append("*Submitted to Jump Trading SportsPredict API*")
        
        report_content = "\n".join(lines)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report_content)
        
        logger.info(f"Prediction report saved to: {filepath}")
        
        # Also print to console for GitHub Actions logs
        print("\n" + "=" * 70)
        print(f"  PREDICTION REPORT: {match_name}")
        print("=" * 70)
        for i, mid in enumerate(market_questions, 1):
            question = market_questions[mid]
            b1 = b1_lookup.get(mid, "—")
            b2 = b2_lookup.get(mid, "—")
            print(f"  Q{i}: {question}")
            print(f"       Bot 1: {b1}%  |  Bot 2: {b2}%")
        print("=" * 70 + "\n")


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
