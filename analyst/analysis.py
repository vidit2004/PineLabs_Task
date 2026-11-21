from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction


@dataclass(frozen=True)
class BankCounts:
    period: str
    bank_id: str
    bank_name: str
    attempts: int
    successes: int

    @property
    def rate(self):
        return Fraction(self.successes, self.attempts)


@dataclass(frozen=True)
class DailyCounts:
    day: date
    attempts: int
    successes: int

    @property
    def rate(self):
        return Fraction(self.successes, self.attempts) if self.attempts else None


@dataclass(frozen=True)
class DailyTrend:
    rows: tuple[DailyCounts, ...]
    sql: str
    parameters: dict[str, str]


def summarize_trend(rows, window, sql, parameters):
    counts = {day: (attempts, successes) for day, attempts, successes in rows}
    days = (window.start + timedelta(days=i) for i in range((window.end - window.start).days))
    return DailyTrend(tuple(DailyCounts(day, *counts.get(day.isoformat(), (0, 0))) for day in days),
                      sql, parameters)


@dataclass(frozen=True)
class Comparison:
    rows: tuple[BankCounts, ...]
    rates: dict[str, Fraction | None]
    mix_pp: Fraction | None
    performance_pp: Fraction | None
    limitation: str | None
    sql: str
    parameters: dict[str, str]


def summarize(rows, sql, parameters):
    cohorts = {}
    totals = {}
    rates = {}
    for period in ("baseline", "current"):
        banks = {row.bank_id: row for row in rows if row.period == period}
        cohorts[period] = banks
        totals[period] = sum(row.attempts for row in banks.values())
        rates[period] = (Fraction(sum(row.successes for row in banks.values()), totals[period])
                         if banks else None)
    baseline, current = cohorts["baseline"], cohorts["current"]
    if not baseline or not current or baseline.keys() != current.keys():
        return Comparison(rows, rates, None, None, "Each bank needs observations in both windows.",
                          sql, parameters)
    mix = performance = Fraction(0)
    for bank, previous in baseline.items():
        now = current[bank]
        w0 = Fraction(previous.attempts, totals["baseline"])
        w1 = Fraction(now.attempts, totals["current"])
        mix += (w1 - w0) * previous.rate
        performance += w1 * (now.rate - previous.rate)
    return Comparison(rows, rates, 100 * mix, 100 * performance, None, sql, parameters)
