"""Structural base rates for international football markets.

These are sensible priors (from public football analytics + the international
dataset) used whenever we lack a precise model for a market — so the system
falls back to an informed base rate, *never* a blind 0.50. The calibration
loop (Tier 5) can refine these from settled results over time.

All values are per-match unless noted. "Team" rates are per-team-per-match.
"""

import math

# --- Goals (per match, international baseline) ---
BTTS = 0.48
OVER_15 = 0.72
OVER_25 = 0.50
OVER_35 = 0.30
TEAM_SCORES = 0.70            # an average team scores >=1
SECOND_HALF_MORE_GOALS = 0.47  # P(2nd-half goals strictly > 1st-half)

# --- Discipline / events ---
PENALTY_AWARDED = 0.30        # VAR era
RED_CARD = 0.12
MEAN_TOTAL_CARDS = 4.2        # yellows + reds, both teams
MEAN_TEAM_OFFSIDES = 1.8
MEAN_TEAM_CORNERS = 5.0
MEAN_TEAM_SOT = 4.0          # shots on target
MEAN_TEAM_FOULS = 12.0

# Logistic slope: how strongly an Elo edge tilts a "more X than opponent" market.
# ~200 Elo edge -> ~0.61; ~400 -> ~0.71.
_ELO_TILT = 0.0023


def logistic(x):
    return 1.0 / (1.0 + math.exp(-x))


def poisson_at_least(mean, k):
    """P(X >= k) for X ~ Poisson(mean)."""
    if mean <= 0:
        return 0.0 if k > 0 else 1.0
    # P(X < k) = sum_{i=0}^{k-1} e^-m m^i / i!
    cdf = 0.0
    term = math.exp(-mean)
    for i in range(0, max(0, k)):
        if i > 0:
            term *= mean / i
        cdf += term
    return max(0.0, min(1.0, 1.0 - cdf))


def penalty_or_red():
    """P(penalty awarded OR red card shown)."""
    return 1.0 - (1.0 - PENALTY_AWARDED) * (1.0 - RED_CARD)


def total_cards_at_least(n, mean_cards=MEAN_TOTAL_CARDS):
    return poisson_at_least(mean_cards, n)


def team_offsides_at_least(n, mean=MEAN_TEAM_OFFSIDES):
    return poisson_at_least(mean, n)


def total_threshold(mean_total, n):
    """Generic 'N or more total events' via Poisson on the total mean."""
    return poisson_at_least(mean_total, n)


def comparison_prob(elo_diff_for_subject, invert=False, half=False):
    """P(subject has strictly MORE of an event than the opponent).

    elo_diff_for_subject: subject_elo - opponent_elo (positive = subject stronger).
    invert: True for events the *weaker* side tends to do more of (e.g. fouls
            committed by the team chasing the game / under pressure).
    half:  half-restricted markets have fewer events -> more ties; since a tie
           resolves as 'No' for a 'more than' question, shrink a bit harder.
    """
    diff = -elo_diff_for_subject if invert else elo_diff_for_subject
    p = logistic(_ELO_TILT * diff)
    # Strictly-greater (ties resolve 'No') pulls the expected prob below the
    # symmetric logistic value; half markets have more ties so pull more.
    tie_penalty = 0.07 if half else 0.04
    return max(0.05, min(0.95, p - tie_penalty))
