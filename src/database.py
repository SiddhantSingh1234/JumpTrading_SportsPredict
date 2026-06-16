import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
from src.config import Config
import logging

logger = logging.getLogger(__name__)

class Database:
    """Firebase Firestore interface for all persistence."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize Firebase Admin SDK."""
        if not firebase_admin._apps:
            try:
                cred = credentials.Certificate(Config.FIREBASE_CREDENTIALS_PATH)
                firebase_admin.initialize_app(cred)
                logger.info("Firebase initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize Firebase: {e}")
                # For local dev without creds, we might want to fail gracefully
                # but for production it's critical.
                raise
        
        # The firebase_admin firestore.client() wrapper doesn't accept 'database' in all versions.
        # If using the default database, we can just call it without arguments.
        if Config.FIREBASE_DATABASE_NAME == "(default)":
            self.db = firestore.client()
        else:
            # If a custom database name is provided, we must instantiate the underlying GCP client directly.
            from google.cloud import firestore as gcp_firestore
            self.db = gcp_firestore.Client(
                project=cred.project_id, 
                database=Config.FIREBASE_DATABASE_NAME, 
                credentials=cred.get_credential()
            )

    # --- Match Queries ---
    
    def get_upcoming_matches(self, within_minutes=None):
        """Get matches starting soon based on closing_time."""
        # The Jump Trading API doesn't use 'status', it just returns matches with opening/closing times.
        matches = [doc.to_dict() for doc in self.db.collection("matches").stream()]
        
        if within_minutes is not None:
            now = datetime.utcnow()
            result = []
            for match in matches:
                # Trigger based purely on opening_time (when markets open) as requested by user
                time_str = match.get("opening_time")
                if not time_str:
                    continue
                    
                try:
                    kickoff = datetime.fromisoformat(time_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    delta_minutes = (kickoff - now).total_seconds() / 60.0
                    
                    # Include matches starting within the window, or matches that started up to 120 mins ago (live)
                    if 0 <= delta_minutes <= within_minutes:
                        result.append(match)
                except Exception as e:
                    logger.warning(f"Error parsing date for match {match.get('id')}: {e}")
            return result
        return matches

    def get_all_matches(self):
        return [doc.to_dict() for doc in self.db.collection("matches").stream()]

    def get_match(self, match_id):
        doc = self.db.collection("matches").document(str(match_id)).get()
        return doc.to_dict() if doc.exists else None
        
    def save_matches(self, matches):
        """Batch save matches."""
        batch = self.db.batch()
        for match in matches:
            match_id = str(match["id"])
            doc_ref = self.db.collection("matches").document(match_id)
            match["updated_at"] = datetime.utcnow().isoformat()
            batch.set(doc_ref, match, merge=True)
        batch.commit()

    # --- Team & Player Stats ---

    def update_team_stats(self, match_data, stats):
        team_id = str(stats.get("team_id"))
        doc_ref = self.db.collection("teams").document(team_id)
        stats["updated_at"] = datetime.utcnow().isoformat()
        doc_ref.set(stats, merge=True)

    def update_injuries(self, match_data, injuries):
        match_id = str(match_data["id"])
        doc_ref = self.db.collection("matches").document(match_id)
        doc_ref.set({"injuries": injuries, "updated_at": datetime.utcnow().isoformat()}, merge=True)

    def update_lineups(self, match_data, lineups):
        match_id = str(match_data["id"])
        doc_ref = self.db.collection("matches").document(match_id)
        doc_ref.set({"lineups": lineups, "updated_at": datetime.utcnow().isoformat()}, merge=True)

    def update_players(self, team_id, players):
        batch = self.db.batch()
        for player in players:
            player_id = str(player.get("id"))
            doc_ref = self.db.collection("players").document(player_id)
            player["team_id"] = team_id
            player["updated_at"] = datetime.utcnow().isoformat()
            batch.set(doc_ref, player, merge=True)
        batch.commit()
        
    def get_team(self, team_id):
        if not team_id: return None
        doc = self.db.collection("teams").document(str(team_id)).get()
        return doc.to_dict() if doc.exists else None
        
    def get_team_by_name_or_code(self, query_str):
        if not query_str: return None
        
        # Try exact match on code
        query = self.db.collection("teams").where("code", "==", query_str).limit(1)
        docs = list(query.stream())
        if docs:
            return docs[0].to_dict()
            
        # Try exact match on name
        query = self.db.collection("teams").where("name", "==", query_str).limit(1)
        docs = list(query.stream())
        if docs:
            return docs[0].to_dict()
            
        return None
        
    def get_player(self, player_id):
        doc = self.db.collection("players").document(str(player_id)).get()
        return doc.to_dict() if doc.exists else None

    # --- Historical Matches ---
    
    def save_historical_matches(self, team_id, matches):
        batch = self.db.batch()
        for match in matches:
            fixture_id = str(match.get("fixture", {}).get("id"))
            if not fixture_id: continue
            doc_ref = self.db.collection("historical_matches").document(fixture_id)
            match["associated_team_id"] = team_id
            match["updated_at"] = datetime.utcnow().isoformat()
            batch.set(doc_ref, match, merge=True)
        batch.commit()
        
    def get_recent_historical_matches_safe(self, team_id, limit=2):
        """Safely fetch and sort matches without requiring a composite Firestore index."""
        query = self.db.collection("historical_matches").where("associated_team_id", "==", str(team_id))
        matches = [doc.to_dict() for doc in query.stream()]
        matches.sort(key=lambda x: x.get("fixture", {}).get("date", ""), reverse=True)
        return matches[:limit]

    # --- Markets & Classifications ---

    def save_markets(self, match_id, markets):
        batch = self.db.batch()
        for market in markets:
            market_id = str(market["id"])
            doc_ref = self.db.collection("markets").document(market_id)
            market["match_id"] = match_id
            market["updated_at"] = datetime.utcnow().isoformat()
            batch.set(doc_ref, market, merge=True)
        batch.commit()

    def get_markets(self, match_id):
        query = self.db.collection("markets").where("match_id", "==", match_id)
        return [doc.to_dict() for doc in query.stream()]

    # --- News & Context ---

    def save_news(self, match_id, briefing, headlines, structured_stats=None):
        doc_ref = self.db.collection("news").document(str(match_id))
        data = {
            "briefing": briefing,
            "headlines": headlines,
            "updated_at": datetime.utcnow().isoformat()
        }
        if structured_stats:
            data["structured_stats"] = structured_stats
        doc_ref.set(data, merge=True)

    def get_news(self, match_id):
        doc = self.db.collection("news").document(str(match_id)).get()
        return doc.to_dict().get("briefing", "") if doc.exists else ""
        
    def get_structured_news(self, match_id):
        doc = self.db.collection("news").document(str(match_id)).get()
        return doc.to_dict().get("structured_stats", {}) if doc.exists else {}

    # --- Simulations ---

    def save_simulations(self, match_id, sim_results):
        doc_ref = self.db.collection("simulations").document(str(match_id))
        doc_ref.set({
            "results": sim_results,
            "updated_at": datetime.utcnow().isoformat()
        }, merge=True)

    def get_simulations(self, match_id):
        doc = self.db.collection("simulations").document(str(match_id)).get()
        return doc.to_dict().get("results", {}) if doc.exists else {}

    # --- Predictions ---

    def is_predicted_final(self, match_id):
        doc = self.db.collection("matches").document(str(match_id)).get()
        return doc.to_dict().get("predicted_final", False) if doc.exists else False

    def mark_predicted(self, match_id):
        self.db.collection("matches").document(str(match_id)).set({
            "predicted_final": True,
            "updated_at": datetime.utcnow().isoformat()
        }, merge=True)

    def save_predictions_local_cache(self, match_id, bot1_preds, bot2_preds):
        """Save predictions without SportsPredict IDs (for query bot)."""
        self._save_preds_to_db(match_id, 1, bot1_preds)
        self._save_preds_to_db(match_id, 2, bot2_preds)

    def save_predictions(self, match_id, bot_number, preds, sp_response=None):
        """Save submitted predictions."""
        # Inject sp_prediction_id if provided from API response
        if sp_response:
            # Match up local preds with SP response ids.
            # Assuming sp_response has a way to map them.
            pass
        self._save_preds_to_db(match_id, bot_number, preds)

    def _save_preds_to_db(self, match_id, bot_number, preds):
        batch = self.db.batch()
        for p in preds:
            # Document ID = market_id_bot_number
            doc_id = f"{p['market_id']}_{bot_number}"
            doc_ref = self.db.collection("predictions").document(doc_id)
            p["match_id"] = match_id
            p["bot_number"] = bot_number
            p["updated_at"] = datetime.utcnow().isoformat()
            batch.set(doc_ref, p, merge=True)
        batch.commit()

    def get_existing_predictions(self, match_id):
        query = self.db.collection("predictions").where("match_id", "==", match_id)
        preds = {}
        for doc in query.stream():
            data = doc.to_dict()
            preds[(data["market_id"], data["bot_number"])] = data
        return preds
        
    def get_predictions(self, match_id=None, bot=None):
        query = self.db.collection("predictions")
        if match_id:
            query = query.where("match_id", "==", match_id)
        if bot:
            query = query.where("bot_number", "==", bot)
        return [doc.to_dict() for doc in query.stream()]

    # --- Schedule & Logs ---

    def log_schedule(self, log_data):
        log_data["executed_at"] = datetime.utcnow().isoformat()
        self.db.collection("schedule_log").add(log_data)

    def get_schedule_logs(self, limit=50):
        query = self.db.collection("schedule_log").order_by("executed_at", direction=firestore.Query.DESCENDING).limit(limit)
        return [doc.to_dict() for doc in query.stream()]
        
    # --- State / Config ---
    
    def is_initialized(self):
        doc = self.db.collection("state").document("config").get()
        return doc.exists and doc.to_dict().get("initialized", False)
        
    def save_state(self, key, value):
        self.db.collection("state").document("config").set({
            key: value,
            "updated_at": datetime.utcnow().isoformat()
        }, merge=True)
        
    def get_state(self, key):
        doc = self.db.collection("state").document("config").get()
        return doc.to_dict().get(key) if doc.exists else None

    # --- Usage tracking ---
    
    def count_predictions_today(self):
        """Count how many predictions were submitted today to monitor quotas."""
        today_iso = datetime.utcnow().date().isoformat()
        # Firestore inequality queries require an index, but we can do a simple prefix or just fetch recently updated.
        # For simplicity without requiring custom indexes immediately, we fetch all and filter,
        # or rely on the updated_at field string comparison.
        query = self.db.collection("predictions").where("updated_at", ">=", today_iso)
        count = sum(1 for _ in query.stream())
        return count
