import json
import logging
from google import genai
from google.genai import types
from src.config import Config

logger = logging.getLogger(__name__)

class AIClient:
    def __init__(self, api_key):
        self.api_key = api_key
        # Initialize Google GenAI client
        self.client = genai.Client(api_key=self.api_key)
        
    def summarize_news(self, headlines, previous_briefing, match_data):
        """Use Flash Lite to summarize news into a concise briefing."""
        logger.info("Summarizing news via AI...")
        prompt = f"""You are a sports intelligence analyst.
Match: {match_data.get('home_team_name')} vs {match_data.get('away_team_name')}
Previous Briefing: {previous_briefing}
New Headlines:
{json.dumps(headlines, indent=2)}

Synthesize the new headlines with the previous briefing. Extract key injuries, lineup changes, and critical context. Keep it under 200 words."""
        
        try:
            response = self.client.models.generate_content(
                model=Config.GEMINI_SUMMARY_MODEL,
                contents=prompt
            )
            return response.text
        except Exception as e:
            logger.warning(f"AI summarize_news failed (likely high demand): {e}")
            return "News briefing temporarily unavailable."

    def extract_stats(self, headlines, match_data):
        """Use Gemma to extract structured JSON stats from news."""
        logger.info("Extracting structured stats via AI...")
        prompt = f"""Extract structured statistical data and injury info from these headlines for {match_data.get('home_team_name')} vs {match_data.get('away_team_name')}.
Headlines: {json.dumps(headlines, indent=2)}
Output strict JSON format. You MUST aggressively hunt for any mention of corners, fouls, cards, red cards, penalties, shots, or shots on target. Example: {{"injuries": ["player X"], "recent_corners": 5, "recent_yellow_cards": 2, "recent_red_cards": 0, "recent_fouls": 11, "recent_shots": 12, "recent_shots_on_target": 4, "recent_penalties": 1}}"""
        
        try:
            response = self.client.models.generate_content(
                model=Config.GEMINI_STATS_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            return json.loads(response.text)
        except Exception as e:
            logger.warning(f"AI extract_stats failed: {e}")
            return {}

    def classify_market(self, question, match_data):
        """Fallback classifier using Flash Lite."""
        logger.info(f"Classifying market via AI: {question}")
        prompt = f"""Classify the following betting market question for the match {match_data.get('home_team_name')} vs {match_data.get('away_team_name')}.
Question: {question}
Return strict JSON with 'type' (e.g., match_result, total_goals, player_goal) and any parameters like 'threshold' (integer) or 'half' (1 or 2)."""

        try:
            response = self.client.models.generate_content(
                model=Config.GEMINI_SUMMARY_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            return json.loads(response.text)
        except Exception as e:
            logger.warning(f"AI classify_market failed: {e}")
            return {"type": "unknown", "question": question}

    def generate_predictions(self, system_prompt, prompt_data):
        """Generate final predictions using Flash 3.5."""
        logger.info("Generating final predictions via AI...")
        
        user_prompt = f"Data context:\n{json.dumps(prompt_data, indent=2)}\n\nGenerate predictions strictly as a JSON array of objects with 'market_id' (string) and 'probability' (integer 1-99)."
        
        try:
            response = self.client.models.generate_content(
                model=Config.GEMINI_PREDICT_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json"
                )
            )
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"AI generate_predictions failed: {e}")
            return []

    def answer_query(self, system_prompt, question, bot1_preds, bot2_preds, match_data, model=Config.QUERY_BOT_MODEL):
        """Query Bot explanation endpoint."""
        logger.info(f"Answering query via AI ({model})...")
        
        user_prompt = f"Match Data: {json.dumps(match_data)}\nBot 1 Preds: {json.dumps(bot1_preds)}\nBot 2 Preds: {json.dumps(bot2_preds)}\nUser Question: {question}"
        
        try:
            response = self.client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt
                )
            )
            return response.text
        except Exception as e:
            logger.error(f"AI answer_query failed: {e}")
            return "Explanation temporarily unavailable due to high AI demand."
