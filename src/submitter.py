import requests
import time
import logging
from src.config import Config

logger = logging.getLogger(__name__)

def retry_api(func):
    """Decorator to retry SportsPredict API requests on 429 or 5xx."""
    def wrapper(*args, **kwargs):
        retries = 3
        backoffs = [5, 15, 60]
        for i in range(retries):
            try:
                response = func(*args, **kwargs)
                if response.status_code == 429:
                    wait = int(response.headers.get("Retry-After", backoffs[i]))
                    logger.warning(f"SportsPredict Rate limited (429). Waiting {wait}s.")
                    time.sleep(wait)
                    continue
                if response.status_code >= 500:
                    logger.warning(f"SportsPredict Server Error {response.status_code}. Retrying...")
                    time.sleep(backoffs[i])
                    continue
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                logger.error(f"SportsPredict Request failed: {e}")
                if i == retries - 1:
                    raise
                time.sleep(backoffs[i])
    return wrapper

class SportsPredictAPI:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = Config.SPORTSPREDICT_BASE_URL
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
        
    @retry_api
    def _get(self, endpoint):
        return requests.get(f"{self.base_url}{endpoint}", headers=self.headers)

    @retry_api
    def _post(self, endpoint, data):
        return requests.post(f"{self.base_url}{endpoint}", headers=self.headers, json=data)

    @retry_api
    def _patch(self, endpoint, data):
        return requests.patch(f"{self.base_url}{endpoint}", headers=self.headers, json=data)

    def discover(self):
        """Find the event and lobby for Probability Cup."""
        events = self._get("/events")
        # Find probability cup
        prob_cup = next((e for e in events if e.get("type") == "probability"), None)
        if not prob_cup:
            # Fallback for dev if types differ
            prob_cup = events[0] if events else {}
            
        event_id = prob_cup.get("id")
        
        if event_id:
            lobbies = self._get(f"/lobbies?eventid={event_id}")
            if lobbies:
                lobby = lobbies[0]
                if not lobby.get("joined"):
                    self._post(f"/lobbies/{lobby['id']}/join", {})
                return event_id, lobby["id"]
        return None, None

    def get_matches(self, event_id):
        return self._get(f"/matches?eventid={event_id}")
        
    def get_markets(self, match_id):
        return self._get(f"/markets?matchid={match_id}")
        
    def get_results(self):
        return self._get("/results")

    def submit_batch(self, predictions):
        """Submit up to 50 predictions at once."""
        # The API accepts 1-99 for probability
        payload = {"predictions": []}
        for p in predictions:
            payload["predictions"].append({
                "marketId": p["market_id"],
                "probability": p["probability"]
            })
        logger.info(f"Submitting batch of {len(predictions)} predictions.")
        return self._post("/predictions/batch", payload)
        
    def update_prediction(self, prediction_id, new_probability):
        """PATCH a single prediction."""
        logger.info(f"PATCHing prediction {prediction_id} to {new_probability}.")
        return self._patch(f"/predictions/{prediction_id}", {"probability": new_probability})
