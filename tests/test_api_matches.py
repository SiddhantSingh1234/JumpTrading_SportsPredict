import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from src.config import Config
from src.submitter import SportsPredictAPI

api = SportsPredictAPI(Config.BOT1_KEY)
event_id, lobby_id = api.discover()
print(f"Event ID: {event_id}, Lobby ID: {lobby_id}")

matches = api.get_matches(event_id)
print(f"Total matches from API: {len(matches)}")

for m in matches:
    time_str = m.get('opening_time')
    if "2026-06-16" in time_str or "2026-06-17" in time_str:
        print(f"{m.get('name')} | id: {m.get('id')} | time: {time_str}")
