import logging

from src import calibration
from src.database import Database
from src.market_classifier import MarketClassifier

logger = logging.getLogger(__name__)


def _to_prob01(p):
    """Results return probability as a 1-99 integer (or 0-1 decimal). Normalise."""
    if p is None:
        return None
    p = float(p)
    return p / 100.0 if p > 1.0 else p


def _outcome_from_brier(p, brier):
    """Recover the binary outcome from (prob, brier): brier=(p-o)^2, o in {0,1}."""
    if p is None or brier is None:
        return None
    b1 = (p - 1.0) ** 2  # if outcome was 1
    b0 = p ** 2          # if outcome was 0
    return 1 if abs(brier - b1) <= abs(brier - b0) else 0


def _result_field(entry, *keys):
    for k in keys:
        if k in entry and entry[k] is not None:
            return entry[k]
    return None


class Calibrator:
    def __init__(self, db: Database, sp_api, ai_client=None):
        self.db = db
        self.sp_api = sp_api
        self.ai = ai_client
        # Regex-only classifier (no AI calls) to categorise the question text
        # that /results returns directly.
        self.classifier = MarketClassifier(None)

    def run_full_calibration(self):
        """Daily: score settled results, fit a recalibration map per market
        category, detect per-category bias, and persist for the predict run."""
        logger.info("Starting calibration run.")
        results = self.sp_api.get_results()
        if not results:
            logger.info("No settled results to process.")
            return

        samples = []          # (category, prob01, outcome)
        per_cat = {}          # category -> {"n", "sum_brier", "sum_p", "sum_o"}
        total_brier = 0.0
        scored = 0

        from src.config import Config
        since = Config.CALIBRATION_SINCE_DATE
        skipped_old = 0

        for entry in results:
            # Only settled markets are scored.
            status = entry.get("market_status")
            if status and status != "settled":
                continue
            # Skip results from before the new system went live (don't calibrate
            # the new pipeline on the old bad bot's predictions).
            if since:
                cd = entry.get("created_date", "")
                if cd and cd[:10] < since:
                    skipped_old += 1
                    continue
            prob = _to_prob01(_result_field(entry, "probability_submitted", "probability", "prob"))
            brier = _result_field(entry, "brier_score", "brierscore", "brier")
            if prob is None or brier is None:
                continue
            outcome = _outcome_from_brier(prob, brier)
            if outcome is None:
                continue

            # The result includes the question text -> classify it directly
            # (regex only, no AI cost) instead of needing a stored market doc.
            question = entry.get("question", "")
            cls = self.classifier.classify({"question_text": question}) or {}
            mtype = cls.get("type", "unknown")
            cat = calibration.category_for(mtype)

            samples.append((cat, prob, outcome))
            total_brier += float(brier)
            scored += 1
            agg = per_cat.setdefault(cat, {"n": 0, "sum_brier": 0.0, "sum_p": 0.0, "sum_o": 0.0})
            agg["n"] += 1
            agg["sum_brier"] += float(brier)
            agg["sum_p"] += prob
            agg["sum_o"] += outcome

        if skipped_old:
            logger.info(f"Calibration: skipped {skipped_old} pre-{since} results (old bot).")
        if scored == 0:
            logger.info("No scorable settled results found (after date filter).")
            return

        # Fit + persist the recalibration map for the predict run to apply.
        calib = calibration.fit(samples)
        self.db.save_state("calibration", calib)

        # Per-category bias report (mean predicted vs realised) for visibility.
        report = {"overall_brier": round(total_brier / scored, 4), "scored": scored, "by_category": {}}
        for cat, agg in per_cat.items():
            n = agg["n"]
            mean_p = agg["sum_p"] / n
            mean_o = agg["sum_o"] / n
            report["by_category"][cat] = {
                "n": n,
                "brier": round(agg["sum_brier"] / n, 4),
                "mean_pred": round(mean_p, 4),
                "mean_actual": round(mean_o, 4),
                "bias": round(mean_p - mean_o, 4),  # +ve = we over-predict this category
            }
        self.db.save_state("calibration_report", report)
        logger.info(f"Calibration complete: {scored} settled, overall Brier {report['overall_brier']}.")
        for cat, r in report["by_category"].items():
            logger.info(f"  [{cat}] n={r['n']} brier={r['brier']} bias={r['bias']:+.3f}")

        if self.ai:
            self._ai_bias_summary(report)

    def _ai_bias_summary(self, report):
        try:
            import json
            from src.config import Config
            from google.genai import types
            prompt = (
                "These are our prediction calibration stats per market category "
                "(bias>0 = we over-predict). In under 120 words, name the 2-3 biggest "
                f"systematic biases to correct:\n{json.dumps(report, indent=1)}"
            )
            resp = self.ai._safe_generate(
                model=Config.GEMINI_STATS_MODEL,
                contents=prompt,
                fallback_models=["gemma-4-31b-it"],
            )
            self.db.save_state("calibration_notes", resp.text)
            logger.info(f"Calibration notes: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"AI bias summary failed: {e}")

    # ------------------------------------------------------------------ #

    def get_dashboard_data(self):
        report = self.db.get_state("calibration_report") or {}
        preds = self.db.get_predictions()
        return {
            "overall_brier": report.get("overall_brier"),
            "scored": report.get("scored", 0),
            "by_category": report.get("by_category", {}),
            "total_predictions_bot1": sum(1 for p in preds if p.get("bot_number") == 1),
            "total_predictions_bot2": sum(1 for p in preds if p.get("bot_number") == 2),
            "notes": self.db.get_state("calibration_notes") or "",
        }

    def get_latest_report(self):
        return self.db.get_state("calibration_report") or {"status": "no data yet"}
