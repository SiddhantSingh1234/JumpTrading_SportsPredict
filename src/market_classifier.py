import re
import json
import logging
from src.config import Config

logger = logging.getLogger(__name__)

class MarketClassifier:
    def __init__(self, ai_client=None):
        self.ai = ai_client
        
        self.patterns = {
            "match_result": [r"(?i)will .+ win", r"(?i)will .+ beat", r"(?i)to win the match"],
            "total_goals": [r"(?i)\d+ or more total goals", r"(?i)over .+ goals", r"(?i)\+ goals"],
            "both_teams_score": [r"(?i)both teams score", r"(?i)btts"],
            "half_goals_comparison": [r"(?i)second half.*more.*goals", r"(?i)first half.*more.*goals"],
            "half_specific_goals": [r"(?i)score in the first half", r"(?i)score in the second half"],
            "corners_comparison": [r"(?i)more corners than", r"(?i)corner kick.*more"],
            "corners_threshold": [r"(?i)corner kick", r"(?i)corners"],
            "fouls_comparison": [r"(?i)commit more fouls"],
            "cards_threshold": [r"(?i)card", r"(?i)yellow", r"(?i)red"],
            "offsides_threshold": [r"(?i)offside"],
            "shots_on_target_comparison": [r"(?i)more shots on target than"],
            "shots_on_target_threshold": [r"(?i)shots? on target"],
            "player_goal_assist": [r"(?i)score or assist", r"(?i)score a goal", r"(?i)assist a goal"],
            "player_shot_on_target": [r"(?i)shot on target.*by"],
            "penalty_or_red": [r"(?i)penalty.*red card", r"(?i)penalty kick.*awarded"],
            "first_goal_conditional": [r"(?i)score the first goal"],
        }
        
    def classify(self, market, match_data=None):
        """Classify a single market question using regex only."""
        question = market.get("question_text", "")
        
        # Check compound conditions first
        if " and " in question.lower() or " AND " in question:
            return {"type": "compound_and"}
        if " or " in question.lower() or " OR " in question:
            return {"type": "compound_or"}
            
        # Try regex patterns
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
