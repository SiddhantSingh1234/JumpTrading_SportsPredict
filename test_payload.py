import sys
import os
import requests
import json
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from src.config import Config
from src.submitter import SportsPredictAPI

api = SportsPredictAPI(Config.BOT1_KEY)
event_id, lobby_id = api.discover()
matches = api.get_matches(event_id)
match = matches[0]
markets = api.get_markets(match['id'])

if markets:
    mid = markets[0]['id']
    headers = {"Authorization": f"Bearer {Config.BOT1_KEY}"}
    
    # Test 1: {"predictions": [...]}
    print("Test 1: Dictionary")
    resp1 = requests.post(f"{Config.SPORTSPREDICT_BASE_URL}/predictions/batch", headers=headers, json={"predictions": [{"marketId": mid, "probability": 50}]})
    print(resp1.status_code, resp1.text)
    
    # Test 2: [...]
    print("Test 2: Array")
    resp2 = requests.post(f"{Config.SPORTSPREDICT_BASE_URL}/predictions/batch", headers=headers, json=[{"marketId": mid, "probability": 50}])
    print(resp2.status_code, resp2.text)
