import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # API Keys
    BOT1_KEY = os.environ.get("SPORTSPREDICT_BOT1_KEY", "mock_key_1")
    BOT2_KEY = os.environ.get("SPORTSPREDICT_BOT2_KEY", "mock_key_2")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "")
    FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY", "")
    
    # Firebase
    FIREBASE_CREDENTIALS_PATH = os.environ.get("FIREBASE_CREDENTIALS_PATH", "firebase-credentials.json")
    FIREBASE_DATABASE_NAME = os.environ.get("FIREBASE_DATABASE_NAME", "(default)")
    
    # SportsPredict API Configuration
    SPORTSPREDICT_BASE_URL = "https://api.sportspredict.com/api/v1"
    
    # API-Football Configuration
    API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
    
    # Football-Data.org Configuration
    FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"
    
    # Gemini Model Selection (all verified present on this key's model list)
    GEMINI_PREDICT_MODEL = "gemini-3.5-flash"
    GEMINI_SUMMARY_MODEL = "gemini-3.1-flash-lite"
    GEMINI_STATS_MODEL = "gemini-3.1-flash-lite"
    QUERY_BOT_MODEL = os.environ.get("QUERY_BOT_MODEL", "gemini-3.1-flash-lite")

    # Fallback chain for the prediction model, in priority order. When the
    # 20/day premium budget is exhausted we cascade to flash-lite (500/day) so
    # predictions keep using AI; only if ALL are exhausted do we drop to the
    # (still-informed) quant model probabilities.
    GEMINI_PREDICT_FALLBACKS = ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-3.1-flash-lite"]

    # Google Search GROUNDING uses a separate, larger quota pool (1500/day) on
    # the gemini-2.5 models. Used only to fetch confirmed lineups/injuries at
    # predict time; tracked under its own usage key so it never competes with
    # the 20/day prediction budget above.
    GEMINI_GROUNDING_MODEL = os.environ.get("GEMINI_GROUNDING_MODEL", "gemini-2.5-flash")
    GROUNDING_USAGE_KEY = "grounding"

    # Actual free-tier per-model DAILY request caps (RPD). Tracked in Firestore
    # across the separate GitHub Actions runs so we never exceed them.
    GEMINI_DAILY_CAPS = {
        "gemini-3.5-flash": int(os.environ.get("RPD_PREDICT", "20")),
        "gemini-3-flash-preview": int(os.environ.get("RPD_PREVIEW", "20")),
        "gemini-2.5-flash": int(os.environ.get("RPD_FLASH", "20")),
        "gemini-3.1-flash-lite": int(os.environ.get("RPD_LITE", "500")),
        "gemma-4-31b-it": int(os.environ.get("RPD_GEMMA", "1500")),
        # Separate grounding pool (Google Search grounded calls only).
        GROUNDING_USAGE_KEY: int(os.environ.get("RPD_GROUNDING", "1500")),
    }

    # --- The Odds API (free tier: 500 req/month) — optional, set ODDS_API_KEY ---
    ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
    ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
    ODDS_API_SPORT = os.environ.get("ODDS_API_SPORT", "soccer_fifa_world_cup")
    ODDS_MONTHLY_CAP = int(os.environ.get("ODDS_MONTHLY_CAP", "480"))  # leave headroom under 500

    # --- Reddit (free script app) — optional, set REDDIT_CLIENT_ID/SECRET ---
    REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
    REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "probabilitycup-bot/1.0")
    REDDIT_SUBREDDITS = ["SoccerBetting", "soccer", "worldcup", "football"]
    
    # Competition Constants
    PROBABILITY_MIN = 1
    PROBABILITY_MAX = 99
    PREDICT_WINDOW_MINUTES = int(os.environ.get("PREDICT_WINDOW_MINUTES", "30"))
    PREDICT_WINDOW_BUFFER = int(os.environ.get("PREDICT_WINDOW_BUFFER", "30"))

    # Competition stance for crowd-relative variance (Tier 3.3). Set from the
    # leaderboard you see: "climb" (trailing -> take more variance on strong
    # edges), "defend" (leading -> hug consensus), or "neutral" (default).
    COMPETITION_STANCE = os.environ.get("COMPETITION_STANCE", "neutral").lower()

    # Only calibrate on settled results created on/after this ISO date, so the
    # old (bad) bot's predictions don't pollute the new pipeline's calibration.
    # Set this to the day you deploy the new system (e.g. "2026-06-18"). Empty =
    # use all results.
    CALIBRATION_SINCE_DATE = os.environ.get("CALIBRATION_SINCE_DATE", "")

    # Stage inference for stage weighting (group 1x, knockout 2x, final 3x).
    # The match API exposes no stage field, so we infer it from the kickoff date
    # (opening_time). WC 2026 approximate cutoffs; override via env if needed.
    GROUP_STAGE_END_DATE = os.environ.get("GROUP_STAGE_END_DATE", "2026-06-27")
    FINAL_DATE = os.environ.get("FINAL_DATE", "2026-07-19")

    @classmethod
    def infer_stage(cls, opening_time):
        """'group' | 'knockout' | 'final' from a kickoff timestamp (opening_time)."""
        if not opening_time or len(str(opening_time)) < 10:
            return "group"
        date = str(opening_time)[:10]  # YYYY-MM-DD; ISO string compares correctly
        if date >= cls.FINAL_DATE:
            return "final"
        if date > cls.GROUP_STAGE_END_DATE:
            return "knockout"
        return "group"
    
    # Paths
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    TEAMS_DIR = os.path.join(DATA_DIR, "teams")
    PLAYERS_DIR = os.path.join(DATA_DIR, "players")
    HISTORICAL_DIR = os.path.join(DATA_DIR, "historical")

    @classmethod
    def setup_dirs(cls):
        """Ensure all local data directories exist."""
        os.makedirs(cls.TEAMS_DIR, exist_ok=True)
        os.makedirs(cls.PLAYERS_DIR, exist_ok=True)
        os.makedirs(cls.HISTORICAL_DIR, exist_ok=True)

# Run setup on import
Config.setup_dirs()
