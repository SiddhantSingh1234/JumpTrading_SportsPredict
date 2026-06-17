"""The Odds API client (free tier: 500 requests/month).

Fetches bookmaker odds for the World Cup and devigs them into true implied
probabilities for match result / totals / BTTS. These are both a top-quality
signal and our best proxy for the crowd. Optional: inactive unless
``ODDS_API_KEY`` is set. Monthly usage is tracked in Firestore so we stay
under the free cap across the separate GitHub Actions runs.

One ``refresh_all()`` call returns every upcoming event in a single request,
so the whole tournament costs ~1 request per collect cycle.
"""

import logging
from datetime import datetime

import requests

from src.config import Config
from src.team_names import to_canonical

logger = logging.getLogger(__name__)


def _devig(odds_list):
    """Decimal odds -> normalised (vig-free) probabilities, same order."""
    if not odds_list or any(o <= 1.0 for o in odds_list):
        return None
    implied = [1.0 / o for o in odds_list]
    s = sum(implied)
    if s <= 0:
        return None
    return [p / s for p in implied]


class OddsClient:
    def __init__(self, db=None):
        self.db = db
        self.key = Config.ODDS_API_KEY
        self.enabled = bool(self.key)

    # ------------------------------------------------------------------ #

    def _month_key(self):
        return datetime.utcnow().strftime("%Y-%m")

    def _usage(self):
        if not self.db:
            return 0
        try:
            doc = self.db.db.collection("odds_usage").document(self._month_key()).get()
            return int(doc.to_dict().get("count", 0)) if doc.exists else 0
        except Exception:
            return 0

    def _record(self, n=1):
        if not self.db:
            return
        try:
            from firebase_admin import firestore
            self.db.db.collection("odds_usage").document(self._month_key()).set(
                {"count": firestore.Increment(n), "updated_at": datetime.utcnow().isoformat()},
                merge=True,
            )
        except Exception as e:
            logger.warning(f"Could not record odds usage: {e}")

    def _budget_left(self):
        return self._usage() < Config.ODDS_MONTHLY_CAP

    # ------------------------------------------------------------------ #

    def refresh_all(self):
        """One request: devigged probabilities for every upcoming event.

        Returns a list of dicts: {home, away, commence_time, probs:{...}}.
        Empty list if disabled, over budget, or on error.
        """
        if not self.enabled:
            logger.info("Odds API disabled (no ODDS_API_KEY).")
            return []
        if not self._budget_left():
            logger.warning(f"Odds API monthly cap reached ({Config.ODDS_MONTHLY_CAP}).")
            return []

        url = f"{Config.ODDS_API_BASE_URL}/sports/{Config.ODDS_API_SPORT}/odds"
        params = {
            "apiKey": self.key,
            "regions": "uk,eu",
            "markets": "h2h,totals,btts",
            "oddsFormat": "decimal",
        }
        try:
            resp = requests.get(url, params=params, timeout=30)
            self._record(1)  # any successful HTTP round-trip consumes 1 request
            if resp.status_code != 200:
                logger.warning(f"Odds API {resp.status_code}: {resp.text[:160]}")
                return []
            events = resp.json()
        except Exception as e:
            logger.warning(f"Odds API request failed: {e}")
            return []

        out = []
        for ev in events:
            parsed = self._parse_event(ev)
            if parsed:
                out.append(parsed)
        logger.info(f"Odds API: parsed {len(out)} events ({self._usage()}/{Config.ODDS_MONTHLY_CAP} reqs used this month).")
        return out

    def _parse_event(self, ev):
        home = to_canonical(ev.get("home_team", ""))
        away = to_canonical(ev.get("away_team", ""))
        if not home or not away:
            return None

        # Average devigged probs across bookmakers for stability.
        h2h_acc, tot_acc, btts_acc = [], {}, []
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                key = mk.get("key")
                outcomes = mk.get("outcomes", [])
                if key == "h2h":
                    by = {o["name"]: o["price"] for o in outcomes if "price" in o}
                    ho = by.get(ev.get("home_team"))
                    ao = by.get(ev.get("away_team"))
                    do = by.get("Draw")
                    if ho and ao and do:
                        dv = _devig([ho, do, ao])
                        if dv:
                            h2h_acc.append(dv)
                elif key == "totals":
                    # group by point
                    pts = {}
                    for o in outcomes:
                        p = o.get("point")
                        if p is not None and "price" in o:
                            pts.setdefault(p, {})[o["name"].lower()] = o["price"]
                    for p, d in pts.items():
                        if "over" in d and "under" in d:
                            dv = _devig([d["over"], d["under"]])
                            if dv:
                                tot_acc.setdefault(p, []).append(dv[0])  # P(over)
                elif key == "btts":
                    by = {o["name"].lower(): o["price"] for o in outcomes if "price" in o}
                    if "yes" in by and "no" in by:
                        dv = _devig([by["yes"], by["no"]])
                        if dv:
                            btts_acc.append(dv[0])

        probs = {}
        if h2h_acc:
            n = len(h2h_acc)
            probs["home_win"] = round(sum(x[0] for x in h2h_acc) / n, 4)
            probs["draw"] = round(sum(x[1] for x in h2h_acc) / n, 4)
            probs["away_win"] = round(sum(x[2] for x in h2h_acc) / n, 4)
        if tot_acc:
            probs["over"] = {str(p): round(sum(v) / len(v), 4) for p, v in tot_acc.items()}
        if btts_acc:
            probs["btts"] = round(sum(btts_acc) / len(btts_acc), 4)

        if not probs:
            return None
        return {
            "home": home,
            "away": away,
            "commence_time": ev.get("commence_time"),
            "probs": probs,
        }
