import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from src.database import Database
import datetime

db = Database()
now = datetime.datetime.utcnow()
print(f"Current UTC time: {now.isoformat()}")

matches = db.get_upcoming_matches(within_minutes=60000)
for m in matches:
    name = m.get('name')
    mid = m.get('id')
    time_str = m.get('closing_time') or m.get('opening_time')
    if time_str:
        kickoff = datetime.datetime.fromisoformat(time_str.replace("Z", "+00:00")).replace(tzinfo=None)
        delta = (kickoff - now).total_seconds() / 60.0
        print(f"{name} | id: {mid} | time: {time_str} | delta_mins: {delta:.2f}")
    else:
        print(f"{name} | id: {mid} | NO TIME")
