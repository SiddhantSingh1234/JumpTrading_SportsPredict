import sys
import os
import json
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from src.config import Config
from src.submitter import SportsPredictAPI

api = SportsPredictAPI(Config.BOT1_KEY)
event_id, lobby_id = api.discover()

matches = api.get_matches(event_id)

raw_output = []
for m in matches:
    time_str = m.get('closing_time') or m.get('opening_time')
    if "2026-06-16" in time_str or "2026-06-17" in time_str:
        raw_output.append(m)

print(json.dumps(raw_output, indent=2))
