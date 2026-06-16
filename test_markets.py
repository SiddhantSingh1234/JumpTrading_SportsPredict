import sys
import os
import json
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from src.config import Config
from src.submitter import SportsPredictAPI

api = SportsPredictAPI(Config.BOT1_KEY)
event_id, lobby_id = api.discover()
matches = api.get_matches(event_id)
match = matches[0]
markets = api.get_markets(match['id'])

print("Type of markets:", type(markets))
print("Markets response:")
print(json.dumps(markets, indent=2))
