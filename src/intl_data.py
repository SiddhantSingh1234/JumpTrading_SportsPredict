"""International football results, Elo, and player scoring rates.

Keystone free data source: the martj42 ``international_results`` dataset
(CC0, public domain) — every men's international since 1872, refreshed
continuously, including current World Cup 2026 fixtures and goalscorers.

This module:
  * Downloads & caches ``results.csv`` and ``goalscorers.csv`` (with a TTL and
    graceful fallback to stale cache if the network is unavailable).
  * Computes per-team attacking/defensive rates and outcome base rates from
    recent *played* matches.
  * Computes a World-Football-style Elo rating for every team from the full
    history, and converts an Elo difference into win/draw/loss + expected
    goals for a fixture.
  * Computes per-player "anytime scorer" rates from goalscorers data.

All inputs are free and require no API key. Everything degrades to ``None`` /
empty dicts on failure so callers can fall back to base rates — never to a
blanket 0.50.
"""

import csv
import io
import logging
import math
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

from src.config import Config
from src.team_names import to_dataset_name

logger = logging.getLogger(__name__)

_RESULTS_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
_GOALSCORERS_URL = "https://raw.githubusercontent.com/martj42/international_results/master/goalscorers.csv"

_CACHE_DIR = os.path.join(Config.DATA_DIR, "free")
_CACHE_TTL_SECONDS = 12 * 3600  # refresh at most every 12h (dataset updates daily)

# K-factor weights by tournament importance (World Football Elo conventions).
_TOURNAMENT_WEIGHT = {
    "FIFA World Cup": 60,
    "FIFA World Cup qualification": 40,
    "Copa América": 50,
    "UEFA Euro": 50,
    "African Cup of Nations": 50,
    "AFC Asian Cup": 50,
    "UEFA Nations League": 40,
    "Confederations Cup": 40,
    "Gold Cup": 40,
    "Friendly": 20,
}
_DEFAULT_K = 30
_HOME_FIELD_ELO = 65  # applied to the designated home side when not neutral


def elo_match_probs(rh, ra, neutral=True, total_goals=2.6):
    """Standalone Elo -> win/draw/loss + expected goals.

    Pure math on two Elo numbers so callers (e.g. the predict run) can use it
    from values stored in Firestore without loading the full dataset.
    """
    if rh is None or ra is None:
        return None
    hfa = 0 if neutral else _HOME_FIELD_ELO
    diff = (rh + hfa) - ra
    exp_home = 1.0 / (1.0 + 10 ** (-diff / 400.0))

    draw = 0.27 * math.exp(-((diff / 380.0) ** 2))
    draw = max(0.06, min(0.34, draw))
    home_win = max(0.01, exp_home - draw / 2.0)
    away_win = max(0.01, (1.0 - exp_home) - draw / 2.0)
    s = home_win + draw + away_win
    home_win, draw, away_win = home_win / s, draw / s, away_win / s

    supremacy = diff / 400.0
    exp_h = max(0.2, (total_goals + supremacy) / 2.0)
    exp_a = max(0.2, (total_goals - supremacy) / 2.0)
    return {
        "home_win": round(home_win, 4),
        "draw": round(draw, 4),
        "away_win": round(away_win, 4),
        "exp_home_goals": round(exp_h, 3),
        "exp_away_goals": round(exp_a, 3),
        "elo_home": round(rh, 1),
        "elo_away": round(ra, 1),
    }


class IntlData:
    """Loads and serves the international results dataset (lazy, cached)."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    # ------------------------------------------------------------------ #
    #  Loading & caching
    # ------------------------------------------------------------------ #

    def _cache_path(self, name):
        return os.path.join(_CACHE_DIR, name)

    def _fetch_csv(self, url, cache_name):
        """Return CSV text. Use fresh cache if young; else download; on failure
        fall back to any existing (stale) cache. Returns None if all fail."""
        os.makedirs(_CACHE_DIR, exist_ok=True)
        path = self._cache_path(cache_name)

        if os.path.exists(path):
            age = time.time() - os.path.getmtime(path)
            if age < _CACHE_TTL_SECONDS:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read()
                except OSError:
                    pass

        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            text = resp.text
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError as e:
                logger.warning(f"Could not write cache {cache_name}: {e}")
            return text
        except Exception as e:
            logger.warning(f"Download failed for {cache_name} ({e}); trying stale cache.")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read()
                except OSError:
                    pass
            logger.error(f"No data available for {cache_name}.")
            return None

    def load(self, force=False):
        """Load results + goalscorers and compute Elo. Idempotent."""
        if self._loaded and not force:
            return

        self.results = []          # list of played matches (dicts)
        self.elo = {}              # team -> rating
        self._scorer_goals = defaultdict(lambda: defaultdict(int))  # team -> player -> goals (all-time)
        self._scorer_goal_dates = defaultdict(lambda: defaultdict(list))  # team -> player -> [date]
        self._team_match_dates = defaultdict(list)  # team -> [date] (played)
        self._goal_minutes_by_team = defaultdict(list)  # team -> [minute]

        results_text = self._fetch_csv(_RESULTS_URL, "results.csv")
        if results_text:
            self._parse_results(results_text)
            self._compute_elo()
        else:
            logger.error("IntlData: results unavailable — team stats/Elo will be empty.")

        goals_text = self._fetch_csv(_GOALSCORERS_URL, "goalscorers.csv")
        if goals_text:
            self._parse_goalscorers(goals_text)

        self._loaded = True
        logger.info(
            f"IntlData loaded: {len(self.results)} played matches, "
            f"{len(self.elo)} teams rated."
        )

    def _parse_results(self, text):
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            hs, as_ = row.get("home_score"), row.get("away_score")
            if hs in (None, "", "NA") or as_ in (None, "", "NA"):
                continue  # unplayed fixture
            try:
                row["home_score"] = int(hs)
                row["away_score"] = int(as_)
            except ValueError:
                continue
            row["neutral"] = str(row.get("neutral", "")).upper() == "TRUE"
            self.results.append(row)
            self._team_match_dates[row["home_team"]].append(row["date"])
            self._team_match_dates[row["away_team"]].append(row["date"])
        # results.csv is already chronological, but be safe.
        self.results.sort(key=lambda r: r.get("date", ""))

    def _parse_goalscorers(self, text):
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            team = row.get("team")
            scorer = row.get("scorer")
            if not team or not scorer:
                continue
            if str(row.get("own_goal", "")).upper() == "TRUE":
                continue
            self._scorer_goals[team][scorer] += 1
            self._scorer_goal_dates[team][scorer].append(row.get("date", ""))
            self._goal_minutes_by_team[team].append(self._safe_minute(row.get("minute")))

    @staticmethod
    def _safe_minute(m):
        try:
            return int(str(m).split("+")[0])
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------ #
    #  Elo
    # ------------------------------------------------------------------ #

    def _compute_elo(self):
        rating = defaultdict(lambda: 1500.0)
        for r in self.results:
            home, away = r["home_team"], r["away_team"]
            hs, as_ = r["home_score"], r["away_score"]
            k = _TOURNAMENT_WEIGHT.get(r.get("tournament", ""), _DEFAULT_K)

            hfa = 0 if r["neutral"] else _HOME_FIELD_ELO
            r_home = rating[home] + hfa
            r_away = rating[away]

            exp_home = 1.0 / (1.0 + 10 ** ((r_away - r_home) / 400.0))
            if hs > as_:
                w_home = 1.0
            elif hs < as_:
                w_home = 0.0
            else:
                w_home = 0.5

            gd = abs(hs - as_)
            if gd <= 1:
                g = 1.0
            elif gd == 2:
                g = 1.5
            else:
                g = (11 + gd) / 8.0

            delta = k * g * (w_home - exp_home)
            rating[home] += delta
            rating[away] -= delta
        self.elo = dict(rating)

    def get_elo(self, team_name):
        self.load()
        return self.elo.get(to_dataset_name(team_name))

    def match_probabilities(self, home_name, away_name, neutral=True):
        """Elo-based win/draw/loss + expected goals for a fixture.

        Returns dict or None if either team is unrated.
        """
        self.load()
        rh = self.elo.get(to_dataset_name(home_name))
        ra = self.elo.get(to_dataset_name(away_name))
        return elo_match_probs(rh, ra, neutral=neutral)

    # ------------------------------------------------------------------ #
    #  Team rates from recent played matches
    # ------------------------------------------------------------------ #

    def get_team_stats(self, team_name, last_n=12):
        """Attacking/defensive rates and outcome base rates from the team's
        most recent ``last_n`` played matches. Returns {} if no data."""
        self.load()
        ds_name = to_dataset_name(team_name)

        matches = [
            r for r in self.results
            if r["home_team"] == ds_name or r["away_team"] == ds_name
        ]
        if not matches:
            return {}
        matches = matches[-last_n:]

        gf = ga = btts = over15 = over25 = over35 = cs = fts = 0
        wins = draws = losses = 0
        n = len(matches)
        for r in matches:
            is_home = r["home_team"] == ds_name
            scored = r["home_score"] if is_home else r["away_score"]
            conceded = r["away_score"] if is_home else r["home_score"]
            total = r["home_score"] + r["away_score"]
            gf += scored
            ga += conceded
            if r["home_score"] > 0 and r["away_score"] > 0:
                btts += 1
            over15 += total >= 2
            over25 += total >= 3
            over35 += total >= 4
            cs += conceded == 0
            fts += scored == 0
            if scored > conceded:
                wins += 1
            elif scored == conceded:
                draws += 1
            else:
                losses += 1

        return {
            "matches_used": n,
            "avg_goals_scored": round(gf / n, 3),
            "avg_goals_conceded": round(ga / n, 3),
            "btts_rate": round(btts / n, 3),
            "over15_rate": round(over15 / n, 3),
            "over25_rate": round(over25 / n, 3),
            "over35_rate": round(over35 / n, 3),
            "clean_sheet_rate": round(cs / n, 3),
            "failed_to_score_rate": round(fts / n, 3),
            "win_rate": round(wins / n, 3),
            "draw_rate": round(draws / n, 3),
            "loss_rate": round(losses / n, 3),
            "elo": round(self.elo.get(ds_name, 1500.0), 1),
        }

    def get_top_scorers(self, team_name, n=10, window_days=900):
        """Return the team's most prolific recent scorers with anytime-scorer
        rates: [{'name', 'rate'}], for storing in Firestore for player markets."""
        self.load()
        ds_name = to_dataset_name(team_name)
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=window_days)).isoformat()
        recent_counts = {}
        for player, dates in self._scorer_goal_dates.get(ds_name, {}).items():
            c = sum(1 for dt in dates if dt >= cutoff)
            if c > 0:
                recent_counts[player] = c
        top = sorted(recent_counts.items(), key=lambda kv: kv[1], reverse=True)[:n]
        out = []
        for player, _ in top:
            rate = self.player_anytime_scorer_rate(player, team_name, window_days=window_days)
            if rate is not None:
                out.append({"name": player, "rate": rate})
        return out

    def second_half_goal_share(self, team_name):
        """Fraction of a team's goals scored in the 2nd half (>=46'). Default 0.55."""
        self.load()
        mins = [m for m in self._goal_minutes_by_team.get(to_dataset_name(team_name), []) if m is not None]
        if len(mins) < 10:
            return 0.55  # structural prior: 2nd halves see more goals
        second = sum(1 for m in mins if m >= 46)
        return round(second / len(mins), 3)

    # ------------------------------------------------------------------ #
    #  Player scoring rates
    # ------------------------------------------------------------------ #

    def player_anytime_scorer_rate(self, player_name, team_name, window_days=900):
        """Estimate P(player scores) per match from goals in a recent window
        divided by the team's matches in that same window.

        Dividing windowed goals by windowed team matches (rather than all-time
        matches) keeps elite scorers realistic — a regular starter's goals/team
        match approximates goals per appearance. Returns a probability in
        [0.03, 0.85], or None if the player is unknown.
        """
        self.load()
        ds_name = to_dataset_name(team_name)

        dates = self._scorer_goal_dates.get(ds_name, {}).get(player_name)
        if not dates:
            # Loose surname match (markets may use a short/alternate name).
            surname = player_name.split()[-1].lower() if player_name else ""
            for p, d in self._scorer_goal_dates.get(ds_name, {}).items():
                if surname and surname in p.lower():
                    dates = d
                    break
        if not dates:
            return None

        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=window_days)).isoformat()
        recent_goals = sum(1 for dt in dates if dt >= cutoff)
        recent_matches = sum(1 for dt in self._team_match_dates.get(ds_name, []) if dt >= cutoff)

        if recent_goals == 0 or recent_matches < 3:
            # Fall back to a long-window estimate assuming ~70% appearance rate.
            total_goals = self._scorer_goals.get(ds_name, {}).get(player_name, len(dates))
            total_matches = max(1, len(self._team_match_dates.get(ds_name, [])))
            rate = total_goals / total_matches / 0.70
        else:
            rate = recent_goals / recent_matches

        prob_at_least_one = 1.0 - math.exp(-rate)
        return round(max(0.03, min(0.85, prob_at_least_one)), 3)
