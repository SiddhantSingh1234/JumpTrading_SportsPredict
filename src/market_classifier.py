import re
import json
import logging
from src.config import Config

logger = logging.getLogger(__name__)

class MarketClassifier:
    def __init__(self, ai_client=None):
        self.ai = ai_client
        
        # Order matters: more specific patterns first. Player props are checked
        # before team thresholds so "[player] ... shot on target" isn't grabbed
        # by the generic team shots-on-target rule.
        self.patterns = {
            "match_result": [r"(?i)will .+ win the match", r"(?i)will .+ win\b", r"(?i)will .+ beat"],
            "both_teams_score": [r"(?i)both teams (to )?score", r"(?i)\bbtts\b"],
            "half_goals_comparison": [r"(?i)(second|first) half.*more.*goals",
                                       r"(?i)more goals than the (first|second) half"],
            "total_goals": [r"(?i)\d+ or more total goals", r"(?i)\d+ or fewer total goals",
                             r"(?i)over [\d.]+ .*goals", r"(?i)under [\d.]+ .*goals"],
            "half_specific_goals": [r"(?i)score in the (first|second) half"],
            "player_goal_assist": [r"(?i)score or assist", r"(?i)score a goal", r"(?i)assist a goal"],
            "player_shot_on_target": [r"(?i)at least \d+ shot on target", r"(?i)shot on target.*by"],
            "shots_on_target_comparison": [r"(?i)more shots on target than"],
            "shots_on_target_threshold": [r"(?i)shots? on target"],
            "corners_comparison": [r"(?i)more corner kicks? than", r"(?i)more corners than"],
            "corners_threshold": [r"(?i)corner"],
            "fouls_comparison": [r"(?i)more fouls"],
            "penalty_or_red": [r"(?i)penalty.*red card", r"(?i)red card.*penalty", r"(?i)penalty kick.*awarded"],
            "cards_threshold": [r"(?i)\bcards?\b", r"(?i)yellow card", r"(?i)red card"],
            "offsides_threshold": [r"(?i)offside"],
            "first_goal_conditional": [r"(?i)score the first goal"],
        }

    def classify(self, market, match_data=None):
        """Classify a single market question using regex only."""
        question = market.get("question_text", "")
        ql = question.lower()

        # A TRUE compound joins two distinct event clauses. Exclude benign
        # 'or'/'and' phrases that are part of a single market wording
        # (e.g. "3 or more", "2 or fewer", "score or assist", "penalty ... or a red card").
        benign_or = any(p in ql for p in (
            "or more", "or fewer", "or less", "score or assist",
            "or a red card", "red card or", "awarded or"))
        if " and " in ql:
            return {"type": "compound_and"}
        if " or " in ql and not benign_or:
            return {"type": "compound_or"}

        # Try regex patterns (specific -> general).
        for type_name, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, question):
                    return self._extract_entities(type_name, question, match_data)

        return None  # Return None to signal "needs AI"

    def _extract_entities(self, type_name, question, match_data):
        """Extract thresholds or specific halves based on type."""
        result = {"type": type_name}
        
        # Extract number threshold
        numbers = re.findall(r'\b\d+\b', question)
        if numbers:
            result["threshold"] = int(numbers[0])
            
        # Extract half
        if "first half" in question.lower():
            result["half"] = "first"
        elif "second half" in question.lower():
            result["half"] = "second"
            
        return result

    def classify_all(self, markets, match_data=None):
        """Classify a list of markets. Uses regex first, then ONE batched AI call for the rest."""
        unclassified = []
        
        for market in markets:
            classification = self.classify(market, match_data)
            if classification:
                market["classification"] = classification
            else:
                unclassified.append(market)
        
        # Batch AI classification for all unmatched markets in ONE call
        if unclassified and self.ai:
            try:
                questions = {str(m["id"]): m.get("question_text", "") for m in unclassified}
                home = match_data.get("home_team_name", "Team A") if match_data else "Team A"
                away = match_data.get("away_team_name", "Team B") if match_data else "Team B"
                
                prompt = f"""Classify these betting market questions for {home} vs {away}.
For each question, return its type (e.g., match_result, total_goals, both_teams_score, corners_threshold, cards_threshold, player_goal_assist, penalty_or_red, half_specific_goals, half_goals_comparison, fouls_comparison, shots_on_target_threshold, offsides_threshold, first_goal_conditional, unknown) and any parameters like 'threshold' (integer) or 'half' (1 or 2).

Questions:
{json.dumps(questions, indent=2)}

Return strict JSON: a dict mapping each market_id to its classification object. Example: {{"id1": {{"type": "total_goals", "threshold": 3}}, "id2": {{"type": "match_result"}}}}"""
                
                from google.genai import types
                response = self.ai.client.models.generate_content(
                    model=Config.GEMINI_SUMMARY_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                batch_result = json.loads(response.text)
                
                for market in unclassified:
                    mid = str(market["id"])
                    market["classification"] = batch_result.get(mid, {"type": "unknown", "question": market.get("question_text", "")})
                    
            except Exception as e:
                logger.warning(f"Batch AI classification failed: {e}")
                for market in unclassified:
                    market["classification"] = {"type": "unknown", "question": market.get("question_text", "")}
        else:
            # No AI available, mark as unknown
            for market in unclassified:
                market["classification"] = {"type": "unknown", "question": market.get("question_text", "")}
                
        return markets
