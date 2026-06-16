"""One-time cleanup: Remove stale last_updated_* timestamps from all match documents.

The old _should_refresh code stamped timestamps BEFORE data was fetched. If the fetch failed
(e.g. because af_fixture_id was None), the timestamp was still set, permanently locking out
that data key with hours=None. This script removes those stale timestamps so the next
extensive_collect run will re-attempt all data fetches.

Run: python src/cleanup_stale_timestamps.py
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from src.database import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("cleanup")

STALE_KEYS = [
    "last_updated_recent_matches",
    "last_updated_advanced_stats", 
    "last_updated_stats",
    "last_updated_players",
]

from google.cloud import firestore

def cleanup():
    db = Database()
    matches = db.get_all_matches()
    
    for match in matches:
        match_name = match.get("name", "Unknown")
        match_id = str(match.get("id"))
        
        # Find any key starting with "last_updated_"
        keys_to_remove = [k for k in match.keys() if k.startswith("last_updated_")]
        
        if keys_to_remove:
            doc_ref = db.db.collection("matches").document(match_id)
            # Create an update dict mapping each key to firestore.DELETE_FIELD
            update_data = {k: firestore.DELETE_FIELD for k in keys_to_remove}
            
            try:
                doc_ref.update(update_data)
                logger.info(f"Cleared timestamps for {match_name}: {keys_to_remove}")
            except Exception as e:
                logger.warning(f"Failed to clear timestamps for {match_name}: {e}")
        else:
            logger.info(f"No timestamps found for {match_name}")
    
    logger.info("Cleanup complete. Run 'python src/main.py collect' to re-fetch stats.")

if __name__ == "__main__":
    cleanup()
