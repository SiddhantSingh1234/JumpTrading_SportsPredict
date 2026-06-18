import logging

from src import calibration as calibration_lib
from src.config import Config

logger = logging.getLogger(__name__)


class Predictor:
    """Turns model probabilities + news into final 1-99 submissions.

    The quantitative model (engine + market_model) already produces an informed
    probability for every market. The AI's job is to *adjust* those for
    qualitative factors (injuries, confirmed lineups, motivation, rotation),
    NOT to invent numbers. If the AI is unavailable or returns nothing, we fall
    back to the model probabilities — never to a blanket 50.
    """

    def __init__(self, ai_client):
        self.ai = ai_client

    def predict(self, bot_number, sim_results, news, structured_news,
                classified_markets, match_data, crowd_sentiment=None, calibration=None):
        logger.info(f"Generating Bot {bot_number} predictions (match {match_data.get('id')})")

        market_probs = sim_results.get("market_probs", {}) or {}
        market_details = sim_results.get("market_details", {}) or {}

        stage = match_data.get("stage", "group")
        stage_weight = {"group": 1, "knockout": 2, "final": 3}.get(stage, 1)

        markets_for_prompt = []
        for m in classified_markets:
            mid = str(m.get("id"))
            model_p = market_probs.get(mid, 0.5)
            det = market_details.get(mid, {})
            markets_for_prompt.append({
                "market_id": mid,
                "question": m.get("question_text") or m.get("question") or m.get("text", ""),
                "model_probability": int(round(model_p * 100)),
                "model_source": det.get("source", "model"),
                "model_confidence": det.get("confidence", "med"),
            })

        prompt_data = {
            "match": match_data.get("name", "Match"),
            "stage": stage,
            "stage_weight": stage_weight,
            "elo_probs": sim_results.get("elo_probs"),
            "news_briefing": news or "",
            "structured_news": structured_news or {},
            "crowd_sentiment": crowd_sentiment or {},
            "markets": markets_for_prompt,
        }

        stance = Config.COMPETITION_STANCE
        prompt_data["competition_stance"] = stance
        logger.info(f"Bot {bot_number} competition stance: {stance}")

        ai_preds = []
        if self.ai:
            try:
                system_prompt = self._system_prompt(bot_number) + self._stance_clause(stance)
                ai_preds = self.ai.generate_predictions(system_prompt, prompt_data) or []
            except Exception as e:
                logger.error(f"AI prediction failed for Bot {bot_number}: {e}")
                ai_preds = []

        return self._merge(ai_preds, classified_markets, market_probs, calibration)

    # ------------------------------------------------------------------ #

    def _merge(self, ai_preds, markets, market_probs, calibration=None):
        """Use the AI value where valid; otherwise fall back to the model
        probability. Then recalibrate (Tier 5) using the learned map. Never
        blanket 50."""
        ai_by_id = {}
        for p in ai_preds or []:
            mid = str(p.get("market_id"))
            prob = p.get("probability")
            try:
                prob = int(round(float(prob)))
            except (TypeError, ValueError):
                continue
            ai_by_id[mid] = prob

        out = []
        ai_used = model_used = recal = 0
        for m in markets:
            mid = str(m["id"])
            if mid in ai_by_id:
                prob = ai_by_id[mid]
                source = "ai"
                ai_used += 1
            else:
                model_p = market_probs.get(mid, 0.5)
                prob = int(round(model_p * 100))
                source = "model_fallback"
                model_used += 1

            # Recalibrate using the learned reliability map for this category.
            if calibration:
                mtype = (m.get("classification") or {}).get("type", "unknown")
                cat = calibration_lib.category_for(mtype)
                new_p01 = calibration_lib.apply(prob / 100.0, cat, calibration)
                new_prob = int(round(new_p01 * 100))
                if new_prob != prob:
                    recal += 1
                prob = new_prob

            prob = max(Config.PROBABILITY_MIN, min(Config.PROBABILITY_MAX, prob))
            out.append({"market_id": mid, "probability": prob, "source": source})

        logger.info(f"Predictions merged: {ai_used} AI, {model_used} model fallback, {recal} recalibrated.")
        return out

    def _stance_clause(self, stance):
        if stance == "climb":
            return ("\n\nSTANCE: We are TRAILING on the leaderboard. On your HIGHEST-CONVICTION "
                    "edges, take a little more variance (push further from 50 when the model and "
                    "news strongly agree) to climb — but never on weak signals or in high-weight "
                    "matches (knockout = 2x points, final = 3x points), where being wrong is "
                    "penalised 2-3x.")
        if stance == "defend":
            return ("\n\nSTANCE: We are LEADING. Play conservatively — hug the model/consensus and "
                    "avoid extreme positions to lock in the lead.")
        return ""

    # ------------------------------------------------------------------ #

    def _system_prompt(self, bot_number):
        common = (
            "You are predicting binary (yes/no) markets on FIFA World Cup 2026 matches for the "
            "Jump Trading Probability Cup. Scoring is Relative Brier Points: "
            "RBP = (crowd_brier - your_brier) * 100. You are scored AGAINST THE CROWD "
            "(casual humans + generic AI bots), and you CANNOT see the crowd's prices.\n\n"
            "KEY FACTS:\n"
            "- Brier is a strictly proper scoring rule: your best score comes from submitting your "
            "HONEST calibrated probability. Do NOT artificially compress toward 50, and do NOT inflate "
            "toward extremes. Report what you actually believe.\n"
            "- Each market comes with a MODEL_PROBABILITY computed from a quantitative engine "
            "(Elo ratings, real national-team scoring rates, Monte-Carlo goal simulation, and "
            "structural base rates) plus a confidence tag. TREAT THIS AS YOUR ANCHOR.\n"
            "- Your job is to ADJUST the model probability for qualitative factors the model does not "
            "see: confirmed lineups, injuries/suspensions, rest/rotation, motivation (already-qualified "
            "teams), weather, and clearly stale model data. If the news says nothing relevant, stay close "
            "to the model probability.\n"
            "- model_confidence tells you how much signal the MODEL has: 'high' = goal-based "
            "Monte-Carlo / bookmaker odds — trust it strongly and move it little. 'med'/'low' = a thin or "
            "base-rate prior, which usually means the MARKET ITSELF is hard or near-random — do NOT read "
            "low confidence as licence to be bold; default to the model unless you have specific, nameable "
            "information.\n"
            "- CRITICAL — forecast only what you can actually know. You add real value where you have "
            "genuine knowledge: match result, total goals, both-teams-to-score, a named player's role / "
            "goal or shot threat, and team-style or referee effects on cards, fouls and corners. But many "
            "markets are NEAR-RANDOM and unforecastable — exact OFFSIDE counts, precise corner/shot "
            "tallies, and fine-grained HALF-BY-HALF comparisons (e.g. 'more goals in the 2nd half than the "
            "1st', 'more shots on target in the 2nd half than the opponent', 'tied at halftime'). No one "
            "can predict these; the MODEL_PROBABILITY (a calibrated base rate) is genuinely the best "
            "estimate. On such markets STAY WITHIN A FEW POINTS OF THE MODEL unless you can name a concrete "
            "reason (a known offside-trap defence, a high-corner pressing style, a card-happy referee). "
            "Inventing confidence on a coin-flip is the single biggest way to LOSE Relative Brier Points, "
            "because Brier penalises being confident-and-wrong quadratically.\n"
            "- Where you DO have information, USE IT — especially for GOAL and SHOT markets. A team's "
            "attacking strength, recent goal-scoring form, and the availability of its key attackers heavily "
            "drive total goals, team-to-score, half-specific scoring, and shots-on-target. The MODEL_PROBABILITY "
            "is built mainly from past goal rates and Elo; it does NOT know current attacking form or who is "
            "fit. So if the news / sentiment shows a team in strong (or poor) attacking form, missing or "
            "returning a key striker or creator, playing an open high-tempo style vs a deep defensive block, "
            "or a clear pattern of scoring late (2nd-half) or early — SHIFT the relevant goal/shot "
            "probabilities accordingly. For example: raise a side's 2nd-half scoring / shots if they finish "
            "matches strongly or will be chasing the game, and lower them if their main scorer is out, the "
            "opponent defends deep, or they are already qualified and likely to rest players. These attack/"
            "defence reads are exactly the qualitative edge the model cannot see — lean on them confidently.\n"
            "- For PLAYER markets (will [player] score or assist / have a shot on target), the FIRST thing to "
            "check is the confirmed STARTING LINEUP from the news/sentiment. A player who is benched, injured, "
            "suspended or not selected cannot shoot or score — drop the probability sharply (low single digits "
            "if confirmed out, low-teens for a likely bench/rotation risk). Only if the player is confirmed (or "
            "very likely) STARTING should you use the model's player rate as the anchor, then adjust for their "
            "role (first-choice striker / penalty-taker / creator vs a defender or holding midfielder), recent "
            "form, and how the opponent defends — a key attacker starting against a weak defence raises it; a "
            "rotation risk or deep-defending opponent lowers it. Never leave a player market near the model "
            "default if the lineup news contradicts it but properly verify if the lineup news contradicts the model "
            "and only then change to an appropriate extent. Do not overestimate the impact of any single piece of information.\n"
            "- Stage weight matters: knockout = 2x, final = 3x. In high-weight matches the Brier penalty "
            "for being wrong is multiplied, so be more conservative with extreme values there.\n"
            "- Only 1-99 is allowed. Reserve values below 8 or above 92 for genuine near-certainties.\n\n"
            "OUTPUT: a strict JSON array; one object per market with 'market_id' (string) and "
            "'probability' (integer 1-99). Include every market_id you were given."
        )
        if bot_number == 1:
            role = (
                "ROLE: CALIBRATED / MODEL-ANCHORED. Stay disciplined and close to the model probability, "
                "nudging only for concrete news. You are the well-calibrated baseline whose edge is being "
                "better calibrated than a careless crowd. On near-random markets (offside/corner/shot counts, "
                "half-by-half comparisons) your discipline IS the edge — default to the model there and spend "
                "your adjustments on the goal, result and player markets where you actually have information.\n\n"
            )
        else:
            role = (
                "ROLE: CROWD-DIVERGENCE / CONTRARIAN. Your edge is fading PREDICTABLE crowd bias. Use the "
                "CROWD_SENTIMENT data (Reddit public lean, hype, betting consensus) when present, plus these "
                "rules: (1) the crowd over-rates star players and big nations -> fade hype on player props and "
                "favorites when the model disagrees; (2) the crowd over-prices compound 'A AND B' markets -> "
                "shade those DOWN toward the true (lower) joint probability; (3) on name-anchored coin-flips "
                "(e.g. 'more 2nd-half corners/shots than the other team') the crowd drifts to the famous side "
                "-> pull toward the model/base rate. Diverge from the crowd only where you have a real reason; "
                "otherwise match the model. Respect the multiplied Brier penalty in 2x/3x matches.\n"
                "IMPORTANT: contrarian does NOT mean overconfident. Your divergence must target an "
                "IDENTIFIABLE bias (hype, compound over-pricing, name-anchoring) — never a random count "
                "market. On offside counts, exact corner/shot tallies and half-split comparisons you have NO "
                "edge over the model, so match it; bold numbers there just bleed Brier points.\n\n"
            )
        return role + common
