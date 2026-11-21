from .plan import AnalysisPlan, TrendPlan


def compile_queries(plan: AnalysisPlan | TrendPlan):
    if isinstance(plan, TrendPlan):
        params = {"window_start": plan.window.start.isoformat(), "window_end": plan.window.end.isoformat()}
        scope = """WITH scoped AS (
            SELECT t.*, 'window' AS period FROM transactions t
            WHERE event_date_ist >= :window_start AND event_date_ist < :window_end"""
        groups = "event_date_ist"
    else:
        params = {f"{name}_{bound}": getattr(getattr(plan, name), bound).isoformat()
                  for name in ("baseline", "current") for bound in ("start", "end")}
        groups = "period, s.bank_id, bank_name"
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
    metric = scope + f"""SELECT {groups}, COUNT(*) AS attempts,
        SUM(status = 'SUCCESS') AS successes
        FROM scoped s JOIN banks b ON s.bank_id = b.bank_id
        WHERE status IN ('SUCCESS', 'FAILED')
        GROUP BY {groups} ORDER BY {groups}"""
    return scope, metric, params
