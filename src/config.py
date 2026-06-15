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
    
    # Gemini Model Selection
    GEMINI_PREDICT_MODEL = "gemini-3.5-flash"
    GEMINI_SUMMARY_MODEL = "gemini-3.1-flash-lite"
    GEMINI_STATS_MODEL = "gemma-4-31b-it"
    QUERY_BOT_MODEL = os.environ.get("QUERY_BOT_MODEL", "gemini-3.1-flash-lite")
    
    # Competition Constants
    PROBABILITY_MIN = 1
    PROBABILITY_MAX = 99
    PREDICT_WINDOW_MINUTES = int(os.environ.get("PREDICT_WINDOW_MINUTES", "15"))
    PREDICT_WINDOW_BUFFER = int(os.environ.get("PREDICT_WINDOW_BUFFER", "5"))
    
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
