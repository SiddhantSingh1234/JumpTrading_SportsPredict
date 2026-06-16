import sys
import os
import requests
import json

# Ensure we can import from src
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from src.config import Config

def check_bot_predictions(bot_name, api_key):
    print(f"--- Checking predictions for {bot_name} ---")
    
    if not api_key or api_key == "mock_key_1" or api_key == "mock_key_2":
        print(f"Warning: It looks like your API key for {bot_name} is not set in your .env file.\n")
        return

    url = f"{Config.SPORTSPREDICT_BASE_URL}/predictions"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        print(f"Success! {bot_name} has {len(data)} active predictions registered.")
        
        # Limit output to first 5 so we don't flood the terminal if there are hundreds
        if data:
            print("Showing the first 5 predictions:")
            print(json.dumps(data[:5], indent=2))
            if len(data) > 5:
                print(f"... and {len(data) - 5} more.")
        else:
            print("No predictions found. Have you run the predict phase yet?")
            
    except Exception as e:
        print(f"Error fetching predictions: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"API Response: {e.response.text}")
            
    print("\n")

if __name__ == "__main__":
    check_bot_predictions("Bot 1", Config.BOT1_KEY)
    check_bot_predictions("Bot 2", Config.BOT2_KEY)
