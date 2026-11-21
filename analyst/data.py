import csv
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from .analysis import BankCounts, summarize, summarize_trend
from .plan import AnalysisPlan, TrendPlan
from .queries import compile_queries


class QualityError(ValueError):
    """Source data prevents a reliable answer."""


TABLES = {"banks": ("bank_id", "bank_name"),
          "transactions": ("attempt_id", "event_date_ist", "bank_id", "status")}


def stage(folder, database):
    with closing(sqlite3.connect(database)) as db, db:
        for table, columns in TABLES.items():
            names = ", ".join(columns)
            db.execute(f"CREATE TABLE {table} ({names})")
            with (folder / f"{table}.csv").open(encoding="utf-8", newline="") as stream:
                reader = csv.reader(stream)
                if next(reader, None) != list(columns):
                    raise QualityError(f"Check the columns in {table}.csv")
                placeholders = ", ".join("?" for _ in columns)
                db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", reader)
        db.execute("CREATE INDEX attempt_ids ON transactions(attempt_id)")


def execute_plan(database: Path, plan: AnalysisPlan | TrendPlan):
    scope, metric, params = compile_queries(plan)
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        bank_ids = [row[0] for row in db.execute("SELECT bank_id FROM banks")]
        if len(set(bank_ids)) != len(bank_ids) or "" in bank_ids:
            raise QualityError("Correct duplicate or missing bank IDs and rerun")
        if set(plan.bank_ids or ()) - set(bank_ids):
            raise ValueError("Unknown bank filter")
        checks = [
            ("missing status", "status IS NULL OR trim(status) = ''"),
            ("invalid status", "status NOT IN ('SUCCESS', 'FAILED')"),
            ("unmatched bank ID", "NOT EXISTS (SELECT 1 FROM banks b WHERE b.bank_id = s.bank_id)"),
            ("missing attempt ID", "attempt_id IS NULL OR attempt_id = ''"),
            ("duplicate attempt ID", "(SELECT COUNT(*) FROM transactions t WHERE t.attempt_id = s.attempt_id) > 1"),
        ]
        for label, predicate in checks:
            query = scope + f"SELECT period, COUNT(*) FROM scoped s WHERE {predicate} GROUP BY period ORDER BY period"
            failure = db.execute(query, params).fetchone()
            if failure:
                period, count = failure
                window = getattr(plan, period)
                raise QualityError(f"Analysis blocked: {label} in {period} [{window.start}, {window.end}), "
                                   f"{count} affected. Correct the source or choose a clean dataset and rerun.")
        cursor = db.execute(metric, params)
        if isinstance(plan, TrendPlan):
            return summarize_trend(cursor, plan.window, metric, params)
        rows = tuple(BankCounts(*row) for row in cursor)
    return summarize(rows, metric, params)


def compare(database: Path, plan: AnalysisPlan):
    return execute_plan(database, plan)


def analyze_fixture(folder: Path, plan: AnalysisPlan | TrendPlan):
    with TemporaryDirectory() as temp:
        database = Path(temp) / "fixture.sqlite"
        stage(folder, database)
        return execute_plan(database, plan)
