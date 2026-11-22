# Bizilytix.ai

Bizilytix.ai helps you investigate changes in payment success rates by bank and by day. Open the deployed app to try an analysis yourself, or watch the demo video for a walkthrough.

- [Deployed app link](https://pinelabstask-case2-22me3ai33.streamlit.app/?embed=true)
- [Live demo video](https://drive.google.com/file/d/1S9iQF80ems8IuxPlVzVoUq74QI1Q7zr-/view)

### How to try the deployed app

1. Open the deployed app. If the sidebar is collapsed, open it with the arrow at the top left. Select **Offline preset** and **Clean** to run the example without an API key.
2. Set **Demo role** to **Analyst**, choose **Bank comparison example**, and click **Analyze**.
3. Scroll down to see how the payment success rate changed. Expand **Query and dataset evidence** to inspect the SQL and source data. Choose **Daily trend example** and click **Analyze** to explore a second view.

Watch the **Live demo video** linked above for a walkthrough of the dashboard.

The app is hosted on Streamlit Community Cloud and deploys from `main` using `app.py`.

Bizilytix.ai analyzes payment success by bank and by day. It validates an analysis plan, runs parameterized SQL against a read-only SQLite snapshot, and shows the counts behind each rate.

## Run locally (PowerShell)

From the repository root on Windows with Python 3.11 installed (tested with 3.11.5), run both offline examples against the shipped clean fixture. Neither example requires credentials.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m analyst --mode offline
.\.venv\Scripts\python.exe -m analyst --mode offline "Show daily payment success from October 5 through October 18, 2026"
```

The first command after setup compares October 5–11 with October 12–18. The second prints successful and eligible attempts for each of the 14 IST dates, followed by its SQL and parameters. October 5 has 138 successes from 144 attempts (95.8%).

To launch the dashboard locally after installing the dependencies, run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## Optional Live Gemini setup

In the same PowerShell session, enter an API key and a Gemini model ID available to your account that supports JSON output.

```powershell
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Gemini API key' -AsSecureString)).Password
$env:GEMINI_MODEL = Read-Host 'Gemini model ID (without models/)'
.\.venv\Scripts\python.exe -m analyst --mode live "Compare payment success by bank for Oct 5-11 and Oct 12-18, 2026."
```

Gemini proposes the plan. Python validates it and computes the results locally.

### Deployment quota

Set the following in your host’s secret manager or as top-level Streamlit deployment secrets. Use the same Upstash database and limit for all app instances.

| Setting | Value |
|---|---|
| `GEMINI_API_KEY` and `GEMINI_MODEL` | Provider key and model ID for Live Gemini |
| `GEMINI_DAILY_LIMIT` | Daily outbound attempt limit, for example the string `"100"`. Zero blocks all attempts. Leave unset for local use without Redis. |
| `UPSTASH_REDIS_REST_URL` | HTTPS REST endpoint from the Upstash Redis database |
| `UPSTASH_REDIS_REST_TOKEN` | Write-capable REST token permitting EVAL, GET, INCR and EXPIRE |

Immediately before calling Gemini, the planner reserves one slot with an atomic Redis script. Sessions and roles share the daily counter. A fresh counter starts at midnight IST and each key expires after 48 hours. A failed Gemini attempt consumes its reservation. Live planning on a result-cache hit also consumes a slot. If Redis cannot confirm a reservation, configuration is invalid, or the limit is reached, the app shows an error and **Offline preset** remains available. Configure the REST endpoint and token using the [Upstash REST API guide](https://upstash.com/docs/redis/features/restapi).

## Dashboard

Each Streamlit session keeps its 32 most recently used successful results. After planning and role checks, equivalent questions reuse a result when the validated plan, effective bank filters, active role and contents of both fixture CSVs match. A hit skips SQLite staging and execution. Live Gemini still interprets each eligible question. Denials, clarifications and failed analyses leave no cache entry. A new session starts empty.

Use **Demo role** below the banner to switch between **Analyst** (both banks) and **Bank A Viewer**. With **Offline preset** and **Clean** selected, run the bank comparison as the viewer to see Bank A’s counts and bound SQL filter. Select **Bank B example** and click **Analyze** to reproduce the denial. Switching to Analyst allows the same example. The selector demonstrates role scoping locally and is user-controlled.

Select a planner and fixture in the sidebar, choose a bank comparison or daily trend example, then click **Analyze**. Expand **Query and dataset evidence** to inspect the executed SQL, bound parameters, source datasets and IST date windows.

## Synthetic data and metric

Each variant in `data/fixtures/` contains two fictional datasets. In `transactions.csv`, each row is one payment attempt with an attempt ID, IST event date, bank ID and terminal status. In `banks.csv`, each row maps one unique bank ID to its display name. The clean fixture contains 2,000 attempts across Bank A and Bank B. The broken fixture clears one October 12 status. Running the sample comparison on **Broken** triggers a quality error. Switch back to **Clean** and rerun to recover.

Success rate is successful attempts divided by eligible attempts. Eligible attempts have a matching bank ID and a terminal status of `SUCCESS` or `FAILED`. Quality errors in scope block the answer. Overall and daily rates use summed counts. A day with zero eligible attempts has an unavailable rate and appears as a gap. Date windows use an inclusive start and exclusive end in IST.

## Bank comparison and attribution

| Bank | Oct 5–11 successes / eligible | Oct 12–18 successes / eligible |
|---|---:|---:|
| Bank A | 784 / 800 (98.0%) | 392 / 400 (98.0%) |
| Bank B | 180 / 200 (90.0%) | 528 / 600 (88.0%) |
| Overall | 964 / 1,000 (96.4%) | 920 / 1,000 (92.0%) |

The observed decline is **4.4 percentage points**. Two descriptive effects reconcile it:

- **Bank mix (−3.2 pp).** Hold each bank’s success rate at its baseline and change its share of attempts. Bank B’s share rose from 20% to 60%, shifting 40% of attempts toward a bank with an 8-point lower baseline rate.
- **Within-bank performance (−1.2 pp).** Weight each bank’s rate change by its current attempt share. Bank A’s rate held steady. Bank B fell by 2 points and handled 60% of current attempts.

## Reproduce the fixtures and run tests

```powershell
.\.venv\Scripts\python.exe scripts/seed_demo.py
git diff --exit-code -- data/fixtures
.\.venv\Scripts\python.exe -m pytest -q
```
