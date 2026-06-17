"""Map a classified market question to a probability.

Pulls from, in order of preference:
  1. Monte Carlo goal distributions (for goal-based markets) — most accurate.
  2. Elo-derived match/goal expectations.
  3. Real per-team rates + structural base rates (peripheral/discipline markets).
  4. Player scoring rates (player props).

Always returns an *informed* probability with a confidence tag — never a blind
0.50. The classifier type is a hint; we also re-parse the question text so new
market wordings still resolve to a sensible category.
"""

import logging
import re

import numpy as np

from src import base_rates as br

logger = logging.getLogger(__name__)


def _num_threshold(text, default=None):
    """First integer/half-number in 'N or more', 'over N.5', 'at least N'."""
    m = re.search(r"(\d+(?:\.\d+)?)", text or "")
    if not m:
        return default
    val = float(m.group(1))
    # "over 2.5" style means >= 3; "3 or more" means >= 3.
    if val != int(val):
        return int(val) + 1
    return int(val)


def _detect_subject(text, home, away):
    """Return ('home'|'away', subject_name, opponent_name) by first mention."""
    t = (text or "").lower()
    hi = t.find((home or "").lower()) if home else -1
    ai = t.find((away or "").lower()) if away else -1
    if hi == -1 and ai == -1:
        return "home", home, away
    if ai == -1 or (hi != -1 and hi < ai):
        return "home", home, away
    return "away", away, home


def _half(text):
    t = (text or "").lower()
    if "first half" in t or "halftime" in t or "at half" in t:
        return "first"
    if "second half" in t:
        return "second"
    return None


def estimate(market, ctx):
    """Return {'prob': float, 'source': str, 'confidence': 'high'|'med'|'low'}."""
    cls = market.get("classification", {}) or {}
    mtype = cls.get("type", "unknown")
    q = market.get("question_text") or market.get("question") or market.get("text", "")

    home, away = ctx.get("home_name"), ctx.get("away_name")
    mc = ctx.get("mc", {})            # dict of numpy arrays
    elo = ctx.get("elo_probs") or {}
    odds = ctx.get("odds") or {}      # devigged bookmaker probs (crowd proxy)
    dc = ctx.get("dc") or {}          # Dixon-Coles exact full-time goal probs
    hs = ctx.get("home_stats") or {}
    as_ = ctx.get("away_stats") or {}
    elo_h = hs.get("elo")
    elo_a = as_.get("elo")
    have_elo = elo_h is not None and elo_a is not None

    def mc_arr(key):
        v = mc.get(key)
        return v if v is not None and len(v) else None

    def res(p, source, conf="med"):
        return {"prob": float(max(0.01, min(0.99, p))), "source": source, "confidence": conf}

    # ---- Goal-based markets (prefer Monte Carlo) ----
    hg, ag = mc_arr("home_goals"), mc_arr("away_goals")
    total = hg + ag if hg is not None and ag is not None else None

    if mtype == "match_result":
        side, subj, _ = _detect_subject(q, home, away)
        # Model component: Dixon-Coles, else Elo, else MC.
        model_p = None
        if dc:
            model_p = dc["home_win"] if side == "home" else dc["away_win"]
        elif have_elo and elo:
            model_p = elo["home_win"] if side == "home" else elo["away_win"]
        elif hg is not None:
            model_p = float(np.mean(hg > ag) if side == "home" else np.mean(ag > hg))
        # Bookmaker odds are the strongest signal — blend when present.
        if odds.get("home_win") is not None:
            book = odds["home_win"] if side == "home" else odds["away_win"]
            if model_p is not None:
                return res(0.6 * book + 0.4 * model_p, "odds+dc", "high")
            return res(book, "odds", "high")
        if model_p is not None:
            return res(model_p, "dc" if dc else ("elo" if elo else "mc"), "high")
        return res(0.40, "prior", "low")

    if mtype == "total_goals":
        n = cls.get("threshold") or _num_threshold(q, 3)
        # "N or fewer / under N" is the complement: P(total <= n) = 1 - P(>= n+1).
        under = bool(re.search(r"fewer|under|less than|at most", q, re.I))

        def p_ge(k):
            if dc and str(k) in dc.get("p_total", {}):
                return dc["p_total"][str(k)]
            if total is not None:
                return float(np.mean(total >= k))
            return None

        if under:
            ge = p_ge(n + 1)
            if ge is not None:
                return res(1.0 - ge, "dc" if dc else "mc", "high")
            return res(1.0 - br.OVER_25, "base", "low")

        model_p = p_ge(n)
        # Bookmaker Over line matching the threshold (n>=3 -> 2.5 line).
        over = odds.get("over") or {}
        line = str(n - 0.5)
        if line in over:
            book = over[line]
            if model_p is not None:
                return res(0.5 * book + 0.5 * model_p, "odds+dc", "high")
            return res(book, "odds", "high")
        if model_p is not None:
            return res(model_p, "dc" if dc else "mc", "high")
        table = {2: br.OVER_15, 3: br.OVER_25, 4: br.OVER_35}
        return res(table.get(n, br.poisson_at_least(2.6, n)), "base", "low")

    if mtype == "both_teams_score":
        model_p = dc.get("btts") if dc else (
            float(np.mean((hg > 0) & (ag > 0))) if hg is not None else None)
        if odds.get("btts") is not None:
            book = odds["btts"]
            if model_p is not None:
                return res(0.5 * book + 0.5 * model_p, "odds+dc", "high")
            return res(book, "odds", "high")
        if model_p is not None:
            return res(model_p, "dc" if dc else "mc", "high")
        return res(br.BTTS, "base", "low")

    if mtype in ("team_score", "team_to_score") or re.search(r"score at least 1 goal|score a goal", q, re.I):
        side, subj, _ = _detect_subject(q, home, away)
        half = _half(q)
        if half == "second" and mc_arr("home_goals_2h") is not None:
            arr = mc_arr("home_goals_2h") if side == "home" else mc_arr("away_goals_2h")
            return res(float(np.mean(arr > 0)), "mc", "high")
        if half == "first" and mc_arr("home_goals_1h") is not None:
            arr = mc_arr("home_goals_1h") if side == "home" else mc_arr("away_goals_1h")
            return res(float(np.mean(arr > 0)), "mc", "high")
        # Full match: Dixon-Coles exact P(team scores), else MC.
        if dc:
            return res(dc["home_scores"] if side == "home" else dc["away_scores"], "dc", "high")
        if hg is not None:
            arr = hg if side == "home" else ag
            return res(float(np.mean(arr > 0)), "mc", "high")
        return res(br.TEAM_SCORES, "base", "low")

    if mtype in ("half_specific_goals",) or re.search(r"score in the (first|second) half", q, re.I):
        side, subj, _ = _detect_subject(q, home, away)
        half = _half(q) or "second"
        key = ("home" if side == "home" else "away") + ("_goals_2h" if half == "second" else "_goals_1h")
        arr = mc_arr(key)
        if arr is not None:
            return res(float(np.mean(arr > 0)), "mc", "high")
        return res(0.45 if half == "second" else 0.40, "base", "low")

    if mtype == "half_goals_comparison" or re.search(r"(second|first) half have more total goals", q, re.I):
        h1 = mc_arr("home_goals_1h"); a1 = mc_arr("away_goals_1h")
        h2 = mc_arr("home_goals_2h"); a2 = mc_arr("away_goals_2h")
        if all(x is not None for x in (h1, a1, h2, a2)):
            second_more = (h2 + a2) > (h1 + a1)
            return res(float(np.mean(second_more)), "mc", "med")
        return res(br.SECOND_HALF_MORE_GOALS, "base", "low")

    # ---- Discipline / event markets ----
    if mtype == "penalty_or_red" or re.search(r"penalty kick.*red card|red card.*penalty", q, re.I):
        return res(br.penalty_or_red(), "base", "med")

    if mtype == "cards_threshold" or re.search(r"\bcards?\b", q, re.I):
        n = cls.get("threshold") or _num_threshold(q, 4)
        return res(br.total_cards_at_least(n), "base", "med")

    if mtype == "offsides_threshold" or re.search(r"offside", q, re.I):
        n = cls.get("threshold") or _num_threshold(q, 2)
        return res(br.team_offsides_at_least(n), "base", "med")

    # ---- Player shot-on-target (BEFORE team SoT to avoid the greedy collision) ----
    if mtype == "player_shot_on_target" or re.search(r"at least \d+ shot on target", q, re.I):
        rate = _player_rate(q, ctx)
        base = 0.62  # named players are usually attackers; SoT >> scoring
        if rate is not None:
            base = min(0.85, 0.45 + rate)
        return res(base, "player", "low")

    # ---- Comparison markets (peripheral stats) ----
    if mtype == "corners_comparison" or re.search(r"more corner kicks? than|more corners than", q, re.I):
        side, subj, opp = _detect_subject(q, home, away)
        diff = (elo_h - elo_a) if (have_elo and side == "home") else \
               (elo_a - elo_h) if have_elo else 0
        return res(br.comparison_prob(diff, half=_half(q) is not None), "base+elo", "med")

    if mtype == "shots_on_target_comparison" or re.search(r"more shots on target than", q, re.I):
        side, subj, opp = _detect_subject(q, home, away)
        diff = (elo_h - elo_a) if (have_elo and side == "home") else \
               (elo_a - elo_h) if have_elo else 0
        return res(br.comparison_prob(diff, half=_half(q) is not None), "base+elo", "med")

    if mtype == "fouls_comparison" or re.search(r"more fouls than|commit more fouls", q, re.I):
        side, subj, opp = _detect_subject(q, home, away)
        # weaker side tends to commit more fouls -> invert
        diff = (elo_h - elo_a) if (have_elo and side == "home") else \
               (elo_a - elo_h) if have_elo else 0
        return res(br.comparison_prob(diff, invert=True, half=_half(q) is not None), "base+elo", "med")

    # ---- Threshold markets for peripheral stats ----
    # "total" => both teams (2x mean); single-team => 1x mean. Half-restricted
    # questions see ~45%/55% of full-match events.
    def _scaled_mean(team_mean):
        m = (2 * team_mean) if "total" in q.lower() else team_mean
        h = _half(q)
        if h == "second":
            m *= 0.55
        elif h == "first":
            m *= 0.45
        return m

    if mtype == "corners_threshold" or re.search(r"corner", q, re.I):
        n = cls.get("threshold") or _num_threshold(q, 9)
        is_total = "total" in q.lower()
        # Use MC only for the full-match total case it actually models.
        if is_total and _half(q) is None:
            hc, ac = mc_arr("home_corners"), mc_arr("away_corners")
            if hc is not None and ac is not None:
                return res(float(np.mean((hc + ac) >= n)), "mc", "med")
        return res(br.total_threshold(_scaled_mean(br.MEAN_TEAM_CORNERS), n), "base", "low")

    if mtype == "shots_on_target_threshold" or re.search(r"shots? on target", q, re.I):
        n = cls.get("threshold") or _num_threshold(q, 8)
        return res(br.total_threshold(_scaled_mean(br.MEAN_TEAM_SOT), n), "base", "low")

    # ---- Player props ----
    if mtype in ("player_goal_assist",) or re.search(r"score or assist|score a goal", q, re.I):
        rate = _player_rate(q, ctx)
        if rate is not None:
            # "score OR assist" is moderately higher than "score": ~1.3x, capped.
            return res(min(0.82, rate * 1.3), "player", "med")
        return res(0.33, "base", "low")

    if mtype == "first_goal_conditional" or re.search(r"score the first goal", q, re.I):
        side, subj, _ = _detect_subject(q, home, away)
        if hg is not None:
            any_goal = np.mean(total > 0)
            lam_h = np.mean(hg); lam_a = np.mean(ag)
            share = lam_h / (lam_h + lam_a) if (lam_h + lam_a) > 0 else 0.5
            p = float(any_goal) * (share if side == "home" else (1 - share))
            return res(p, "mc", "med")
        return res(0.33, "base", "low")

    # ---- Compound markets: crowd over-prices AND, under-prices OR ----
    if mtype == "compound_and":
        return res(0.30, "compound", "low")
    if mtype == "compound_or":
        return res(0.66, "compound", "low")

    # ---- Genuine unknown: neutral but flagged low confidence ----
    return res(0.50, "unknown", "low")


def _player_rate(q, ctx):
    """Look up a named player's anytime-scorer rate from stored team scorers."""
    scorers = {}
    for key in ("home_stats", "away_stats"):
        for s in (ctx.get(key) or {}).get("top_scorers", []) or []:
            scorers[s.get("name", "").lower()] = s.get("rate")
    if not scorers:
        return None
    ql = (q or "").lower()
    for name, rate in scorers.items():
        if name and name in ql:
            return rate
    # surname match
    for name, rate in scorers.items():
        sn = name.split()[-1] if name else ""
        if sn and sn in ql:
            return rate
    return None
