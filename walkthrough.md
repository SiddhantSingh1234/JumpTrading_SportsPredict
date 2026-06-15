# Probability Cup AI: Implementation Walkthrough

The codebase is now fully implemented according to the v6 architecture plan. The system is 100% serverless, fully automated via GitHub Actions, and operates completely within free-tier limits.

## 🏗️ Architecture Overview

The system is split into two independent parts:
1. **The Daemon (GitHub Actions)**: Runs automatically on schedules.
2. **The Query Bot (Local)**: Runs on your PC when you want to ask questions.

Both connect to the same **Firebase Firestore** database to stay perfectly synchronized.

## 📁 File Structure

- `.github/workflows/`: Contains the 4 cron/manual triggers.
- `src/database.py`: Connects to Firebase Firestore.
- `src/collector.py` & `src/news_scraper.py`: Handle the 2-phase data fetch (extensive vs. quick refresh).
- `src/engine.py` & `src/market_classifier.py`: The Poisson/NegBinom/MonteCarlo engine and regex-first classifiers.
- `src/predictor.py`: Generates the Bot 1 (Calibrated Baseline) and Bot 2 (Edge Hunter) probabilities.
- `src/submitter.py`: SportsPredict API client with retry logic.
- `src/calibrator.py`: Daily calibration analysis.
- `src/main.py`: The CLI entry point used by GitHub Actions.
- `src/query_bot.py`: The local FastAPI server for your questions.
- `src/bootstrap.py`: One-time script to populate the initial database.

## 🚀 How to Run It

To bring this system online, follow these final manual setup steps:

### 1. Set Up Firebase (One-Time)
1. Go to [Firebase Console](https://console.firebase.google.com/), create a new project.
2. Add a Firestore Database (start in Production mode, choose a region near you).
3. Go to Project Settings -> Service Accounts -> "Generate new private key".
4. Save the downloaded JSON file as `firebase-credentials.json` in your local project folder (this is already ignored by `.gitignore`).

### 2. Run Bootstrap Locally
Before pushing to GitHub, you need to populate the initial baseline stats for the 48 teams.
```bash
# In your terminal
pip install -r requirements.txt
python src/bootstrap.py
```
> You only ever need to run this once!

### 3. Deploy to GitHub
1. Create a **Private Repository** on GitHub and push your code.
2. Go to the repository's **Settings -> Secrets and variables -> Actions**.
3. Add the following **New repository secrets**:
   - `SPORTSPREDICT_BOT1_KEY`
   - `SPORTSPREDICT_BOT2_KEY`
   - `GEMINI_API_KEY`
   - `API_FOOTBALL_KEY`
   - `FOOTBALL_DATA_KEY`
   - `FIREBASE_CREDENTIALS` (Paste the *entire contents* of your `firebase-credentials.json` file here)

### 4. Let it Run!
Once the secrets are in place, the GitHub Actions will automatically take over based on the schedule we defined:
- Extensive collection every 6 hours.
- Prediction pipeline every 30 minutes (checking for T-45min).
- Calibration daily at midnight.

You can also go to the **Actions** tab in your GitHub repository, click "Manual Trigger", and manually force a run anytime.

### 5. Using the Query Bot
When you want to check in on the system, run the local Query Bot:
```bash
uvicorn src.query_bot:app --reload
```
Then you can send POST requests to `http://localhost:8000/api/ask` with your questions, and it will fetch the freshest data from Firebase and simulate answers on the spot.

> [!TIP]
> **Free Tier Safety**
> With the 30-minute prediction cycle, you will use ~1,800 out of 2,000 free GitHub Actions minutes per month on a private repo. If you make the repo public, it is completely unlimited and free.
