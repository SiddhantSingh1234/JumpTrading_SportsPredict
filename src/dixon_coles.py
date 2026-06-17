"""Dixon-Coles bivariate goals model (Tier 2.1).

Independent Poisson over-counts 1-0/0-1 and under-counts 0-0/1-1. Dixon-Coles
applies a low-score correlation correction (parameter rho < 0) that inflates
draws and shifts the joint score distribution to match football reality.

We build the exact joint score matrix once and read every full-time goal market
off it analytically (no Monte-Carlo sampling noise). Half-specific markets still
use the engine's per-half simulation.
"""

import math

import numpy as np

_DEFAULT_RHO = -0.13  # typical fitted value; mild negative low-score dependence


def _tau(x, y, lam, mu, rho):
    """Dixon-Coles low-score correction factor."""
    if x == 0 and y == 0:
        return 1.0 - lam * mu * rho
    if x == 0 and y == 1:
        return 1.0 + lam * rho
    if x == 1 and y == 0:
        return 1.0 + mu * rho
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(lam_home, lam_away, rho=_DEFAULT_RHO, max_goals=10):
    """Return a (max_goals+1)x(max_goals+1) joint probability matrix
    M[i, j] = P(home=i, away=j), Dixon-Coles corrected and normalised."""
    lam_home = max(0.05, float(lam_home))
    lam_away = max(0.05, float(lam_away))

    # Poisson pmfs
    i = np.arange(max_goals + 1)
    ph = np.exp(-lam_home) * lam_home ** i / np.array([math.factorial(k) for k in i])
    pa = np.exp(-lam_away) * lam_away ** i / np.array([math.factorial(k) for k in i])

    M = np.outer(ph, pa)
    # Apply tau correction to the four low-score cells.
    for x in (0, 1):
        for y in (0, 1):
            M[x, y] *= _tau(x, y, lam_home, lam_away, rho)
    M = np.clip(M, 0.0, None)
    s = M.sum()
    if s > 0:
        M /= s
    return M


def summary(M):
    """Standard full-time goal-market probabilities from a score matrix."""
    n = M.shape[0]
    idx = np.arange(n)
    home_goals = idx[:, None]
    away_goals = idx[None, :]
    total = home_goals + away_goals

    home_win = float(M[np.where(home_goals > away_goals)].sum())
    draw = float(np.trace(M))
    away_win = float(M[np.where(home_goals < away_goals)].sum())

    p_total = {k: float(M[total >= k].sum()) for k in range(1, 9)}

    btts = float(M[1:, 1:].sum())
    home_scores = float(M[1:, :].sum())
    away_scores = float(M[:, 1:].sum())
    exp_total = float((M * total).sum())

    return {
        "home_win": round(home_win, 4),
        "draw": round(draw, 4),
        "away_win": round(away_win, 4),
        "p_total": {str(k): round(v, 4) for k, v in p_total.items()},
        "btts": round(btts, 4),
        "home_scores": round(home_scores, 4),
        "away_scores": round(away_scores, 4),
        "exp_total": round(exp_total, 3),
    }
