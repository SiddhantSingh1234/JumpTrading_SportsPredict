import requests
import feedparser
import urllib.parse
import logging
import time
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Respectful scraping headers
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

_SCRAPE_DELAY = 2  # seconds between page fetches


class NewsScraper:
    def __init__(self):
        # Google News RSS search format
        self.google_news_base = "https://news.google.com/rss/search?q="
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

        self.full_feeds = {
            "bbc_sport": "https://feeds.bbci.co.uk/sport/football/rss.xml",
            "espn_fc": "https://www.espn.com/espn/rss/soccer/news",
            "guardian": "https://www.theguardian.com/football/rss",
        }

    # ------------------------------------------------------------------ #
    #  RSS / News scraping (existing + enhanced)
    # ------------------------------------------------------------------ #

    def _build_google_query(self, match, extra_terms=""):
        team_a = match.get("home_team_name", "Team A")
        team_b = match.get("away_team_name", "Team B")
        query = f"{team_a} vs {team_b} World Cup 2026 {extra_terms}".strip()
        return self.google_news_base + urllib.parse.quote(query)

    def _fetch_feed(self, url, max_items=10):
        try:
            feed = feedparser.parse(url)
            headlines = []
            for entry in feed.entries[:max_items]:
                headlines.append(f"[{entry.title}] - {entry.get('description', '')}")
            return headlines
        except Exception as e:
            logger.error(f"Error fetching feed {url}: {e}")
            return []

    def scrape_team_news(self, team_name):
        """Scrape news specifically for one national team."""
        query = f"{team_name} National Football Team World Cup 2026"
        url = self.google_news_base + urllib.parse.quote(query)
        return self._fetch_feed(url, max_items=8)

    def scrape_all_feeds(self, match):
        """Scrape all extensive RSS feeds for a match."""
        headlines = []

        # Google News specific to this match
        google_url = self._build_google_query(match)
        google_headlines = self._fetch_feed(google_url, max_items=15)
        headlines.extend(google_headlines)

        # Match preview / analysis
        preview_url = self._build_google_query(match, "preview analysis prediction lineup")
        preview_headlines = self._fetch_feed(preview_url, max_items=10)
        headlines.extend(preview_headlines)

        # Injury news
        injury_url = self._build_google_query(match, "injury squad team news")
        injury_headlines = self._fetch_feed(injury_url, max_items=8)
        headlines.extend(injury_headlines)

        # General feeds filtered by team names
        team_a = match.get("home_team_name", "").lower()
        team_b = match.get("away_team_name", "").lower()

        for name, url in self.full_feeds.items():
            feed_headlines = self._fetch_feed(url, max_items=20)
            for h in feed_headlines:
                h_lower = h.lower()
                if team_a in h_lower or team_b in h_lower:
                    headlines.append(f"({name}) {h}")

        # De-duplicate by title
        seen = set()
        unique = []
        for h in headlines:
            key = h.split("]")[0] if "]" in h else h[:60]
            if key not in seen:
                seen.add(key)
                unique.append(h)

        return unique

    def quick_scan(self, match):
        """Quickly scan just Google News."""
        google_url = self._build_google_query(match)
        return self._fetch_feed(google_url, max_items=5)

    # ------------------------------------------------------------------ #
    #  Stats scraping from FBref
    # ------------------------------------------------------------------ #

    def _safe_get(self, url, timeout=15):
        """Fetch a URL with delay and error handling."""
        try:
            time.sleep(_SCRAPE_DELAY)
            resp = self.session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def scrape_team_stats_fbref(self, team_name):
        """Scrape team stats from FBref by searching Google for the team page.
        
        Returns dict with keys like avg_goals_scored, avg_corners, etc.
        Returns empty dict on failure.
        """
        stats = {}
        
        # Step 1: Search FBref directly to avoid Google blocking
        search_query = f"{team_name} National Football Team"
        search_url = f"https://fbref.com/en/search/search.fcgi?search={urllib.parse.quote(search_query)}"
        
        logger.info(f"Searching FBref directly for {team_name}: {search_url}")
        html = self._safe_get(search_url)
        if not html:
            logger.warning(f"FBref direct search failed for {team_name}")
            return self._scrape_team_stats_wikipedia(team_name)
        
        # If requests followed a redirect directly to the team page, parse it
        if "Standard Stats" in html or "Squad Total" in html:
            logger.info(f"FBref search redirected directly to team page for {team_name}")
            stats = self._parse_fbref_team_page(html, team_name)
            if stats: return stats
            
        # Otherwise, look for search results
        soup = BeautifulSoup(html, "html.parser")
        fbref_url = None
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/en/squads/" in href and "History" not in a_tag.get_text():
                fbref_url = "https://fbref.com" + href if href.startswith("/") else href
                break
        
        if not fbref_url:
            logger.info(f"No FBref page found in search results for {team_name}, trying Wikipedia")
            return self._scrape_team_stats_wikipedia(team_name)
        
        # Step 2: Fetch the FBref team page
        logger.info(f"Scraping FBref stats for {team_name}: {fbref_url}")
        team_html = self._safe_get(fbref_url)
        if not team_html:
            return self._scrape_team_stats_wikipedia(team_name)
        
        stats = self._parse_fbref_team_page(team_html, team_name)
        
        if not stats:
            logger.info(f"FBref parsing returned no stats for {team_name}, trying Wikipedia")
            return self._scrape_team_stats_wikipedia(team_name)
        
        return stats

    def _parse_fbref_team_page(self, html, team_name):
        """Parse FBref team page HTML to extract stats."""
        stats = {}
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # Look for the main stats table ("Standard Stats")
            # FBref uses div#all_stats_standard or similar
            tables = soup.find_all("table")
            
            for table in tables:
                caption = table.find("caption")
                if not caption:
                    continue
                caption_text = caption.get_text().lower()
                
                # Standard Stats table — has goals, assists, shots, cards
                if "standard stats" in caption_text or "scores & fixtures" in caption_text:
                    stats.update(self._parse_standard_stats_table(table, team_name))
                
                # Match logs / Scores & Fixtures
                if "scores" in caption_text and "fixture" in caption_text:
                    stats.update(self._parse_scores_table(table, team_name))
            
            # Also try to find stats from the page's text directly
            stats.update(self._extract_inline_stats(soup, team_name))
            
        except Exception as e:
            logger.warning(f"Error parsing FBref page for {team_name}: {e}")
        
        return stats

    def _parse_standard_stats_table(self, table, team_name):
        """Parse FBref Standard Stats table."""
        stats = {}
        try:
            # Find the "Squad Total" or team total row
            tfoot = table.find("tfoot")
            if not tfoot:
                return stats
            
            rows = tfoot.find_all("tr")
            if not rows:
                return stats
            
            row = rows[0]  # First footer row is usually the total
            cells = row.find_all(["td", "th"])
            
            # Build a header map
            thead = table.find("thead")
            if thead:
                header_rows = thead.find_all("tr")
                headers = []
                for hr in header_rows:
                    for th in hr.find_all("th"):
                        stat_attr = th.get("data-stat", "")
                        if stat_attr:
                            headers.append(stat_attr)
                
                cell_map = {}
                for cell in cells:
                    stat_attr = cell.get("data-stat", "")
                    if stat_attr:
                        cell_map[stat_attr] = cell.get_text(strip=True)
                
                # Extract what we need
                matches_played = self._safe_float(cell_map.get("games", "0")) or 1
                
                goals = self._safe_float(cell_map.get("goals", "0"))
                if goals and matches_played:
                    stats["avg_goals_scored"] = round(goals / matches_played, 2)
                
                cards_yellow = self._safe_float(cell_map.get("cards_yellow", "0"))
                if cards_yellow is not None and matches_played:
                    stats["avg_yellow_cards"] = round(cards_yellow / matches_played, 2)
                
                cards_red = self._safe_float(cell_map.get("cards_red", "0"))
                if cards_red is not None and matches_played:
                    stats["avg_red_cards"] = round(cards_red / matches_played, 2)
                
                pens_made = self._safe_float(cell_map.get("pens_made", "0"))
                if pens_made is not None and matches_played:
                    stats["avg_penalties"] = round(pens_made / matches_played, 2)
                    
                shots = self._safe_float(cell_map.get("shots", "0"))
                if shots is not None and matches_played:
                    stats["avg_shots"] = round(shots / matches_played, 2)
                    
                shots_on_target = self._safe_float(cell_map.get("shots_on_target", "0"))
                if shots_on_target is not None and matches_played:
                    stats["avg_shots_on_target"] = round(shots_on_target / matches_played, 2)
                    
        except Exception as e:
            logger.warning(f"Error parsing standard stats table for {team_name}: {e}")
        
        return stats

    def _parse_scores_table(self, table, team_name):
        """Parse FBref Scores & Fixtures table for goals scored/conceded."""
        stats = {}
        try:
            tbody = table.find("tbody")
            if not tbody:
                return stats
            
            rows = tbody.find_all("tr")
            goals_for_total = 0
            goals_against_total = 0
            valid = 0
            
            for row in rows:
                cells = {}
                for cell in row.find_all(["td", "th"]):
                    stat_attr = cell.get("data-stat", "")
                    if stat_attr:
                        cells[stat_attr] = cell.get_text(strip=True)
                
                gf = self._safe_float(cells.get("goals_for", ""))
                ga = self._safe_float(cells.get("goals_against", ""))
                
                if gf is not None and ga is not None:
                    goals_for_total += gf
                    goals_against_total += ga
                    valid += 1
            
            if valid > 0:
                stats["avg_goals_scored"] = round(goals_for_total / valid, 2)
                stats["avg_goals_conceded"] = round(goals_against_total / valid, 2)
                logger.info(f"FBref Scores table: {team_name} — {valid} matches, GF avg {stats['avg_goals_scored']}, GA avg {stats['avg_goals_conceded']}")
                
        except Exception as e:
            logger.warning(f"Error parsing scores table for {team_name}: {e}")
        
        return stats

    def _extract_inline_stats(self, soup, team_name):
        """Try to extract stats from FBref page text/meta content."""
        stats = {}
        try:
            # FBref often has a 'Record:' section with W-D-L and goal info
            text = soup.get_text()
            
            # Look for patterns like "Record: 5-2-1, 15 GF, 6 GA"
            record_match = re.search(r'Record:\s*(\d+)-(\d+)-(\d+),\s*(\d+)\s*GF,\s*(\d+)\s*GA', text)
            if record_match:
                w, d, l = int(record_match.group(1)), int(record_match.group(2)), int(record_match.group(3))
                gf, ga = int(record_match.group(4)), int(record_match.group(5))
                matches = w + d + l
                if matches > 0:
                    stats["avg_goals_scored"] = round(gf / matches, 2)
                    stats["avg_goals_conceded"] = round(ga / matches, 2)
                    logger.info(f"FBref inline: {team_name} — {matches} matches, GF/G {stats['avg_goals_scored']}, GA/G {stats['avg_goals_conceded']}")
        except Exception as e:
            logger.warning(f"Error extracting inline stats for {team_name}: {e}")
        
        return stats

    # ------------------------------------------------------------------ #
    #  Wikipedia fallback for stats
    # ------------------------------------------------------------------ #

    def _scrape_team_stats_wikipedia(self, team_name):
        """Fallback: scrape basic stats from Wikipedia World Cup 2026 page."""
        stats = {}
        logger.info(f"Trying Wikipedia for {team_name} stats...")
        
        # Try recent major tournaments where the team might have standardized stats tables
        wiki_urls = [
            f"https://en.wikipedia.org/wiki/2022_FIFA_World_Cup",
            f"https://en.wikipedia.org/wiki/2024_Copa_América",
            f"https://en.wikipedia.org/wiki/UEFA_Euro_2024",
            f"https://en.wikipedia.org/wiki/2023_AFC_Asian_Cup",
            f"https://en.wikipedia.org/wiki/2023_Africa_Cup_of_Nations",
            f"https://en.wikipedia.org/wiki/2026_FIFA_World_Cup" # Just in case it gets updated later
        ]
        
        for wiki_url in wiki_urls:
            html = self._safe_get(wiki_url)
            if not html:
                continue
            
            try:
                soup = BeautifulSoup(html, "html.parser")
                
                # Find tables with team standings (they contain GF, GA columns)
                tables = soup.find_all("table", class_="wikitable")
                for table in tables:
                    rows = table.find_all("tr")
                    headers = []
                    for th in rows[0].find_all("th") if rows else []:
                        headers.append(th.get_text(strip=True).upper())
                    
                    # Look for GF/GA columns
                    gf_idx = None
                    ga_idx = None
                    pld_idx = None
                    for i, h in enumerate(headers):
                        if h in ("GF", "GOALS FOR"):
                            gf_idx = i
                        elif h in ("GA", "GOALS AGAINST"):
                            ga_idx = i
                        elif h in ("PLD", "MP", "P", "PLAYED"):
                            pld_idx = i
                    
                    if gf_idx is None or ga_idx is None:
                        continue
                    
                    # Search for our team in this table
                    for row in rows[1:]:
                        cells = row.find_all(["td", "th"])
                        row_text = row.get_text().lower()
                        
                        if team_name.lower() in row_text:
                            try:
                                gf = int(cells[gf_idx].get_text(strip=True))
                                ga = int(cells[ga_idx].get_text(strip=True))
                                pld = int(cells[pld_idx].get_text(strip=True)) if pld_idx else 3
                                
                                if pld > 0:
                                    stats["avg_goals_scored"] = round(gf / pld, 2)
                                    stats["avg_goals_conceded"] = round(ga / pld, 2)
                                    logger.info(f"Wikipedia: {team_name} — {pld} matches, GF/G {stats['avg_goals_scored']}, GA/G {stats['avg_goals_conceded']}")
                                    return stats
                            except (ValueError, IndexError):
                                continue
                                
            except Exception as e:
                logger.warning(f"Error parsing Wikipedia for {team_name}: {e}")
        
        return stats

    # ------------------------------------------------------------------ #
    #  Combined stats scraper (orchestrator)
    # ------------------------------------------------------------------ #

    def scrape_comprehensive_stats(self, team_name):
        """Scrape comprehensive stats for a team. Tries FBref first, then Wikipedia.
        
        Returns a dict with all available stats:
        - avg_goals_scored, avg_goals_conceded
        - avg_corners, avg_fouls_committed  
        - avg_yellow_cards, avg_red_cards
        - avg_shots, avg_shots_on_target
        - avg_penalties
        """
        logger.info(f"Scraping comprehensive stats for {team_name}...")
        
        stats = self.scrape_team_stats_fbref(team_name)
        
        if not stats:
            logger.info(f"No web stats found for {team_name}, will rely on AI extraction from news")
        else:
            logger.info(f"Scraped stats for {team_name}: {stats}")
        
        return stats

    # ------------------------------------------------------------------ #
    #  Utility
    # ------------------------------------------------------------------ #

    @staticmethod
    def _safe_float(val):
        """Safely convert a string to float, returning None on failure."""
        if not val or val == "":
            return None
        try:
            # Remove commas and other formatting
            clean = re.sub(r'[^\d.\-]', '', str(val))
            return float(clean) if clean else None
        except (ValueError, TypeError):
            return None
