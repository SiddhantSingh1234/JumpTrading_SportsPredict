import json
import logging
from src.config import Config

logger = logging.getLogger(__name__)

class Predictor:
    def __init__(self, ai_client):
        self.ai = ai_client
        
    def predict(self, bot_number, sim_results, news, structured_news, classified_markets, match_data):
        """Generate predictions for a specific bot."""
        logger.info(f"Generating predictions for Bot {bot_number} (Match {match_data.get('id')})")
        
        # We need to construct a prompt depending on whether it's Bot 1 or Bot 2
        # For this implementation, we simulate the AI logic if an AI client isn't fully integrated,
        # but the actual prompt structure matches the implementation plan.
        
        system_prompt = self._get_bot_system_prompt(bot_number)
        
        # Build prompt context
        stage = match_data.get("stage", "group")
        stage_weight = {"group": 1, "knockout": 2, "final": 3}.get(stage, 1)
        
        prompt_data = {
            "stage": stage,
            "stage_weight": stage_weight,
            "team_a": match_data.get("home_team_name", "Team A"),
            "team_b": match_data.get("away_team_name", "Team B"),
            "sim_results": sim_results.get("market_probs", {}),
            "news_briefing": news,
            "structured_news": structured_news,
            "markets": [{"id": m.get("id"), "text": m.get("question_text") or m.get("question") or m.get("text", "")} for m in classified_markets]
        }
        
        if self.ai:
            try:
                # Ask Gemini 3.5 Flash
                response = self.ai.generate_predictions(system_prompt, prompt_data)
                return self._validate_and_clamp(response, classified_markets)
            except Exception as e:
                logger.error(f"AI Prediction failed for Bot {bot_number}: {e}")
        
        # Fallback logic if AI fails or isn't provided
        return self._fallback_predictions(bot_number, sim_results, classified_markets)

    def _get_bot_system_prompt(self, bot_number):
        if bot_number == 1:
            return """You are Bot 1: THE CALIBRATED BASELINE (Smart Money Consensus).
Your absolute and sole objective is to MAXIMIZE RELATIVE BRIER POINT (RBP) in the Jump Trading Probability Cup.
RBP is calculated as: (crowd_brier - user_brier) * 100. Because Brier scoring is quadratic, extreme overconfidence (probabilities near 1 or 99) carries a massive, exponential penalty if wrong. 

You must act as the ultimate analytical machine. Before generating any probability, you must perform a deep, exhaustive analysis:
1. QUANTITATIVE ANCHOR: Review the Monte Carlo simulation probabilities. CRITICAL RULE: The system uses a hardcoded fallback baseline of exactly 1.5 Goals Scored and 1.0 Goals Conceded for teams with no recent match data. If you detect that a team's stats perfectly match this 1.5/1.0 baseline, the math engine is currently blind—you MUST rely almost entirely on the qualitative News Briefing. If their stats deviate from 1.5/1.0, it means real World Cup data is flowing in. As the tournament progresses and stats deviate, dynamically shift your weight back to trusting the quantitative simulation math.
2. QUALITATIVE OVERLAY: Thoroughly analyze the provided structured stats, injury reports, confirmed lineups, and the news briefing. Give massive weightage to this breaking news if the math is locked to the baseline.
3. CONTEXTUAL WEIGHTING: Consider the tournament stage. Group stages (1x weight) see more rotation; Knockouts (2x) and Finals (3x) see tighter, more defensive football.
4. CALIBRATION: Aggressively adjust the baseline simulation probability using your qualitative news findings. If the news shows a star striker is injured or a team is resting players, heavily discount the simulation's predictions.
5. RISK MANAGEMENT: You represent the smart consensus. Generally, keep your probabilities between 15 and 85 to minimize Brier penalty risk. Note the competition scoring rules: Knockout matches have a 2x point weightage, and the Final has a 3x point weightage. For these high-stakes matches, the massive upside for a correct prediction is matched only by the drastically multiplied Brier penalties for extreme overconfidence. Be incredibly careful with your probability spreads, but do not be afraid to capitalize on the huge upside if the math and news strongly align.

Output your final prediction as a strict JSON list of objects containing 'market_id' and 'probability' (must be an integer from 1 to 99).

TIME CONSTRAINT: You have up to 15 minutes to think, but aim to complete your analysis and output your final JSON within 12 minutes. Think as deeply as you need to — consider every angle, every data point, every edge — but once you've done your analysis, commit to your numbers and output the JSON."""
        else:
            return """You are Bot 2: THE EDGE HUNTER (Contrarian Value Seeker).
Your absolute and sole objective is to MAXIMIZE RELATIVE BRIER POINT (RBP) by exploiting crowd bias and finding hidden value.
RBP rewards you heavily when you are correct and the crowd is wrong. The crowd is often heavily influenced by recency bias, public narratives, and star player popularity, while ignoring tactical mismatches or systemic flaws.

You must perform extensive, multi-layered research before predicting:
1. IDENTIFY THE CROWD: Read the news briefing and standard simulations. Note that the "average" bettor will blindly follow the simulation math, even when it is just guessing.
2. FIND THE EDGE: Dig deep into the structured stats. CRITICAL RULE: Our system uses a hardcoded fallback of 1.5 Goals Scored and 1.0 Conceded. If a team's stats match this 1.5/1.0 baseline exactly, the simulation is completely blind. If so, your absolute greatest edge lies in exploiting the breaking news and lineup rotations. If their stats deviate from 1.5/1.0, real tournament data has arrived; you must adapt and start blending the true simulation math back into your edge strategy as the tournament progresses.
3. FORMULATE THESIS: Build a specific, data-backed thesis for why the simulation math or crowd is slightly wrong based on current team news or true math divergence.
4. EXECUTE EDGE: Push your probability aggressively (but intelligently) away from the simulation and in the direction of the news. If the math says 60% but the news shows they are playing a backup goalkeeper, push it to 40% or 30%.
5. CALIBRATION & SCORING WEIGHTS: You take more calculated risks than Bot 1 to maximize the RBP spread, but you still respect the Brier penalty. Avoid 1 or 99. The competition rules state Knockouts have a 2x weightage and the Final has a 3x weightage. In these matches, the reward for a correct contrarian prediction is astronomical, but the Brier penalties for being wrong are massively amplified. You must balance your contrarian edge with absolute precision to capture this huge upside when the stakes are 2x or 3x. Keep probabilities strictly integer 1 to 99.

Output your final prediction as a strict JSON list of objects containing 'market_id' and 'probability' (must be an integer from 1 to 99).

TIME CONSTRAINT: You have up to 15 minutes to think, but aim to complete your analysis and output your final JSON within 12 minutes. Think as deeply as you need to — consider every angle, every data point, every edge — but once you've done your analysis, commit to your numbers and output the JSON."""

    def _validate_and_clamp(self, predictions, markets):
        """Ensure predictions are 1-99 and all markets are covered."""
        valid_preds = []
        market_ids = {str(m["id"]) for m in markets}
        
        for p in predictions:
            mid = str(p.get("market_id"))
            if mid in market_ids:
                prob = p.get("probability", 50)
                # Clamp between 1 and 99
                prob = max(Config.PROBABILITY_MIN, min(Config.PROBABILITY_MAX, int(prob)))
                p["probability"] = prob
                valid_preds.append(p)
                market_ids.remove(mid)
                
        # Fill in missing markets with a default 50%
        for missing_mid in market_ids:
            valid_preds.append({
                "market_id": missing_mid,
                "probability": 50,
                "reasoning": "Fallback prediction."
            })
            
        return valid_preds

    def _fallback_predictions(self, bot_number, sim_results, markets):
        """Fallback prediction generator based entirely on simulation math."""
        logger.warning(f"Using fallback predictions for Bot {bot_number}.")
        preds = []
        market_probs = sim_results.get("market_probs", {})
        
        for m in markets:
            mid = str(m["id"])
            raw_prob = market_probs.get(mid, 0.5)
            
            if bot_number == 2:
                # Bot 2 tries to be edgy: push away from 0.5 slightly
                if raw_prob > 0.5:
                    raw_prob += 0.03
                else:
                    raw_prob -= 0.03
            
            prob_int = int(raw_prob * 100)
            prob_int = max(Config.PROBABILITY_MIN, min(Config.PROBABILITY_MAX, prob_int))
            
            preds.append({
                "market_id": mid,
                "probability": prob_int,
                "math_baseline": int(raw_prob * 100),
                "reasoning": "Mathematical baseline from Monte Carlo simulation."
            })
        return preds
