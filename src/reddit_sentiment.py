"""Reddit public-sentiment collection (free, optional).

Because RBP scores us relative to a crowd whose prices we cannot see, Reddit is
our best free proxy for public sentiment. We collect match-relevant discussion
(upvote-weighted) so the AI can quantify the public lean and we can FADE
predictable crowd bias (star/big-nation hype, over-priced compound bets).

Uses the official Reddit API via PRAW (free "script" app). Inactive unless
REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are set. Returns raw text for the AI
to turn into structured sentiment; never raises into the caller.
"""

import logging

from src.config import Config

logger = logging.getLogger(__name__)


class RedditSentiment:
    def __init__(self):
        self.enabled = bool(Config.REDDIT_CLIENT_ID and Config.REDDIT_CLIENT_SECRET)
        self._reddit = None
        if self.enabled:
            try:
                import praw  # lazy: only needed when enabled
                self._reddit = praw.Reddit(
                    client_id=Config.REDDIT_CLIENT_ID,
                    client_secret=Config.REDDIT_CLIENT_SECRET,
                    user_agent=Config.REDDIT_USER_AGENT,
                    check_for_async=False,
                )
                self._reddit.read_only = True
            except Exception as e:
                logger.warning(f"Reddit init failed; disabling: {e}")
                self.enabled = False

    def fetch_match_sentiment(self, home, away, max_posts=6, max_comments=5):
        """Return a list of {title, score, comments:[...]} for the matchup,
        gathered across the configured subreddits. Empty list if disabled."""
        if not self.enabled or not self._reddit:
            return []

        query = f"{home} {away}"
        bundle = []
        seen = set()
        try:
            subs = "+".join(Config.REDDIT_SUBREDDITS)
            multi = self._reddit.subreddit(subs)
            # Recent + relevant: search this matchup in the last week.
            for submission in multi.search(query, sort="relevance", time_filter="week", limit=max_posts):
                if submission.id in seen:
                    continue
                seen.add(submission.id)
                comments = []
                try:
                    submission.comment_sort = "top"
                    submission.comments.replace_more(limit=0)
                    for c in submission.comments[:max_comments]:
                        body = getattr(c, "body", "") or ""
                        if body and body not in ("[deleted]", "[removed]"):
                            comments.append({"score": int(getattr(c, "score", 0)), "text": body[:400]})
                except Exception:
                    pass
                bundle.append({
                    "title": submission.title,
                    "score": int(getattr(submission, "score", 0)),
                    "subreddit": str(submission.subreddit),
                    "comments": comments,
                })
        except Exception as e:
            logger.warning(f"Reddit fetch failed for {home} vs {away}: {e}")
            return []

        logger.info(f"Reddit: collected {len(bundle)} posts for {home} vs {away}.")
        return bundle
