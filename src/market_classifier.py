import re
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
        """Classify a single market question."""
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
                    
        # Fallback to AI if patterns fail
        if self.ai:
            try:
                result = self.ai.classify_market(question, match_data)
                return result
            except Exception as e:
                logger.error(f"AI classification failed for '{question}': {e}")
                
        # Ultimate fallback
        return {"type": "unknown", "question": question}

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
            
        # For player markets, we'd extract the player name here
        # E.g. "Will Lionel Messi score?" -> "Lionel Messi"
        # This requires matching against known players for the match
        
        return result

    def classify_all(self, markets, match_data=None):
        """Classify a list of markets."""
        for market in markets:
            classification = self.classify(market, match_data)
            market["classification"] = classification
        return markets
