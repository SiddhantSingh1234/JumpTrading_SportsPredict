import numpy as np
from scipy.stats import poisson, nbinom
import logging

logger = logging.getLogger(__name__)

class SimulationEngine:
    def __init__(self):
        pass
        
    def _calculate_params(self, home_team, away_team):
        """Calculate expected event rates (λ) for a match."""
        # Defaults if no team data
        if not home_team or not away_team:
            return {
                "lambda_home_goals": 1.2, "lambda_away_goals": 1.2,
                "lambda_home_corners": 5.0, "lambda_away_corners": 5.0,
                "lambda_home_fouls": 12.0, "lambda_away_fouls": 12.0,
                "lambda_home_cards": 2.0, "lambda_away_cards": 2.0,
                "lambda_home_shots": 12.0, "lambda_away_shots": 12.0,
                "lambda_home_sot": 4.0, "lambda_away_sot": 4.0,
                "lambda_home_offsides": 2.0, "lambda_away_offsides": 2.0,
            }

        league_avg_goals = 2.5
        
        # Protect against div by zero or missing data
        hg_scored = home_team.get("avg_goals_scored", 1.25)
        hg_conceded = home_team.get("avg_goals_conceded", 1.25)
        ag_scored = away_team.get("avg_goals_scored", 1.25)
        ag_conceded = away_team.get("avg_goals_conceded", 1.25)

        home_attack = hg_scored / (league_avg_goals / 2)
        home_defense = hg_conceded / (league_avg_goals / 2)
        away_attack = ag_scored / (league_avg_goals / 2)
        away_defense = ag_conceded / (league_avg_goals / 2)
        
        neutral_factor = 1.05  # slight advantage for "designated home"
        
        lambda_home = (league_avg_goals / 2) * home_attack * away_defense * neutral_factor
        lambda_away = (league_avg_goals / 2) * away_attack * home_defense
        
        return {
            "lambda_home_goals": lambda_home,
            "lambda_away_goals": lambda_away,
            "lambda_home_corners": home_team.get("avg_corners", 5.0),
            "lambda_away_corners": away_team.get("avg_corners", 5.0),
            "lambda_home_fouls": home_team.get("avg_fouls_committed", 12.0),
            "lambda_away_fouls": away_team.get("avg_fouls_committed", 12.0),
            "lambda_home_cards": home_team.get("avg_yellow_cards", 2.0) + home_team.get("avg_red_cards", 0.1),
            "lambda_away_cards": away_team.get("avg_yellow_cards", 2.0) + away_team.get("avg_red_cards", 0.1),
            "lambda_home_shots": home_team.get("avg_shots", 12.0),
            "lambda_away_shots": away_team.get("avg_shots", 12.0),
            "lambda_home_sot": home_team.get("avg_shots_on_target", 4.0),
            "lambda_away_sot": away_team.get("avg_shots_on_target", 4.0),
            "lambda_home_offsides": home_team.get("avg_offsides", 2.0),
            "lambda_away_offsides": away_team.get("avg_offsides", 2.0),
        }

    def _simulate_single_match(self, params):
        """Simulate one match: generate events per half."""
        FIRST_HALF_FRACTION = 0.45
        SECOND_HALF_FRACTION = 0.55
        
        # Goals (Poisson)
        hg_1h = np.random.poisson(params["lambda_home_goals"] * FIRST_HALF_FRACTION)
        hg_2h = np.random.poisson(params["lambda_home_goals"] * SECOND_HALF_FRACTION)
        ag_1h = np.random.poisson(params["lambda_away_goals"] * FIRST_HALF_FRACTION)
        ag_2h = np.random.poisson(params["lambda_away_goals"] * SECOND_HALF_FRACTION)
        
        # Helper for NegBinom
        def negbinom_draw(mean, fraction):
            if mean <= 0: return 0
            dispersion = 1.5
            p = 1 / dispersion
            r = (mean * fraction) * p / (1 - p)
            return np.random.negative_binomial(r, p)
            
        return {
            "home_goals": hg_1h + hg_2h, "away_goals": ag_1h + ag_2h,
            "home_goals_1h": hg_1h, "away_goals_1h": ag_1h,
            "home_goals_2h": hg_2h, "away_goals_2h": ag_2h,
            
            "home_corners": negbinom_draw(params["lambda_home_corners"], 1.0),
            "away_corners": negbinom_draw(params["lambda_away_corners"], 1.0),
            "home_cards": negbinom_draw(params["lambda_home_cards"], 1.0),
            "away_cards": negbinom_draw(params["lambda_away_cards"], 1.0),
            
            "penalty_awarded": np.random.random() < 0.15,
            "red_card_shown": np.random.random() < 0.05
        }

    def simulate_match(self, match_data, home_team_stats, away_team_stats, classified_markets=None, n_sims=10000):
        """Run 10K Monte Carlo simulations."""
        logger.info(f"Running {n_sims} simulations for match {match_data.get('id')}")
        
        params = self._calculate_params(home_team_stats, away_team_stats)
        
        results = {
            "home_goals": np.zeros(n_sims, dtype=int),
            "away_goals": np.zeros(n_sims, dtype=int),
            "home_goals_1h": np.zeros(n_sims, dtype=int),
            "away_goals_1h": np.zeros(n_sims, dtype=int),
            "home_goals_2h": np.zeros(n_sims, dtype=int),
            "away_goals_2h": np.zeros(n_sims, dtype=int),
            "home_corners": np.zeros(n_sims, dtype=int),
            "away_corners": np.zeros(n_sims, dtype=int),
            "home_cards": np.zeros(n_sims, dtype=int),
            "away_cards": np.zeros(n_sims, dtype=int),
            "penalty_awarded": np.zeros(n_sims, dtype=bool),
            "red_card_shown": np.zeros(n_sims, dtype=bool),
        }
        
        for i in range(n_sims):
            sim = self._simulate_single_match(params)
            for k, v in sim.items():
                results[k][i] = v
                
        # Calculate specific market probabilities if classified markets are provided
        market_probs = {}
        if classified_markets:
            for market in classified_markets:
                prob = self._extract_market_probability(market, results, params)
                market_probs[str(market["id"])] = prob
                
        return {
            "params": params,
            "mc_summary": {
                "home_win": float(np.mean(results["home_goals"] > results["away_goals"])),
                "draw": float(np.mean(results["home_goals"] == results["away_goals"])),
                "away_win": float(np.mean(results["home_goals"] < results["away_goals"])),
                "avg_goals": float(np.mean(results["home_goals"] + results["away_goals"]))
            },
            "market_probs": market_probs
        }

    def _extract_market_probability(self, market, mc_results, params):
        """Extract probability for a specific market type."""
        cls = market.get("classification", {})
        mtype = cls.get("type", "unknown")
        
        # Default fallback
        prob = 0.50
        
        if mtype == "match_result":
            prob = np.mean(mc_results["home_goals"] > mc_results["away_goals"]) # Simplified
        elif mtype == "total_goals":
            threshold = cls.get("threshold", 3)
            totals = mc_results["home_goals"] + mc_results["away_goals"]
            prob = np.mean(totals >= threshold)
        elif mtype == "both_teams_score":
            prob = np.mean((mc_results["home_goals"] > 0) & (mc_results["away_goals"] > 0))
        elif mtype == "corners_threshold":
            threshold = cls.get("threshold", 10)
            totals = mc_results["home_corners"] + mc_results["away_corners"]
            prob = np.mean(totals >= threshold)
            
        # Clamp to 0.01 - 0.99
        return max(0.01, min(0.99, float(prob)))
