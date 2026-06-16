import sys
import os
import requests
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from src.config import Config
from src.submitter import SportsPredictAPI

api = SportsPredictAPI(Config.BOT1_KEY)
api.discover() # ensures we are joined to the lobby

matches = api.get_matches(Config.SPORTSPREDICT_BASE_URL)
# Actually, let's just get the markets from the db or API
# But wait, api.discover() joins the lobby!
# Let's re-run the payload test now that we are joined to the lobby!

event_id, lobby_id = api.discover()
matches = api.get_matches(event_id)
match = matches[0]
markets = api.get_markets(match['id'])

if markets:
    mid = markets[0]['id']
    headers = {"Authorization": f"Bearer {Config.BOT1_KEY}"}
    
    print("Test 1: marketId")
    resp1 = requests.post(f"{Config.SPORTSPREDICT_BASE_URL}/predictions/batch", headers=headers, json={"predictions": [{"marketId": mid, "probability": 50}]})
    print(resp1.status_code, resp1.text)
    
    print("Test 2: marketid")
    resp2 = requests.post(f"{Config.SPORTSPREDICT_BASE_URL}/predictions/batch", headers=headers, json={"predictions": [{"marketid": mid, "probability": 50}]})
    print(resp2.status_code, resp2.text)
    
    print("Test 3: market_id")
    resp3 = requests.post(f"{Config.SPORTSPREDICT_BASE_URL}/predictions/batch", headers=headers, json={"predictions": [{"market_id": mid, "probability": 50}]})
    print(resp3.status_code, resp3.text)

