"""Probability calibration (Tier 5).

Learns, from settled results, how our stated probabilities map to realised
frequencies, then recalibrates future submissions. Because Brier is strictly
proper, better calibration directly raises RBP without needing better raw
prediction — the cheapest edge available.

Pure-Python (no sklearn): binned reliability + Pool-Adjacent-Violators isotonic
regression + shrinkage toward the identity for low-count bins. Calibration is
fit per market CATEGORY (with a global fallback) and applied at predict time.
"""

# Market type -> coarse category for calibration (enough data per category).
CATEGORY_BY_TYPE = {
    "match_result": "result",
    "total_goals": "totals",
    "both_teams_score": "btts_team",
    "team_score": "btts_team",
    "team_to_score": "btts_team",
    "half_specific_goals": "halves",
    "half_goals_comparison": "halves",
    "first_goal_conditional": "halves",
    "corners_comparison": "peripheral_cmp",
    "fouls_comparison": "peripheral_cmp",
    "shots_on_target_comparison": "peripheral_cmp",
    "corners_threshold": "peripheral_thr",
    "shots_on_target_threshold": "peripheral_thr",
    "offsides_threshold": "peripheral_thr",
    "cards_threshold": "events",
    "penalty_or_red": "events",
    "player_goal_assist": "player",
    "player_shot_on_target": "player",
    "compound_and": "compound",
    "compound_or": "compound",
}

_MIN_CAT_SAMPLES = 25     # below this, use the global map
_MIN_GLOBAL_SAMPLES = 40  # below this, identity (no recalibration yet)


def category_for(mtype):
    return CATEGORY_BY_TYPE.get(mtype, "other")


def _pava(y, w):
    """Weighted Pool-Adjacent-Violators -> non-decreasing fit of y."""
    blocks = []  # each: [sum_wy, sum_w, count]
    for yi, wi in zip(y, w):
        blocks.append([yi * wi, wi, 1])
        while len(blocks) >= 2 and (blocks[-2][0] / blocks[-2][1]) > (blocks[-1][0] / blocks[-1][1]):
            a = blocks.pop()
            b = blocks.pop()
            blocks.append([b[0] + a[0], b[1] + a[1], b[2] + a[2]])
    out = []
    for sw, sumw, count in blocks:
        out.extend([sw / sumw if sumw else 0.0] * count)
    return out


def _fit_one(samples, n_bins=10, prior=6.0):
    """samples: list of (prob, outcome). Returns {x:[midpoints], y:[calibrated], n:int} or None."""
    if len(samples) < 5:
        return None
    bins_sum = [0.0] * n_bins
    bins_cnt = [0] * n_bins
    for p, o in samples:
        b = min(n_bins - 1, max(0, int(p * n_bins)))
        bins_sum[b] += o
        bins_cnt[b] += 1

    mids, realized, weights = [], [], []
    for b in range(n_bins):
        mid = (b + 0.5) / n_bins
        cnt = bins_cnt[b]
        # Shrink realised frequency toward the bin midpoint (identity) by `prior`
        # pseudo-counts so sparse bins barely move.
        val = (bins_sum[b] + prior * mid) / (cnt + prior)
        mids.append(mid)
        realized.append(val)
        weights.append(cnt + prior)

    calibrated = _pava(realized, weights)  # enforce monotonic non-decreasing
    return {"x": [round(m, 4) for m in mids],
            "y": [round(c, 4) for c in calibrated],
            "n": len(samples)}


def fit(samples):
    """samples: list of (category, prob, outcome). Returns a serialisable map."""
    by_cat_samples = {}
    all_samples = []
    for cat, p, o in samples:
        if p is None or o is None:
            continue
        by_cat_samples.setdefault(cat, []).append((p, o))
        all_samples.append((p, o))

    by_cat = {}
    for cat, s in by_cat_samples.items():
        m = _fit_one(s)
        if m:
            by_cat[cat] = m
    glob = _fit_one(all_samples)
    return {"by_cat": by_cat, "global": glob, "n": len(all_samples)}


def _interp(p, x, y):
    if not x:
        return p
    if p <= x[0]:
        return y[0]
    if p >= x[-1]:
        return y[-1]
    for i in range(1, len(x)):
        if p <= x[i]:
            t = (p - x[i - 1]) / (x[i] - x[i - 1]) if x[i] != x[i - 1] else 0.0
            return y[i - 1] + t * (y[i] - y[i - 1])
    return y[-1]


def apply(prob, category, calib):
    """Recalibrate a probability. Prefers the category map, falls back to global,
    then identity if there isn't enough data yet. Returns prob in (0,1)."""
    if not calib:
        return prob
    cat_map = (calib.get("by_cat") or {}).get(category)
    if cat_map and cat_map.get("n", 0) >= _MIN_CAT_SAMPLES:
        out = _interp(prob, cat_map["x"], cat_map["y"])
    else:
        glob = calib.get("global")
        if glob and glob.get("n", 0) >= _MIN_GLOBAL_SAMPLES:
            out = _interp(prob, glob["x"], glob["y"])
        else:
            out = prob  # not enough data — identity
    return max(0.01, min(0.99, out))
