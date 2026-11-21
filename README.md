# Payment success comparison

The analyst turns a question into a validated bank comparison against fictional payment attempts. Each transactions.csv row is one attempt identified by attempt_id. Each banks.csv row is one bank identified by bank_id. Success rate divides successful attempts by eligible terminal attempts (SUCCESS or FAILED with a matching bank). Overall rates use summed counts.

From the repository root in PowerShell, using Python 3.11 (development version 3.11.5):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python scripts/seed_demo.py
.\.venv\Scripts\python -m pytest -q
```

## Launch the comparison screen from PowerShell

From the repository root, install the screen dependencies and start Streamlit.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Choose **Offline preset**, leave **Clean** selected, and click **Run comparison**. Expand **Query and dataset evidence** to inspect the executed SQL, parameters and IST date windows. Repeat with **Broken** to see the missing-status error, then switch back to **Clean** and rerun to recover. To use **Live Gemini**, set the two environment variables described below in the PowerShell session before launching Streamlit.

## Try the question planner from PowerShell

Run the offline preset from the repository root. With no question argument, the CLI uses the shipped October comparison.

```powershell
.\.venv\Scripts\python.exe -m analyst --mode offline
```

For a separate live smoke test, enter your Gemini API key and a model ID available to your account that supports JSON output. The adapter sends the question and approved catalog to Gemini. The local executor validates the response and computes the numbers.

```powershell
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Gemini API key' -AsSecureString)).Password
$env:GEMINI_MODEL = Read-Host 'Gemini model ID (without models/)'
.\.venv\Scripts\python.exe -m analyst --mode live "Compare payment success by bank for Oct 5-11 and Oct 12-18, 2026."
```

Both examples should report 96.4% and 92.0%, with mix and within-bank effects of −3.2 pp and −1.2 pp. Live mode also accepts custom questions. A clarification prints a follow-up question. A planner error exits with status 1 and you can explicitly rerun the offline command. Add `--fixture broken` to try the quality gate.

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
