import logging

import numpy as np

from src import dixon_coles, market_model
from src.intl_data import elo_match_probs
from src.team_names import code_to_name

logger = logging.getLogger(__name__)

_LEAGUE_AVG_GOALS = 2.6  # international baseline


class SimulationEngine:
    def __init__(self):
        pass

    def _resolve_names(self, match_data):
        name = match_data.get("name", "")
        if " vs " in name:
            raw_h, raw_a = name.split(" vs ", 1)
        else:
            raw_h = match_data.get("home_team_name", "")
            raw_a = match_data.get("away_team_name", "")
        return code_to_name(raw_h.strip()), code_to_name(raw_a.strip())

    def _lambdas(self, home_team, away_team, elo):
        """Expected goals for each side, blending team rates with Elo supremacy."""
        h = home_team or {}
        a = away_team or {}
        half = _LEAGUE_AVG_GOALS / 2.0

        hg_scored = h.get("avg_goals_scored")
        hg_conceded = h.get("avg_goals_conceded")
        ag_scored = a.get("avg_goals_scored")
        ag_conceded = a.get("avg_goals_conceded")
        have_rates = None not in (hg_scored, hg_conceded, ag_scored, ag_conceded)

        if have_rates:
            home_attack = hg_scored / half
            home_def = hg_conceded / half
            away_attack = ag_scored / half
            away_def = ag_conceded / half
            lam_h = half * home_attack * away_def
            lam_a = half * away_attack * home_def
        else:
            lam_h = lam_a = half

        # Blend with Elo expected goals when available (stabilises sparse data).
        if elo:
            lam_h = 0.5 * lam_h + 0.5 * elo["exp_home_goals"]
            lam_a = 0.5 * lam_a + 0.5 * elo["exp_away_goals"]

        return max(0.15, lam_h), max(0.15, lam_a)

    def simulate_match(self, match_data, home_team_stats, away_team_stats,
                       classified_markets=None, n_sims=20000):
        logger.info(f"Running {n_sims} simulations for match {match_data.get('id')}")
        home_name, away_name = self._resolve_names(match_data)

        elo_h = (home_team_stats or {}).get("elo")
        elo_a = (away_team_stats or {}).get("elo")
        elo = elo_match_probs(elo_h, elo_a, neutral=True) if (elo_h and elo_a) else None

        lam_h, lam_a = self._lambdas(home_team_stats, away_team_stats, elo)

        # Dixon-Coles exact joint score distribution for full-time goal markets.
        dc = dixon_coles.summary(dixon_coles.score_matrix(lam_h, lam_a))

        # Vectorised goal simulation by half.
        f1, f2 = 0.45, 0.55
        hg1 = np.random.poisson(lam_h * f1, n_sims)
        hg2 = np.random.poisson(lam_h * f2, n_sims)
        ag1 = np.random.poisson(lam_a * f1, n_sims)
        ag2 = np.random.poisson(lam_a * f2, n_sims)

        # Peripheral events (corners) via Poisson on team rates / defaults.
        hc = np.random.poisson((home_team_stats or {}).get("avg_corners", 5.0), n_sims)
        ac = np.random.poisson((away_team_stats or {}).get("avg_corners", 5.0), n_sims)

        mc = {
            "home_goals": hg1 + hg2, "away_goals": ag1 + ag2,
            "home_goals_1h": hg1, "away_goals_1h": ag1,
            "home_goals_2h": hg2, "away_goals_2h": ag2,
            "home_corners": hc, "away_corners": ac,
        }

        ctx = {
            "home_name": home_name, "away_name": away_name,
            "home_stats": home_team_stats or {}, "away_stats": away_team_stats or {},
            "elo_probs": elo, "mc": mc, "dc": dc,
            "odds": match_data.get("odds") or {},
        }

        market_probs, market_details = {}, {}
        if classified_markets:
            for m in classified_markets:
                est = market_model.estimate(m, ctx)
                mid = str(m["id"])
                market_probs[mid] = est["prob"]
                market_details[mid] = est

        return {
            "lambdas": {"home": round(lam_h, 3), "away": round(lam_a, 3)},
            "elo_probs": elo,
            "dc": dc,
            "mc_summary": {
                "home_win": float(np.mean(mc["home_goals"] > mc["away_goals"])),
                "draw": float(np.mean(mc["home_goals"] == mc["away_goals"])),
                "away_win": float(np.mean(mc["home_goals"] < mc["away_goals"])),
                "avg_goals": float(np.mean(mc["home_goals"] + mc["away_goals"])),
            },
            "market_probs": market_probs,
            "market_details": market_details,
        }
