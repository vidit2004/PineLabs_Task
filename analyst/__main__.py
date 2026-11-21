import argparse
import sys
from pathlib import Path

from .analysis import DailyTrend
from .data import QualityError
from .plan import Clarification
from .planner import QUESTION, PlannerError, ask


def main():
    parser = argparse.ArgumentParser(description="Compare synthetic bank payment success.")
    parser.add_argument("--mode", choices=["offline", "live"], required=True)
    parser.add_argument("--fixture", choices=["clean", "broken"], default="clean")
    parser.add_argument("question", nargs="?", default=QUESTION)
    args = parser.parse_args()
    label = "offline preset" if args.mode == "offline" else "live Gemini"
    print(f"Planner: {label} | Synthetic fixture: {args.fixture}")
    print(args.question)
    folder = Path(__file__).resolve().parents[1] / "data" / "fixtures" / args.fixture
    try:
        result = ask(args.question, args.mode, folder)
    except PlannerError as exc:
        print(f"{exc} Retry or select the demo with --mode offline.", file=sys.stderr)
        return 1
    except QualityError as exc:
        print(exc, file=sys.stderr)
        return 1
    if isinstance(result, Clarification):
        print(result.question)
        return 0
    if isinstance(result, DailyTrend):
        for row in result.rows:
            rate = "unavailable" if row.rate is None else f"{float(row.rate):.1%}"
            print(f"{row.day} IST: {row.successes}/{row.attempts} ({rate})")
        print(result.sql, result.parameters)
        return 0
    for period, rate in result.rates.items():
        value = "unavailable" if rate is None else f"{float(rate):.1%}"
        start = result.parameters[f"{period}_start"]
        end = result.parameters[f"{period}_end"]
        print(f"{period} [{start}, {end}): {value}")
    for row in result.rows:
        print(f"{row.period} {row.bank_name}: {row.successes}/{row.attempts}")
    if result.limitation:
        print(result.limitation)
    else:
        print(f"Mix: {float(result.mix_pp):+.1f} pp | Within-bank: {float(result.performance_pp):+.1f} pp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
