import requests
import time as _time
import logging
from datetime import datetime
from src.config import Config
from src.database import Database
from src.seed_team_codes import FIFA_CODES

# Build a reverse lookup: 3-letter code -> full name
_CODE_TO_NAME = {code: name for name, code in FIFA_CODES.items()}

logger = logging.getLogger(__name__)

# ============================================================================
# API-Football and Football-Data clients are COMMENTED OUT.
# They were unreliable on the free tier (403s, paid-only params, missing teams).
# All data collection is now done via web scraping + AI extraction.
# To re-enable, uncomment the classes and their usage in DataCollector.
# ============================================================================

# def retry_request(func):
#     """Decorator to retry requests with exponential backoff on 429 and 5xx."""
#     def wrapper(*args, **kwargs):
#         retries = 3
#         backoff_factors = [5, 15, 60]
#         for i in range(retries):
#             try:
#                 response = func(*args, **kwargs)
#                 if response.status_code == 429:
#                     wait = int(response.headers.get("Retry-After", backoff_factors[i]))
#                     logger.warning(f"Rate limited (429). Waiting {wait} seconds.")
#                     _time.sleep(wait)
#                     continue
#                 if response.status_code >= 500:
#                     logger.warning(f"Server error {response.status_code}. Retrying...")
#                     _time.sleep(backoff_factors[i])
#                     continue
#                 if response.status_code in [400, 401, 403, 404]:
#                     logger.warning(f"Client error {response.status_code} for {response.url}. Failing fast.")
#                     response.raise_for_status()
#                 response.raise_for_status()
#                 return response.json()
#             except requests.RequestException as e:
#                 logger.error(f"Request failed: {e}")
#                 if i == retries - 1:
#                     raise
#                 _time.sleep(backoff_factors[i])
#     return wrapper
#
# class APIFootballClient:
#     def __init__(self):
#         self.base_url = Config.API_FOOTBALL_BASE_URL.rstrip('/')
#         host = "api-football-v1.p.rapidapi.com" if "rapidapi" in self.base_url else "v3.football.api-sports.io"
#         self.headers = {
#             "x-rapidapi-key": Config.API_FOOTBALL_KEY,
#             "x-rapidapi-host": host
#         }
#         self._last_request_time = 0
#
#     @retry_request
#     def _get(self, endpoint, params=None):
#         elapsed = _time.time() - self._last_request_time
#         if elapsed < 7:
#             _time.sleep(7 - elapsed)
#         self._last_request_time = _time.time()
#         return requests.get(f"{self.base_url}{endpoint}", headers=self.headers, params=params)
#
#     def get_fixtures_by_date(self, date_str):
#         data = self._get("/fixtures", params={"date": date_str, "league": 1, "season": "2026"})
#         if not data: return []
#         return data.get("response", [])
#
#     def get_team_stats(self, team_id, season="2026", league_id=1):
#         data = self._get("/teams/statistics", params={"team": team_id, "season": season, "league": league_id})
#         if not data: return {}
#         return data.get("response", {})
#
#     def get_recent_fixtures_for_team(self, team_id, last_n=20):
#         data = self._get("/fixtures", params={"team": team_id, "season": "2026", "status": "FT"})
#         if "errors" in data and data["errors"] or not data.get("response"):
#             data = self._get("/fixtures", params={"team": team_id, "season": "2025", "status": "FT"})
#         if "errors" in data and data["errors"]:
#             logger.error(f"API Error fetching fixtures for team {team_id}: {data['errors']}")
#         fixtures = data.get("response", [])
#         return fixtures[-last_n:] if len(fixtures) > last_n else fixtures
#
#     def get_fixture_statistics(self, fixture_id, half=None):
#         params = {"fixture": fixture_id}
#         if half: params["half"] = half
#         data = self._get("/fixtures/statistics", params=params)
#         if not data: return []
#         return data.get("response", [])
#
#     def get_injuries(self, fixture_id):
#         data = self._get("/injuries", params={"fixture": fixture_id})
#         if not data: return []
#         return data.get("response", [])
#
#     def get_lineups(self, fixture_id):
#         data = self._get("/fixtures/lineups", params={"fixture": fixture_id})
#         if not data: return []
#         return data.get("response", [])
#
#     def get_top_players(self, team_id, season="2026"):
#         data = self._get("/players", params={"team": team_id, "season": season, "page": 1})
#         if not data: return []
#         return data.get("response", [])
#
#     def search_team(self, name):
#         data = self._get("/teams", params={"name": name})
#         if not data: return None
#         if "errors" in data and data["errors"]:
#             logger.error(f"API-Football Error for {name}: {data['errors']}")
#             return None
#         responses = data.get("response", [])
#         if not responses:
#             data = self._get("/teams", params={"search": name})
#             responses = data.get("response", [])
#         if not responses:
#             logger.warning(f"API-Football returned 0 results for {name}")
#             return None
#         for r in responses:
#             team_info = r.get("team", {})
#             if team_info.get("national") is True:
#                 return team_info
#         return responses[0].get("team", {})
#
# class FootballDataClient:
#     def __init__(self):
#         self.headers = {"X-Auth-Token": Config.FOOTBALL_DATA_KEY}
#         self.base_url = Config.FOOTBALL_DATA_BASE_URL.rstrip('/')
#         self._last_request_time = 0
#
#     @retry_request
#     def _get(self, endpoint, params=None):
#         elapsed = _time.time() - self._last_request_time
#         if elapsed < 7:
#             _time.sleep(7 - elapsed)
#         self._last_request_time = _time.time()
#         return requests.get(f"{self.base_url}{endpoint}", headers=self.headers, params=params)
#
#     def search_team(self, name):
#         try:
#             data = self._get("/teams", params={"limit": 500})
#             teams = data.get("teams", [])
#             for t in teams:
#                 t_name = t.get("name", "").lower()
#                 if name.lower() in t_name:
#                     return t
#         except Exception as e:
#             logger.warning(f"Football-Data.org API failed: {e}")
#         return None
#
#     def get_recent_fixtures_for_team(self, team_id, last_n=20):
#         try:
#             data = self._get(f"/teams/{team_id}/matches", params={"status": "FINISHED", "limit": last_n})
#             if data and "matches" in data:
#                 return data["matches"][-last_n:]
#         except Exception as e:
#             logger.warning(f"Football-Data.org match fetch failed: {e}")
#         return []
#
#     def get_top_players(self, team_name):
#         try:
#             team = self.search_team(team_name)
#             if team and team.get("id"):
#                 data = self._get(f"/teams/{team.get('id')}")
#                 squad = data.get("squad", [])
#                 return [{"player": {"id": p.get("id"), "name": p.get("name"), "position": p.get("position")}} for p in squad]
#         except Exception as e:
#             logger.warning(f"Football-Data.org squad fetch failed: {e}")
#         return []
#
#     def get_team_stats(self, team_name, competition_id="2000"):
#         try:
#             team = self.search_team(team_name)
#             if not team: return {}
#             data = self._get(f"/competitions/{competition_id}/standings")
#             standings = data.get("standings", [])
#             for s in standings:
#                 table = s.get("table", [])
#                 for row in table:
#                     if row.get("team", {}).get("id") == team.get("id"):
#                         return {
#                             "form": row.get("form", ""),
#                             "rank": row.get("position"),
#                             "points": row.get("points"),
#                             "goalsDiff": row.get("goalDifference"),
#                             "all": {
#                                 "played": row.get("playedGames"),
#                                 "win": row.get("won"),
#                                 "draw": row.get("draw"),
#                                 "lose": row.get("lost"),
#                                 "goals": {
#                                     "for": row.get("goalsFor"),
#                                     "against": row.get("goalsAgainst")
#                                 }
#                             }
#                         }
#         except Exception as e:
#             logger.warning(f"Football-Data.org standings fetch failed: {e}")
#         return {}


class DataCollector:
    """Handles both extensive and quick data collection phases.
    
    All data is collected via web scraping (FBref, Wikipedia, Google News RSS)
    and AI-powered extraction. No paid football APIs are used.
    """
    def __init__(self, db: Database, sp_api, news_scraper, ai_client):
        self.db = db
        self.sp_api = sp_api
        # API clients commented out — using web scraping instead
        # self.api_football = APIFootballClient()
        # self.football_data = FootballDataClient()
        self.news_scraper = news_scraper
        self.ai = ai_client
        
    def _resolve_team_names(self, match):
        """Extract and resolve 3-letter codes to full team names from a match dict."""
        match_name = match.get("name", "")
        if " vs " in match_name:
            raw_home, raw_away = match_name.split(" vs ", 1)
        else:
            raw_home = match.get("home_team_name", "")
            raw_away = match.get("away_team_name", "")
            
        home_full = _CODE_TO_NAME.get(raw_home.strip().upper(), raw_home.strip())
        away_full = _CODE_TO_NAME.get(raw_away.strip().upper(), raw_away.strip())
        return home_full, away_full

    def extensive_collect(self, event_id):
        """PHASE 1: Extensive scraping and updates (every 6 hours).
        
        Collects stats and news for all matches within the next 24 hours
        using web scraping (FBref, Wikipedia, Google News) and AI extraction.
        """
        logger.info("Starting extensive collection (web scraping mode)...")
        matches = self.sp_api.get_matches(event_id)
        
        # Save matches to DB
        self.db.save_matches(matches)
        
        # Only collect for matches within 24 hours
        upcoming = self.db.get_upcoming_matches(within_minutes=24 * 60)
        
        if not upcoming:
            logger.info("No matches within 24 hours. Nothing to collect.")
            return
        
        logger.info(f"Found {len(upcoming)} matches within 24 hours.")
        
        for match in upcoming:
            match_name = match.get("name", "Unknown")
            logger.info(f"Processing match: {match_name}")
            
            home_full, away_full = self._resolve_team_names(match)
            
            # Create enriched match dict with full team names for scraping/AI
            enriched_match = dict(match)
            enriched_match["home_team_name"] = home_full
            enriched_match["away_team_name"] = away_full
            
            # --------------------------------------------------------
            # STEP 1: Scrape team stats from the web (FBref / Wikipedia)
            # --------------------------------------------------------
            if self._should_refresh(match, "web_stats", hours=None):
                logger.info(f"Scraping web stats for {home_full} and {away_full}...")
                
                home_stats = self.news_scraper.scrape_comprehensive_stats(home_full)
                away_stats = self.news_scraper.scrape_comprehensive_stats(away_full)
                
                # Get or create team docs using match name as ID (since we don't have API IDs)
                home_team_id = match.get("home_team_id") or home_full.replace(" ", "_").lower()
                away_team_id = match.get("away_team_id") or away_full.replace(" ", "_").lower()
                
                # Save team IDs back to match if they weren't set
                if not match.get("home_team_id"):
                    match["home_team_id"] = home_team_id
                if not match.get("away_team_id"):
                    match["away_team_id"] = away_team_id
                self.db.save_matches([match])
                
                # Merge scraped stats into team docs
                if home_stats:
                    home_doc = self.db.get_team(home_team_id) or {"team_id": str(home_team_id)}
                    home_doc.update(home_stats)
                    self.db.update_team_stats(match, home_doc)
                    logger.info(f"Saved web-scraped stats for {home_full}: {home_stats}")
                
                if away_stats:
                    away_doc = self.db.get_team(away_team_id) or {"team_id": str(away_team_id)}
                    away_doc.update(away_stats)
                    self.db.update_team_stats(match, away_doc)
                    logger.info(f"Saved web-scraped stats for {away_full}: {away_stats}")
                
                self._mark_refreshed(match, "web_stats")
            
            # --------------------------------------------------------
            # STEP 2: Scrape news + AI summarization + AI stats extraction
            # --------------------------------------------------------
            if self._should_refresh(match, "news", hours=2.5):
                logger.info(f"Scraping news for {home_full} vs {away_full}...")
                
                headlines = self.news_scraper.scrape_all_feeds(enriched_match)
                logger.info(f"Collected {len(headlines)} headlines for {match_name}")
                
                previous_briefing = self.db.get_news(match.get("id"))
                
                # AI summarization
                briefing = ""
                if self.ai and headlines:
                    briefing = self.ai.summarize_news(headlines, previous_briefing, enriched_match)
                
                # AI structured stats extraction from news
                structured = {}
                if self.ai and headlines:
                    structured = self.ai.extract_stats(headlines, enriched_match)
                
                self.db.save_news(match.get("id"), briefing, headlines, structured)
                self._mark_refreshed(match, "news")
                
                # Inject AI-extracted stats into team docs if web scraping missed them
                home_team_id = match.get("home_team_id")
                away_team_id = match.get("away_team_id")
                
                if structured:
                    self._inject_ai_stats(match, home_team_id, home_full, structured, "home")
                    self._inject_ai_stats(match, away_team_id, away_full, structured, "away")
        
        logger.info("Extensive collection complete.")

    def _inject_ai_stats(self, match, team_id, team_name, structured, side):
        """Inject AI-mined stats into team documents if they're still at default baselines."""
        if not team_id or not structured:
            return
            
        team_doc = self.db.get_team(team_id)
        if not team_doc:
            return
            
        updated = False
        
        # Map structured news keys to team doc keys with their default baselines
        stat_mappings = {
            "recent_corners": ("avg_corners", 5.0),
            "recent_yellow_cards": ("avg_yellow_cards", 2.0),
            "recent_red_cards": ("avg_red_cards", 0.1),
            "recent_fouls": ("avg_fouls_committed", 12.0),
            "recent_shots": ("avg_shots", 10.0),
            "recent_shots_on_target": ("avg_shots_on_target", 4.0),
            "recent_penalties": ("avg_penalties", 0.1),
        }
        
        # Use side-specific keys if available (e.g., "home_recent_corners"), else fall back to generic
        for news_key, (doc_key, default_val) in stat_mappings.items():
            side_key = f"{side}_{news_key}"
            val = structured.get(side_key) or structured.get(news_key)
            if val is not None and team_doc.get(doc_key, default_val) == default_val:
                try:
                    team_doc[doc_key] = float(val)
                    updated = True
                except (ValueError, TypeError):
                    pass
        
        if updated:
            self.db.update_team_stats(match, team_doc)
            logger.info(f"Injected AI-mined stats for {team_name}")

    def quick_refresh(self, match_id):
        """PHASE 2: Quick refresh for imminent matches (T-45m or queries).
        
        Only scrapes latest Google News headlines and updates the briefing.
        """
        logger.info(f"Quick refresh for match {match_id}...")
        match = self.db.get_match(match_id)
        if not match:
            return False
        
        home_full, away_full = self._resolve_team_names(match)
        enriched_match = dict(match)
        enriched_match["home_team_name"] = home_full
        enriched_match["away_team_name"] = away_full
        
        # Quick scan via Google News RSS only
        latest_headlines = self.news_scraper.quick_scan(enriched_match)
        
        if latest_headlines:
            old_briefing = self.db.get_news(match_id)
            new_briefing = self.ai.summarize_news(latest_headlines, old_briefing, enriched_match)
            structured = self.ai.extract_stats(latest_headlines, enriched_match)
            self.db.save_news(match_id, new_briefing, latest_headlines, structured)
            return True
            
        return False

    def _should_refresh(self, match, key, hours=6):
        """Check if we should refresh data for this key. Does NOT stamp the timestamp."""
        state_key = f"last_updated_{key}"
        last_updated_str = match.get(state_key)
        
        if not last_updated_str:
            return True  # Never updated — needs refresh
            
        if hours is None:
            return False  # hours=None means "only once" and it was already done
            
        try:
            last_updated = datetime.fromisoformat(last_updated_str)
            delta_hours = (datetime.utcnow() - last_updated).total_seconds() / 3600.0
            return delta_hours >= hours
        except Exception:
            return True

    def _mark_refreshed(self, match, key):
        """Stamp the timestamp AFTER data was successfully fetched."""
        state_key = f"last_updated_{key}"
        match[state_key] = datetime.utcnow().isoformat()
        self.db.save_matches([match])
