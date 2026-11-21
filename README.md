# Payment success comparison

This H0–6 slice runs an explicit bank comparison against fictional payment attempts. Each transactions.csv row is one attempt identified by attempt_id. Each banks.csv row is one bank identified by bank_id. Success rate divides successful attempts by eligible terminal attempts (SUCCESS or FAILED with a matching bank). Overall rates use summed counts.

From the repository root in PowerShell, using Python 3.11 (development version 3.11.5):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python scripts/seed_demo.py
.\.venv\Scripts\python -m pytest -q
```

The seed is deterministic. The broken variant clears one current-week status. The following example uses the shipped files directly:

```python
from pathlib import Path
from analyst.data import analyze_fixture
from analyst.plan import AnalysisPlan

plan = AnalysisPlan(intent="compare", metric="success_rate", group_by="bank",
                    baseline={"start": "2026-10-05", "end": "2026-10-12"},
                    current={"start": "2026-10-12", "end": "2026-10-19"})
answer = analyze_fixture(Path("data/fixtures/clean"), plan)
print(answer.rows, answer.rates, answer.mix_pp, answer.performance_pp)
print(answer.sql, answer.parameters)
```

Windows use IST dates with exclusive ends. The temporary staging database preserves source rows for quality checks. Analysis opens it read-only and checks data in the same snapshot as the count query. A QualityError blocks the result. The mix effect weights changes in attempt share by baseline bank rates. The performance effect weights bank rate changes by current shares. Both are descriptive percentage-point contributions.
