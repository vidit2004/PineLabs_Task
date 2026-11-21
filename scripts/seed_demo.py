import csv
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data" / "fixtures"


def seed(root=ROOT):
    for variant in ("clean", "broken"):
        folder = root / variant
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "banks.csv").open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows([("bank_id", "bank_name"), ("A", "Bank A"), ("B", "Bank B")])
        with (folder / "transactions.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("attempt_id", "event_date_ist", "bank_id", "status"))
            for day, bank, total, successes in [(5, "A", 800, 784), (5, "B", 200, 180),
                                                (12, "A", 400, 392), (12, "B", 600, 528)]:
                for i in range(total):
                    status = "SUCCESS" if i < successes else "FAILED"
                    if variant == "broken" and (day, bank, i) == (12, "A", 0):
                        status = ""
                    writer.writerow((f"{day}-{bank}-{i}", date(2026, 10, day) + timedelta(days=i % 7),
                                     bank, status))


if __name__ == "__main__":
    seed()
