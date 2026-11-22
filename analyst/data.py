import csv
import sqlite3
from collections import OrderedDict
from contextlib import closing
from enum import Enum
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from .analysis import BankCounts, Comparison, DailyTrend, summarize, summarize_trend
from .plan import AnalysisPlan, TrendPlan
from .queries import compile_queries


class QualityError(ValueError):
    """Source data prevents a reliable answer."""


class DemoRole(str, Enum):
    ANALYST = "Analyst"
    BANK_A_VIEWER = "Bank A Viewer"


class AccessDenied(PermissionError):
    """The requested banks exceed the active demo role."""

    def __init__(self):
        super().__init__("Access denied. Bank A Viewer can analyze Bank A only.")


def authorized_plan(plan, role):
    if DemoRole(role) == DemoRole.ANALYST:
        return plan
    if set(plan.bank_ids or ()) - {"A"}:
        raise AccessDenied()
    return plan.model_copy(update={"bank_ids": ("A",)})


TABLES = {"banks": ("bank_id", "bank_name"),
          "transactions": ("attempt_id", "event_date_ist", "bank_id", "status")}


ResultCache = OrderedDict[tuple[DemoRole, str, tuple[bytes, ...]], Comparison | DailyTrend]


def read_fixture(folder):
    return {table: (folder / f"{table}.csv").read_bytes() for table in TABLES}


def stage(folder, database, *, contents=None):
    if contents is None:
        contents = read_fixture(folder)
    with closing(sqlite3.connect(database)) as db, db:
        for table, columns in TABLES.items():
            names = ", ".join(columns)
            db.execute(f"CREATE TABLE {table} ({names})")
            with StringIO(contents[table].decode("utf-8"), newline="") as stream:
                reader = csv.reader(stream)
                if next(reader, None) != list(columns):
                    raise QualityError(f"Check the columns in {table}.csv")
                placeholders = ", ".join("?" for _ in columns)
                db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", reader)
        db.execute("CREATE INDEX attempt_ids ON transactions(attempt_id)")


def execute_plan(database: Path, plan: AnalysisPlan | TrendPlan, role=DemoRole.ANALYST):
    return _execute(database, authorized_plan(plan, role), role)


def _execute(database, plan, role):
    scope, metric, params = compile_queries(plan)
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        restricted = role == DemoRole.BANK_A_VIEWER
        bank_query = "SELECT bank_id FROM banks"
        if restricted:
            bank_query += " WHERE bank_id = :bank_0"
        bank_ids = [row[0] for row in db.execute(bank_query, params)]
        if len(set(bank_ids)) != len(bank_ids) or "" in bank_ids:
            raise QualityError("Correct duplicate or missing bank IDs and rerun")
        if restricted and not bank_ids:
            raise QualityError("Correct the missing Bank A dimension record and rerun")
        if set(plan.bank_ids or ()) - set(bank_ids):
            raise ValueError("Unknown bank filter")
        duplicate_scope = " AND t.bank_id = :bank_0" if restricted else ""
        checks = [
            ("missing status", "status IS NULL OR trim(status) = ''"),
            ("invalid status", "status NOT IN ('SUCCESS', 'FAILED')"),
            ("unmatched bank ID", "NOT EXISTS (SELECT 1 FROM banks b WHERE b.bank_id = s.bank_id)"),
            ("missing attempt ID", "attempt_id IS NULL OR attempt_id = ''"),
            ("duplicate attempt ID", "(SELECT COUNT(*) FROM transactions t WHERE t.attempt_id = s.attempt_id"
                                     + duplicate_scope + ") > 1"),
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


def compare(database: Path, plan: AnalysisPlan, role=DemoRole.ANALYST):
    return execute_plan(database, plan, role)


def analyze_fixture(folder: Path, plan: AnalysisPlan | TrendPlan, role=DemoRole.ANALYST,
                    *, cache: ResultCache | None = None):
    plan = authorized_plan(plan, role)
    contents = read_fixture(folder)
    if cache is not None:
        if plan.bank_ids:
            plan = plan.model_copy(update={"bank_ids": tuple(sorted(set(plan.bank_ids)))})
        fingerprints = tuple(sha256(contents[table]).digest() for table in TABLES)
        key = (DemoRole(role), plan.model_dump_json(), fingerprints)
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
    with TemporaryDirectory() as temp:
        database = Path(temp) / "fixture.sqlite"
        stage(folder, database, contents=contents)
        result = _execute(database, plan, role)
    if cache is not None:
        cache[key] = result
        if len(cache) > 32:
            cache.popitem(last=False)
    return result
