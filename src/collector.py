import requests
import time as _time
import time
import logging
from datetime import datetime
from src.config import Config
from src.database import Database

logger = logging.getLogger(__name__)

def retry_request(func):
    """Decorator to retry requests with exponential backoff on 429 and 5xx."""
    def wrapper(*args, **kwargs):
        retries = 3
        backoff_factors = [5, 15, 60]
        for i in range(retries):
            try:
                response = func(*args, **kwargs)
                if response.status_code == 429:
                    wait = int(response.headers.get("Retry-After", backoff_factors[i]))
                    logger.warning(f"Rate limited (429). Waiting {wait} seconds.")
                    time.sleep(wait)
                    continue
                if response.status_code >= 500:
                    logger.warning(f"Server error {response.status_code}. Retrying...")
                    time.sleep(backoff_factors[i])
                    continue
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                logger.error(f"Request failed: {e}")
                if i == retries - 1:
                    raise
                time.sleep(backoff_factors[i])
    return wrapper

class APIFootballClient:
    def __init__(self):
        self.base_url = Config.API_FOOTBALL_BASE_URL.rstrip('/')
        
        # Determine host for RapidAPI vs Direct
        host = "api-football-v1.p.rapidapi.com" if "rapidapi" in self.base_url else "v3.football.api-sports.io"
        
        self.headers = {
            "x-apisports-key": Config.API_FOOTBALL_KEY,  # Used if registered directly at api-sports.io
            "x-rapidapi-key": Config.API_FOOTBALL_KEY,   # Used if registered via RapidAPI
            "x-rapidapi-host": host
        }
        self._last_request_time = 0
        
    @retry_request
    def _get(self, endpoint, params=None):
        # Enforce 7s gap between requests (10 RPM free tier = 6s minimum, +1s buffer)
        elapsed = _time.time() - self._last_request_time
        if elapsed < 7:
            _time.sleep(7 - elapsed)
        self._last_request_time = _time.time()
        return requests.get(f"{self.base_url}{endpoint}", headers=self.headers, params=params)

    def get_team_stats(self, team_id, season, league_id):
        data = self._get("/teams/statistics", params={"team": team_id, "season": season, "league": league_id})
        return data.get("response", {})
        
    def get_injuries(self, fixture_id):
        data = self._get("/injuries", params={"fixture": fixture_id})
        return data.get("response", [])
        
    def get_lineups(self, fixture_id):
        data = self._get("/fixtures/lineups", params={"fixture": fixture_id})
        return data.get("response", [])
        
    def get_top_players(self, team_id, season):
        data = self._get("/players", params={"team": team_id, "season": season, "page": 1})
        # Note: in a real app, might need to paginate to get all key players
        return data.get("response", [])
        
    def get_fixtures_by_date(self, date_str):
        data = self._get("/fixtures", params={"date": date_str})
        return data.get("response", [])
        
    def get_recent_fixtures_for_team(self, team_id, last_n=20):
        data = self._get("/fixtures", params={"team": team_id, "last": last_n})
        
        if "errors" in data and data["errors"]:
            logger.error(f"API Error fetching fixtures for team {team_id}: {data['errors']}")
            
        return data.get("response", [])
        
    def get_fixture_statistics(self, fixture_id, half=None):
        params = {"fixture": fixture_id}
        if half:
            params["half"] = half
        data = self._get("/fixtures/statistics", params=params)
        return data.get("response", [])
        
    def search_team(self, name):
        """Search for a team by name and prioritize national teams."""
        # Try exact name first
        data = self._get("/teams", params={"name": name})
        
        if "errors" in data and data["errors"]:
            logger.error(f"API-Football Error for {name}: {data['errors']}")
            return None
            
        responses = data.get("response", [])
        
        if not responses:
            # Fallback to search if exact name fails
            data = self._get("/teams", params={"search": name})
            responses = data.get("response", [])
            
        if not responses:
            logger.warning(f"API-Football returned 0 results for {name}")
            return None
        
        # Try to find the national team specifically to avoid club name collisions
        for r in responses:
            team_info = r.get("team", {})
            if team_info.get("national") is True:
                return team_info
                
        # Fallback to the first result if no explicit national flag
        return responses[0].get("team", {})

class FootballDataClient:
    def __init__(self):
        self.headers = {
            "X-Auth-Token": Config.FOOTBALL_DATA_KEY
        }
        self.base_url = Config.FOOTBALL_DATA_BASE_URL.rstrip('/')
        self._last_request_time = 0
        
    @retry_request
    def _get(self, endpoint, params=None):
        # Football-Data.org free tier: 10 requests/minute
        elapsed = _time.time() - self._last_request_time
        if elapsed < 7:
            _time.sleep(7 - elapsed)
        self._last_request_time = _time.time()
        return requests.get(f"{self.base_url}{endpoint}", headers=self.headers, params=params)

    def search_team(self, name):
        """Search for a team. Football-Data doesn't have a direct team search, so we query teams and filter locally."""
        try:
            data = self._get("/teams", params={"limit": 500})
            teams = data.get("teams", [])
            for t in teams:
                t_name = t.get("name", "").lower()
                if name.lower() in t_name:
                    return t
        except Exception as e:
            logger.warning(f"Football-Data.org API failed (check your API key or connection): {e}")
        return None

    def get_recent_fixtures_for_team(self, team_id, last_n=20):
        """Fetch recent matches from Football-Data.org as a fallback."""
        try:
            data = self._get(f"/teams/{team_id}/matches", params={"status": "FINISHED", "limit": last_n})
            if data and "matches" in data:
                return data["matches"][-last_n:] # ensure we only get last_n if API ignores limit
        except Exception as e:
            logger.warning(f"Football-Data.org match fetch failed: {e}")
        return []

    def get_top_players(self, team_name):
        """Fetch team squad from Football-Data.org as a fallback for players."""
        try:
            team = self.search_team(team_name)
            if team and team.get("id"):
                data = self._get(f"/teams/{team.get('id')}")
                squad = data.get("squad", [])
                # Format to roughly match API-Football structure
                return [{"player": {"id": p.get("id"), "name": p.get("name"), "position": p.get("position")}} for p in squad]
        except Exception as e:
            logger.warning(f"Football-Data.org squad fetch failed: {e}")
        return []

    def get_team_stats(self, team_name, competition_id="2000"):
        """Fetch team standings/form from Football-Data.org as a fallback."""
        try:
            team = self.search_team(team_name)
            if not team: return {}
            
            data = self._get(f"/competitions/{competition_id}/standings")
            standings = data.get("standings", [])
            for s in standings:
                table = s.get("table", [])
                for row in table:
                    if row.get("team", {}).get("id") == team.get("id"):
                        return {
                            "form": row.get("form", ""),
                            "rank": row.get("position"),
                            "points": row.get("points"),
                            "goalsDiff": row.get("goalDifference"),
                            "all": {
                                "played": row.get("playedGames"),
                                "win": row.get("won"),
                                "draw": row.get("draw"),
                                "lose": row.get("lost"),
                                "goals": {
                                    "for": row.get("goalsFor"),
                                    "against": row.get("goalsAgainst")
                                }
                            }
                        }
        except Exception as e:
            logger.warning(f"Football-Data.org standings fetch failed: {e}")
        return {}

class DataCollector:
    """Handles both extensive and quick data collection phases."""
    def __init__(self, db: Database, sp_api, news_scraper, ai_client):
        self.db = db
        self.sp_api = sp_api
        self.api_football = APIFootballClient()
        self.football_data = FootballDataClient()
        self.news_scraper = news_scraper
        self.ai = ai_client
        
    def extensive_collect(self, event_id):
        """PHASE 1: Extensive scraping and updates (every 6 hours)."""
        logger.info("Starting extensive collection...")
        matches = self.sp_api.get_matches(event_id)
        
        # Save matches to DB (updates their kickoff times)
        self.db.save_matches(matches)
        
        upcoming = self.db.get_upcoming_matches(within_minutes=72 * 60) # Next 3 days
        
        for match in upcoming:
            logger.info(f"Processing upcoming match: {match.get('name')}")
            # Find the true API-Football fixture ID by searching by date and matching team names
            af_fixture_id = match.get("api_football_fixture_id") 
            home_team_id = match.get("home_team_id")
            away_team_id = match.get("away_team_id")
            season = "2026"
            league_id = 1  # World Cup league ID in API-football
            
            if not af_fixture_id and match.get("kickoff_time"):
                date_str = match["kickoff_time"].split("T")[0]
                fixtures = self.api_football.get_fixtures_by_date(date_str)
                for f in fixtures:
                    t_home = f.get("teams", {}).get("home", {}).get("name", "").lower()
                    t_away = f.get("teams", {}).get("away", {}).get("name", "").lower()
                    if match.get("home_team_name", "").lower() in t_home or t_home in match.get("home_team_name", "").lower():
                        af_fixture_id = f.get("fixture", {}).get("id")
                        home_team_id = f.get("teams", {}).get("home", {}).get("id")
                        away_team_id = f.get("teams", {}).get("away", {}).get("id")
                        
                        # Save the discovered IDs back to the match
                        match["api_football_fixture_id"] = af_fixture_id
                        match["home_team_id"] = home_team_id
                        match["away_team_id"] = away_team_id
                        self.db.save_matches([match])
                        break
            
            if af_fixture_id:
                # Update recent matches to capture friendlies/qualifiers played since bootstrap
                if self._should_refresh(match, "recent_matches", hours=None):
                    for tid in [home_team_id, away_team_id]:
                        if tid:
                            team_name = match.get("home_team_name") if tid == home_team_id else match.get("away_team_name")
                            self._update_team_goals(tid, team_name, match)
                                
                # Lazy Load Advanced Statistics (Corners, Fouls, Cards)
                if self._should_refresh(match, "advanced_stats", hours=None):
                    for tid in [home_team_id, away_team_id]:
                        if not tid: continue
                        
                        recent_4 = self.db.get_recent_historical_matches_safe(tid, limit=4)
                        if not recent_4: continue
                        
                        totals = {"Corner Kicks": 0, "Fouls": 0, "Yellow Cards": 0, "Red Cards": 0, "Total Shots": 0, "Shots on Goal": 0, "Penalty": 0}
                        ht_totals = {"Corner Kicks": 0, "Fouls": 0}
                        valid_matches = 0
                        valid_ht_matches = 0
                        
                        for hist_match in recent_4:
                            fix_id = hist_match.get("fixture", {}).get("id")
                            if not fix_id: continue
                            
                            stats_res = self.api_football.get_fixture_statistics(fix_id)
                            ht_stats_res = self.api_football.get_fixture_statistics(fix_id, half="1st Half")
                            
                            # Find our team's stats in the response
                            team_stats = next((s for s in stats_res if str(s.get("team", {}).get("id")) == str(tid)), None)
                            ht_team_stats = next((s for s in ht_stats_res if str(s.get("team", {}).get("id")) == str(tid)), None)
                            
                            if team_stats and team_stats.get("statistics"):
                                valid_matches += 1
                                for stat_obj in team_stats["statistics"]:
                                    stype = stat_obj.get("type")
                                    val = stat_obj.get("value")
                                    if stype in totals and val is not None:
                                        try:
                                            totals[stype] += int(val)
                                        except (ValueError, TypeError):
                                            pass
                                            
                            if ht_team_stats and ht_team_stats.get("statistics"):
                                valid_ht_matches += 1
                                for stat_obj in ht_team_stats["statistics"]:
                                    stype = stat_obj.get("type")
                                    val = stat_obj.get("value")
                                    if stype in ht_totals and val is not None:
                                        try:
                                            ht_totals[stype] += int(val)
                                        except (ValueError, TypeError):
                                            pass
                        
                        if valid_matches > 0:
                            team_doc = self.db.get_team(tid) or {"team_id": str(tid)}
                            team_doc["avg_corners"] = round(totals["Corner Kicks"] / valid_matches, 2)
                            team_doc["avg_fouls_committed"] = round(totals["Fouls"] / valid_matches, 2)
                            team_doc["avg_yellow_cards"] = round(totals["Yellow Cards"] / valid_matches, 2)
                            team_doc["avg_red_cards"] = round(totals["Red Cards"] / valid_matches, 2)
                            team_doc["avg_shots"] = round(totals.get("Total Shots", 0) / valid_matches, 2)
                            team_doc["avg_shots_on_target"] = round(totals.get("Shots on Goal", 0) / valid_matches, 2)
                            team_doc["avg_penalties"] = round(totals.get("Penalty", 0) / valid_matches, 2)
                            
                            if valid_ht_matches > 0:
                                team_doc["avg_ht_corners"] = round(ht_totals["Corner Kicks"] / valid_ht_matches, 2)
                                team_doc["avg_ht_fouls"] = round(ht_totals["Fouls"] / valid_ht_matches, 2)
                                
                            self.db.update_team_stats(match, team_doc)
                            logger.info(f"Updated advanced stats for team {tid} (Full: {totals}, HT: {ht_totals})")
                
                # Stats
                if self._should_refresh(match, "stats", hours=None):
                    for tid in [home_team_id, away_team_id]:
                        if tid:
                            stats = self.api_football.get_team_stats(tid, season, league_id)
                            if not stats:
                                team_name = match.get("home_team_name") if tid == home_team_id else match.get("away_team_name")
                                logger.info(f"API-Football skipped for stats of {team_name}, falling back to Football-Data.org")
                                stats = self.football_data.get_team_stats(team_name)
                            
                            stats["team_id"] = tid
                            self.db.update_team_stats(match, stats)

                # Injuries & Lineups
                if self._should_refresh(match, "injuries", hours=3):
                    injuries = self.api_football.get_injuries(af_fixture_id)
                    lineups = self.api_football.get_lineups(af_fixture_id)
                    self.db.update_injuries(match, injuries)
                    self.db.update_lineups(match, lineups)
                    
                # Players
                if self._should_refresh(match, "players", hours=None):
                    for tid in [home_team_id, away_team_id]:
                        if tid:
                            players = self.api_football.get_top_players(tid, season)
                            if not players:
                                team_name = match.get("home_team_name") if tid == home_team_id else match.get("away_team_name")
                                logger.info(f"API-Football skipped for players of {team_name}, falling back to Football-Data.org")
                                players = self.football_data.get_top_players(team_name)
                            self.db.update_players(tid, players)

            # Extensive News & AI-Mined Stats
            if self._should_refresh(match, "news", hours=3):
                headlines = self.news_scraper.scrape_all_feeds(match)
                previous_briefing = self.db.get_news(match.get("id"))
                
                briefing = self.ai.summarize_news(headlines, previous_briefing, match)
                structured = self.ai.extract_stats(headlines, match)
                
                self.db.save_news(match.get("id"), briefing, headlines, structured)
                
                # Inject AI-Mined Advanced Stats (Corners/Cards) if API-Football is completely dead
                for tid, tname in [(home_team_id, match.get("home_team_name")), (away_team_id, match.get("away_team_name"))]:
                    if tid and structured:
                        team_doc = self.db.get_team(tid)
                        if team_doc:
                            updated = False
                            # Only inject if we are locked to the default mathematical baselines (meaning API-Football failed)
                            if "recent_corners" in structured and team_doc.get("avg_corners") == 5.0:
                                team_doc["avg_corners"] = float(structured["recent_corners"])
                                updated = True
                            if "recent_yellow_cards" in structured and team_doc.get("avg_yellow_cards") == 2.0:
                                team_doc["avg_yellow_cards"] = float(structured["recent_yellow_cards"])
                                updated = True
                            if "recent_fouls" in structured and team_doc.get("avg_fouls_committed") == 12.0:
                                team_doc["avg_fouls_committed"] = float(structured["recent_fouls"])
                                updated = True
                            if "recent_red_cards" in structured and team_doc.get("avg_red_cards") == 0.1:
                                team_doc["avg_red_cards"] = float(structured["recent_red_cards"])
                                updated = True
                            if "recent_shots" in structured and team_doc.get("avg_shots") == 10.0:
                                team_doc["avg_shots"] = float(structured["recent_shots"])
                                updated = True
                            if "recent_shots_on_target" in structured and team_doc.get("avg_shots_on_target") == 4.0:
                                team_doc["avg_shots_on_target"] = float(structured["recent_shots_on_target"])
                                updated = True
                            if "recent_penalties" in structured and team_doc.get("avg_penalties") == 0.1:
                                team_doc["avg_penalties"] = float(structured["recent_penalties"])
                                updated = True
                                
                            if updated:
                                self.db.update_team_stats(match, team_doc)
                                logger.info(f"Injected AI-mined stats for {tname} due to API-Football fallback.")
        
        logger.info("Extensive collection complete.")

    def quick_refresh(self, match_id):
        """PHASE 2: Quick refresh for imminent matches (T-45m or queries)."""
        logger.info(f"Quick refresh for match {match_id}...")
        match = self.db.get_match(match_id)
        if not match:
            return False
            
        af_fixture_id = match.get("api_football_fixture_id")
        changes_detected = False
        
        latest_injuries = []
        latest_lineups = []
        if af_fixture_id:
            latest_injuries = self.api_football.get_injuries(af_fixture_id)
            latest_lineups = self.api_football.get_lineups(af_fixture_id)
            # Compare with DB (simple check, assume anything fetched is "changes" for now)
            changes_detected = True 
            
        latest_headlines = self.news_scraper.quick_scan(match)
        if latest_headlines:
            changes_detected = True
            
        if changes_detected:
            old_briefing = self.db.get_news(match_id)
            # Update briefing with new info
            new_briefing = self.ai.summarize_news(latest_headlines, old_briefing, match)
            # For quick refresh, we might skip deep structured stats extraction to save time/tokens,
            # but we'll do it if it's cheap enough.
            structured = self.ai.extract_stats(latest_headlines, match)
            self.db.save_news(match_id, new_briefing, latest_headlines, structured)
            
            # Update the match doc
            self.db.update_injuries(match, latest_injuries)
            self.db.update_lineups(match, latest_lineups)
            
        return changes_detected

    def _should_refresh(self, match, key, hours=6):
        """Helper to decide if we should make API calls based on time."""
        state_key = f"last_updated_{key}"
        last_updated_str = match.get(state_key)
        
        if not last_updated_str:
            # If we've never updated it, return True and stamp it now
            match[state_key] = datetime.utcnow().isoformat()
            self.db.save_matches([match])
            return True
            
        if hours is None:
            return False
            
        try:
            last_updated = datetime.fromisoformat(last_updated_str)
            delta_hours = (datetime.utcnow() - last_updated).total_seconds() / 3600.0
            if delta_hours >= hours:
                match[state_key] = datetime.utcnow().isoformat()
                self.db.save_matches([match])
                return True
            return False
        except Exception:
            return True

    def _update_team_goals(self, team_id, team_name, match_doc):
        """Re-calculate goal averages using the API-Football -> Football-Data cascade."""
        valid_matches = 0
        goals_scored = 0
        goals_conceded = 0
        ht_goals_scored = 0
        ht_goals_conceded = 0
        
        # 1. Try API Football
        recent_matches = self.api_football.get_recent_fixtures_for_team(team_id, last_n=20)
        if recent_matches:
            self.db.save_historical_matches(team_id, recent_matches)
            for m in recent_matches:
                score = m.get("goals", {})
                ht_score = m.get("score", {}).get("halftime", {})
                t_home_id = str(m.get("teams", {}).get("home", {}).get("id"))
                t_away_id = str(m.get("teams", {}).get("away", {}).get("id"))
                
                h_goals, a_goals = score.get("home"), score.get("away")
                h_ht, a_ht = ht_score.get("home"), ht_score.get("away")
                
                if h_goals is not None and a_goals is not None:
                    valid_matches += 1
                    if str(team_id) == t_home_id:
                        goals_scored += h_goals
                        goals_conceded += a_goals
                        if h_ht is not None: ht_goals_scored += h_ht
                        if a_ht is not None: ht_goals_conceded += a_ht
                    elif str(team_id) == t_away_id:
                        goals_scored += a_goals
                        goals_conceded += h_goals
                        if a_ht is not None: ht_goals_scored += a_ht
                        if h_ht is not None: ht_goals_conceded += h_ht
                        
        # 2. Football-Data Fallback
        if valid_matches == 0:
            fd_team = self.football_data.search_team(team_name)
            if fd_team and fd_team.get("id"):
                fd_team_id = str(fd_team.get("id"))
                fd_matches = self.football_data.get_recent_fixtures_for_team(fd_team_id, last_n=20)
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
                                
        # 3. Update Database if we found matches
        if valid_matches > 0:
            team_doc = self.db.get_team(team_id) or {"team_id": str(team_id)}
            team_doc["avg_goals_scored"] = round(goals_scored / valid_matches, 2)
            team_doc["avg_goals_conceded"] = round(goals_conceded / valid_matches, 2)
            team_doc["avg_ht_goals_scored"] = round(ht_goals_scored / valid_matches, 2)
            team_doc["avg_ht_goals_conceded"] = round(ht_goals_conceded / valid_matches, 2)
            self.db.update_team_stats(match_doc, team_doc)
            logger.info(f"Dynamically updated goal averages for {team_name} based on {valid_matches} live matches.")
