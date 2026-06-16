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
mid = match['id']

print("Testing ?matchid=")
res1 = api._get(f"/markets?matchid={mid}")
print(f"Returned {len(res1)} markets")

print("Testing ?match_id=")
res2 = api._get(f"/markets?match_id={mid}")
print(f"Returned {len(res2)} markets")

print("Testing ?matchId=")
res3 = api._get(f"/markets?matchId={mid}")
print(f"Returned {len(res3)} markets")
