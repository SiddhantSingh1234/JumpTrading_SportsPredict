import feedparser
import urllib.parse
import logging

logger = logging.getLogger(__name__)

class NewsScraper:
    def __init__(self):
        # Google News RSS search format
        self.google_news_base = "https://news.google.com/rss/search?q="
        
        self.full_feeds = {
            "bbc_sport": "https://feeds.bbci.co.uk/sport/football/rss.xml",
            "espn_fc": "https://www.espn.com/espn/rss/soccer/news",
            "guardian": "https://www.theguardian.com/football/rss",
        }
        
    def _build_google_query(self, match):
        team_a = match.get('home_team_name', 'Team A')
        team_b = match.get('away_team_name', 'Team B')
        query = f"{team_a} vs {team_b} World Cup 2026"
        return self.google_news_base + urllib.parse.quote(query)

    def scrape_team_news(self, team_name):
        """Scrape news specifically for one national team (used in bootstrap)."""
        query = f"{team_name} National Football Team"
        url = self.google_news_base + urllib.parse.quote(query)
        return self._fetch_feed(url, max_items=8)

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

    def scrape_all_feeds(self, match):
        """Scrape all extensive RSS feeds for a match."""
        headlines = []
        
        # Google News specific to this match
        google_url = self._build_google_query(match)
        google_headlines = self._fetch_feed(google_url, max_items=15)
        headlines.extend(google_headlines)
        
        # General feeds (we would ideally filter these by team names)
        team_a = match.get('home_team_name', '').lower()
        team_b = match.get('away_team_name', '').lower()
        
        for name, url in self.full_feeds.items():
            feed_headlines = self._fetch_feed(url, max_items=20)
            # Filter general feeds for our teams
            for h in feed_headlines:
                h_lower = h.lower()
                if team_a in h_lower or team_b in h_lower:
                    headlines.append(f"({name}) {h}")
                    
        return headlines

    def quick_scan(self, match):
        """Quickly scan just Google News."""
        google_url = self._build_google_query(match)
        return self._fetch_feed(google_url, max_items=5)
