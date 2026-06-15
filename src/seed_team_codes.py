import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from src.database import Database

logger = logging.getLogger("seed_team_codes")

FIFA_CODES = {
    "Argentina": "ARG", "Algeria": "ALG", "Australia": "AUS", "Austria": "AUT", 
    "Belgium": "BEL", "Bosnia and Herzegovina": "BIH", "Brazil": "BRA", "Canada": "CAN", 
    "Cabo Verde": "CPV", "Colombia": "COL", "Croatia": "CRO", "Czechia": "CZE", 
    "Curaçao": "CUW", "DR Congo": "COD", "Ecuador": "ECU", "Egypt": "EGY", 
    "England": "ENG", "France": "FRA", "Germany": "GER", "Ghana": "GHA", 
    "Haiti": "HAI", "Iran": "IRN", "Iraq": "IRQ", "Ivory Coast": "CIV", 
    "Japan": "JPN", "Jordan": "JOR", "Mexico": "MEX", "Morocco": "MAR", 
    "Netherlands": "NED", "New Zealand": "NZL", "Norway": "NOR", "Panama": "PAN", 
    "Paraguay": "PAR", "Portugal": "POR", "Qatar": "QAT", "Saudi Arabia": "KSA", 
    "Scotland": "SCO", "Senegal": "SEN", "South Africa": "RSA", "South Korea": "KOR", 
    "Spain": "ESP", "Sweden": "SWE", "Switzerland": "SUI", "Tunisia": "TUN", 
    "Türkiye": "TUR", "United States": "USA", "Uruguay": "URU", "Uzbekistan": "UZB"
}

def seed_codes():
    """Hardcodes official FIFA 3-letter strings to the database to ensure translation works perfectly."""
    logger.info("Seeding official FIFA 3-letter codes into Firestore...")
    db = Database()
    
    for full_name, code in FIFA_CODES.items():
        team_doc = db.get_team_by_name_or_code(full_name)
        
        if team_doc:
            if team_doc.get("code") != code:
                team_doc["code"] = code
                db.update_team_stats({}, team_doc)
                logger.info(f"Updated {full_name} code to {code}")
        else:
            team_id = full_name.lower().replace(" ", "_")
            new_doc = {
                "team_id": team_id,
                "name": full_name,
                "code": code
            }
            db.update_team_stats({}, new_doc)
            logger.info(f"Created new baseline document for {full_name} ({code})")
            
    logger.info("FIFA team codes seeded successfully.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_codes()
