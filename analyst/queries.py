from .plan import AnalysisPlan


def compile_queries(plan: AnalysisPlan):
    params = {f"{name}_{bound}": getattr(getattr(plan, name), bound).isoformat()
              for name in ("baseline", "current") for bound in ("start", "end")}
    scope = """WITH scoped AS (
        SELECT t.*, CASE WHEN event_date_ist < :baseline_end THEN 'baseline'
                         ELSE 'current' END AS period
        FROM transactions t
        WHERE ((event_date_ist >= :baseline_start AND event_date_ist < :baseline_end)
            OR (event_date_ist >= :current_start AND event_date_ist < :current_end))"""
    if plan.bank_ids:
        filters = {f"bank_{i}": bank for i, bank in enumerate(plan.bank_ids)}
        params.update(filters)
        scope += " AND bank_id IN (" + ", ".join(":" + key for key in filters) + ")"
    scope += "\n)\n"
    metric = scope + """SELECT period, s.bank_id, bank_name, COUNT(*) AS attempts,
        SUM(status = 'SUCCESS') AS successes
        FROM scoped s JOIN banks b ON s.bank_id = b.bank_id
        WHERE status IN ('SUCCESS', 'FAILED')
        GROUP BY period, s.bank_id, bank_name ORDER BY period, s.bank_id"""
    return scope, metric, params
