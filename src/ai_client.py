import json
import logging
import time
from google import genai
from google.genai import types
from src.config import Config

logger = logging.getLogger(__name__)

# Minimum interval (seconds) between calls for each model, derived from RPM limits.
# gemini-3.5-flash: 10 RPM -> 6s + 1s buffer = 7s
# gemini-3.1-flash-lite: 15 RPM -> 4s + 1s buffer = 5s
# gemma-4-31b-it: 15 RPM -> 4s + 1s buffer = 5s
MODEL_MIN_INTERVALS = {
    "gemini-3.5-flash": 7.0,
    "gemini-3.1-flash-lite": 5.0,
    "gemma-4-31b-it": 5.0,
}

DEFAULT_MIN_INTERVAL = 5.0
MAX_RETRIES = 3
DEFAULT_RETRY_WAIT = 30


class AIClient:
    def __init__(self, api_key):
        self.api_key = api_key
        # Set a 10-minute HTTP timeout — model is allowed to think deeply
        self.client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=600_000)  # 10 minutes in ms
        )
        # Track the last call timestamp per model for rate-limiting.
        self._last_call_time: dict[str, float] = {}

    def _wait_for_rate_limit(self, model: str) -> None:
        """Block until enough time has passed since the last call to this model."""
        min_interval = MODEL_MIN_INTERVALS.get(model, DEFAULT_MIN_INTERVAL)
        last_time = self._last_call_time.get(model, 0.0)
        elapsed = time.time() - last_time
        if elapsed < min_interval:
            wait = min_interval - elapsed
            logger.info(
                f"Rate-limit: waiting {wait:.1f}s before next call to {model}"
            )
            time.sleep(wait)

    def _safe_generate(self, model: str, contents, config=None):
        """Wrapper around generate_content with per-model rate limiting and 429 retry logic.

        1. Enforces a minimum interval between consecutive calls to the same model.
        2. On a 429 (ResourceExhausted) response, reads the Retry-After hint or
           waits a default of 30 seconds, then retries up to MAX_RETRIES times.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            self._wait_for_rate_limit(model)

            try:
                self._last_call_time[model] = time.time()
                kwargs = {"model": model, "contents": contents}
                if config is not None:
                    kwargs["config"] = config
                response = self.client.models.generate_content(**kwargs)
                return response
            except Exception as e:
                error_str = str(e)
                is_rate_limit = (
                    "429" in error_str
                    or "RESOURCE_EXHAUSTED" in error_str.upper()
                    or "rate" in error_str.lower()
                )

                if is_rate_limit and attempt < MAX_RETRIES:
                    # Try to extract a Retry-After value from the error message.
                    retry_after = DEFAULT_RETRY_WAIT
                    try:
                        if hasattr(e, "headers"):
                            ra = e.headers.get("Retry-After") or e.headers.get("retry-after")
                            if ra is not None:
                                retry_after = int(ra)
                        elif "retry-after" in error_str.lower():
                            # Some SDKs embed the header value in the message.
                            import re
                            match = re.search(r"retry.?after[\":\s]*(\d+)", error_str, re.IGNORECASE)
                            if match:
                                retry_after = int(match.group(1))
                    except (ValueError, AttributeError):
                        retry_after = DEFAULT_RETRY_WAIT

                    logger.warning(
                        f"Rate-limited (429) on {model}, attempt {attempt}/{MAX_RETRIES}. "
                        f"Waiting {retry_after}s before retry..."
                    )
                    time.sleep(retry_after)
                    continue
                else:
                    raise

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
            response = self._safe_generate(
                model=Config.GEMINI_SUMMARY_MODEL,
                contents=prompt,
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
            response = self._safe_generate(
                model=Config.GEMINI_STATS_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
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
            response = self._safe_generate(
                model=Config.GEMINI_SUMMARY_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
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
            response = self._safe_generate(
                model=Config.GEMINI_PREDICT_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"AI generate_predictions failed: {e}")
            return []

    def answer_query(self, system_prompt, question, bot1_preds, bot2_preds, match_data, model=None):
        """Query Bot explanation endpoint."""
        if model is None:
            model = Config.QUERY_BOT_MODEL
        logger.info(f"Answering query via AI ({model})...")

        user_prompt = f"Match Data: {json.dumps(match_data)}\nBot 1 Preds: {json.dumps(bot1_preds)}\nBot 2 Preds: {json.dumps(bot2_preds)}\nUser Question: {question}"

        try:
            response = self._safe_generate(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                ),
            )
            return response.text
        except Exception as e:
            logger.error(f"AI answer_query failed: {e}")
            return "Explanation temporarily unavailable due to high AI demand."
