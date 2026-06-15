import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from src.database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bootstrap")

def run_bootstrap():
    """Initializes the database with foundational team data."""
    logger.info("Running bootstrap...")
    
    db = Database()
    
    if db.is_initialized():
        logger.info("Database already initialized. Exiting.")
        return
        
    logger.info("Initializing baseline stats for the 48 World Cup teams...")
    from src.collector import APIFootballClient, FootballDataClient
    from src.news_scraper import NewsScraper
    from src.ai_client import AIClient
    from src.config import Config
    
    af_client = APIFootballClient()
    fd_client = FootballDataClient()
    news_scraper = NewsScraper()
    ai_client = AIClient(Config.GEMINI_API_KEY)
    
    world_cup_teams = [
        "Argentina", "Algeria", "Australia", "Austria", "Belgium", "Bosnia and Herzegovina", 
        "Brazil", "Canada", "Cabo Verde", "Colombia", "Croatia", "Czechia", "Curaçao", 
        "DR Congo", "Ecuador", "Egypt", "England", "France", "Germany", "Ghana", "Haiti", 
        "Iran", "Iraq", "Ivory Coast", "Japan", "Jordan", "Mexico", "Morocco", "Netherlands", 
        "New Zealand", "Norway", "Panama", "Paraguay", "Portugal", "Qatar", "Saudi Arabia", 
        "Scotland", "Senegal", "South Africa", "South Korea", "Spain", "Sweden", 
        "Switzerland", "Tunisia", "Türkiye", "United States", "Uruguay", "Uzbekistan"
    ]
    
    for team_name in world_cup_teams:
        import time
        time.sleep(6.5) # Protect against the 10 requests/minute free tier limit
        
        logger.info(f"Bootstrapping {team_name}...")
        
        # 1. Search Both APIs
        team_info = af_client.search_team(team_name)
        fd_info = fd_client.search_team(team_name)
        
        # Fallback to slugified name if both APIs fail
        team_id = team_name.lower().replace(" ", "_")
        fd_team_id = None
        
        if team_info and team_info.get("id"):
            team_id = str(team_info.get("id"))
        if fd_info and fd_info.get("id"):
            fd_team_id = str(fd_info.get("id"))
        
        goals_scored = 0
        goals_conceded = 0
        ht_goals_scored = 0
        ht_goals_conceded = 0
        valid_matches = 0
        
        # Try API-Football First
        if team_info:
            recent_matches = af_client.get_recent_fixtures_for_team(team_id, last_n=20)
            if recent_matches:
                db.save_historical_matches(team_id, recent_matches)
                for m in recent_matches:
                    score = m.get("goals", {})
                    ht_score = m.get("score", {}).get("halftime", {})
                    t_home_id = str(m.get("teams", {}).get("home", {}).get("id"))
                    t_away_id = str(m.get("teams", {}).get("away", {}).get("id"))
                    
                    h_goals, a_goals = score.get("home"), score.get("away")
                    h_ht, a_ht = ht_score.get("home"), ht_score.get("away")
                    
                    if h_goals is not None and a_goals is not None:
                        valid_matches += 1
                        if team_id == t_home_id:
                            goals_scored += h_goals
                            goals_conceded += a_goals
                            if h_ht is not None: ht_goals_scored += h_ht
                            if a_ht is not None: ht_goals_conceded += a_ht
                        elif team_id == t_away_id:
                            goals_scored += a_goals
                            goals_conceded += h_goals
                            if a_ht is not None: ht_goals_scored += a_ht
                            if h_ht is not None: ht_goals_conceded += h_ht
        
        # If API-Football Failed, Fallback to Football-Data.org
        if valid_matches == 0 and fd_team_id:
            logger.info(f"API-Football skipped for {team_name}. Falling back to Football-Data.org for matches.")
            fd_matches = fd_client.get_recent_fixtures_for_team(fd_team_id, last_n=20)
            if fd_matches:
                for m in fd_matches:
                    score = m.get("score", {}).get("fullTime", {})
                    ht_score = m.get("score", {}).get("halfTime", {})
                    t_home_id = str(m.get("homeTeam", {}).get("id"))
                    t_away_id = str(m.get("awayTeam", {}).get("id"))
                    
                    h_goals, a_goals = score.get("home"), score.get("away")
                    h_ht, a_ht = ht_score.get("home"), ht_score.get("away")
                    
                    if h_goals is not None and a_goals is not None:
                        valid_matches += 1
                        if fd_team_id == t_home_id:
                            goals_scored += h_goals
                            goals_conceded += a_goals
                            if h_ht is not None: ht_goals_scored += h_ht
                            if a_ht is not None: ht_goals_conceded += a_ht
                        elif fd_team_id == t_away_id:
                            goals_scored += a_goals
                            goals_conceded += h_goals
                            if a_ht is not None: ht_goals_scored += a_ht
                            if h_ht is not None: ht_goals_conceded += h_ht
        
        if valid_matches == 0:
            logger.warning(f"Both APIs failed to find recent matches for {team_name}. Using baseline 1.5/1.0")
            avg_scored, avg_conceded = 1.5, 1.0
            avg_ht_scored, avg_ht_conceded = 0.5, 0.5
        else:
            avg_scored = goals_scored / valid_matches
            avg_conceded = goals_conceded / valid_matches
            avg_ht_scored = ht_goals_scored / valid_matches
            avg_ht_conceded = ht_goals_conceded / valid_matches
        
        team_doc = {
            "team_id": team_id,
            "name": team_name,
            "code": team_info.get("code", team_name[:3].upper()) if team_info else team_name[:3].upper(),
            "logo": team_info.get("logo", "") if team_info else "",
            "avg_goals_scored": round(avg_scored, 2),
            "avg_goals_conceded": round(avg_conceded, 2),
            "avg_ht_goals_scored": round(avg_ht_scored, 2),
            "avg_ht_goals_conceded": round(avg_ht_conceded, 2),
            # Advanced stats fallbacks to protect API limits during massive bootstrap.
            "avg_corners": 5.0,
            "avg_fouls_committed": 12.0,
            "avg_yellow_cards": 2.0,
            "avg_red_cards": 0.1,
            "avg_shots": 10.0,
            "avg_shots_on_target": 4.0,
            "avg_penalties": 0.1,
            "avg_ht_corners": 2.5,
            "avg_ht_fouls": 6.0
        }
        
        # 2. Football-Data.org Enrichment
        if fd_info:
            team_doc["founded"] = fd_info.get("founded")
            team_doc["club_colors"] = fd_info.get("clubColors")
            team_doc["venue"] = fd_info.get("venue")
            coach = fd_info.get("coach", {})
            if coach:
                team_doc["coach_name"] = coach.get("name")
        
        # 3. Baseline News Briefing
        headlines = news_scraper.scrape_team_news(team_name)
        if headlines:
            # Create a fake match context to trick the summarizer into making a general briefing
            fake_match = {"home_team_name": team_name, "away_team_name": ""}
            briefing = ai_client.summarize_news(headlines, "", fake_match)
            team_doc["baseline_news_briefing"] = briefing
            
        db.update_team_stats({}, team_doc)
        
    db.save_state("initialized", True)
    logger.info("Bootstrap complete.")

if __name__ == "__main__":
    run_bootstrap()
