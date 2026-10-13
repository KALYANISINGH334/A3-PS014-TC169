# NetPulse

A local internet-quality comparison pilot: **FastAPI + SQLite** for observations and **Streamlit + Plotly** for analytics. Real mode shows only stored observations; an opt-in Demo Mode displays a separate illustrative dataset in memory. A consenting-device agent collects genuine ICMP/DNS observations every five minutes by default and uploads them automatically. Demo observations are explicitly fictional; AI model integration is not implemented.

## Windows PowerShell setup

Install Python **3.10 or newer**. Open PowerShell in the Netplus project directory. Activation is optional; these commands work without changing PowerShell execution policy:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

**Terminal 1 — backend**, from the project directory:

```powershell
$env:NETPULSE_DB_PATH = "data/netpulse.sqlite3"
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
```

**Terminal 2 — dashboard**, from the same project directory:

```powershell
$env:NETPULSE_API_URL = "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501
```

- Dashboard: **http://localhost:8501**
- API documentation and interactive payload schema: **http://localhost:8000/docs**
- Health check: **http://localhost:8000/health**

Stop each process with Ctrl+C. The default SQLite path is `data/netpulse.sqlite3`, relative to the backend's working directory. Records survive server restarts. The dashboard accesses the database exclusively through the API. Environment settings are optional because these values are defaults. `.env.example` documents settings; `.env` is **not** automatically loaded. No secrets are needed for local loopback use. Set NETPULSE_UPLOAD_TOKEN on the backend and dashboard/collectors for a central setup. Remote collectors require HTTPS plus that token; do not expose a plain HTTP development server publicly.

On macOS/Linux, replace `.\.venv\Scripts\python.exe` with `.venv/bin/python` and use `export NAME=value` for environment variables.

## API and observation contract

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Returns `{"status":"ok"}`. This checks server responsiveness, not measurement freshness or database availability. |
| `POST /measurements` | Validates an observation, saves it, returns the record including its ID with HTTP 201. |
| `GET /measurements?limit=500&offset=0` | Returns `{items, total, limit, offset}` ordered newest first. Limit is 1–5000. |

`POST /measurements` accepts these fields (see `/docs` for the machine-readable schema):

| Field | Meaning |
| --- | --- |
| `timestamp` | Required ISO 8601 actual observation time with timezone; normalized to UTC. Future times are rejected. |
| `access_medium` | `Wi-Fi`, `Ethernet`, `Cellular`, or `Unknown`. Default `Unknown`. These describe the local link, not the ISP's upstream technology. |
| `medium_verified` | Boolean, default false. |
| `verification_source` | `unverified`, `participant_attestation`, or `operator_record`. Verified labels require a known medium and declared source. |
| `isp` | Optional provider label, at most 80 characters. No personal identifiers. |
| `location_category` | Optional `urban`, `suburban`, `rural`, or `unknown`. No precise addresses. |
| `status` | `success`, `partial`, or `failed`. Successful/partial records need at least one metric; failed records must have no metrics. |
| `latency_ms` | Nullable nonnegative latency, at most 60000 ms. |
| `packet_loss_pct` | Nullable 0–100 percentage. A measured zero is preserved. |
| `dns_ms` | Nullable nonnegative DNS delay, at most 60000 ms. |
| `throughput_mbps` | Nullable nonnegative transfer rate, at most 1000000 Mbps. |

Unknown fields, nonfinite metrics, inconsistent verification, and malformed timestamps return HTTP 422. Missing metrics remain `null`; do not substitute zero. A success record is a declared successful collection, not a promise that all four metrics exist. Use `partial` when collection was incomplete. NetPulse records verification declarations but does not independently audit them.

## Dashboard workflow

1. **Overview:** connection status, separately labeled last successful observation, real medians, coverage, latency timeline, and recent records.
2. **Live Measurements:** background collection runs on each consenting device, not inside Streamlit. The page shows received collector observations and their freshness. The dashboard button remains disabled to prevent accidentally measuring the dashboard host. Use **Import an actual observation** to save a measurement already collected under a documented procedure. All numeric inputs start blank. Confirm provenance before saving. This import calls the real `POST /measurements` endpoint and reloads API data.
3. **Access Medium Comparison:** verified successful/partial records only; median of each available metric and its sample count. Missing metrics and single-category data have explicit messages.
4. **Historical Trends:** latency, loss, DNS, throughput, and latency distribution. Date range and medium filters are interactive. Individual points are used to avoid inventing intermediate observations.
5. **Data Quality & Methodology:** coverage, measurement definitions, verification, privacy, and pilot limitations.
6. **Settings & About:** runtime connection and honest prototype scope.

Click **Refresh API data** to reload. Normal interactions also refresh the data. Automatic refresh polls the API every 45 seconds when enabled. It never sends measurement probes or generates fabricated telemetry. HTTP requests use a 2-second connection timeout and a 5-second operation timeout. A disconnected API produces error states rather than stale statistics. Empty databases and filters with no results are supported. Recent tables support status filters, time order, and native column sorting.

Dashboard statistics cover the **latest 5000 attempts**, or all attempts when fewer exist; a warning appears when records are truncated. Date filters operate in UTC within this loaded window. Cards show metric medians (packet loss uses an arithmetic mean) and include metric-specific counts in tooltips. Failed attempts count toward total attempts but never contribute to metric medians. Comparisons exclude unverified labels, show per-metric sample counts, and warn about small samples. Five observations is an interface warning threshold, not a statistical significance claim.

## Automatic collection: one-time setup, then one-click startup

On Windows, open the existing project folder and run:

```powershell
.\setup_netpulse.bat
.\start_netpulse.bat
```

Setup reuses `.venv` or `.venv313`, installs dependencies and runs tests. It creates `.venv` only if neither exists. The launcher starts FastAPI, a device collector, and Streamlit in separate consoles. It preserves compatible services already using the standard ports. `targets.json` is copied from the example **only if missing**, never overwritten. Starting the collector is an explicit opt-in to this pilot; obtain consent from each volunteer before they launch it.

Default settings, explicitly approved for this initial prototype:

- ICMP target `1.1.1.1`; 3 probes, 2-second timeout, every 300 seconds.
- System DNS lookup of `example.com`; the measured duration can include cached answers.
- Throughput **disabled**. No download is attempted without both `throughput_enabled=true` and an approved, matching HTTP(S) `download_url`.
- Wi-Fi is a **declared, unverified** label. ISP is unset and location is `unknown`.
- Seven-day pilot window; the start time and schedule survive restarts. Pending uploads drain after the window ends; no new probes are collected. Use `--new-pilot --resume` to explicitly begin another window while preserving IDs and data. Set `pilot_days` to null only if ongoing collection is intended.

Edit `targets.json` for interval, probe limits, DNS hostname, access medium, ISP, and optional throughput. The running agent reloads configuration edits. Invalid settings pause operations rather than retaining obsolete approval; `enabled=false` stops the agent. Throughput has a separate default one-hour interval, minimum 30 minutes, a default 256 KiB payload cap (maximum 1 MiB), and a total timeout. Redirects are not followed and TLS verification stays enabled. Counted payload excludes transport overhead and any socket read-ahead.

To stop:

```powershell
.\stop_netpulse.bat
```

The stop marker prevents further collection; an in-progress bounded operation finishes first. The launcher stops only the backend/dashboard processes it started, checking PID creation times to avoid unrelated processes. Services that were already running manually remain yours to stop with Ctrl+C. You can also press Ctrl+C in the collector console. No database or queue is deleted. `start_netpulse.bat` explicitly resumes a stopped agent unless configuration is disabled or the pilot window has ended.

### Separate terminal / quick one-shot check

With the backend running:

```powershell
# Respect the persisted schedule; does not bypass the five-minute interval.
.\.venv\Scripts\python.exe -m agent --once
# Continuous scheduled collector:
.\.venv\Scripts\python.exe -m agent --resume
# Ask the running agent to stop:
.\.venv\Scripts\python.exe -m agent --stop
```

Use `.venv313` in these commands if that is your existing environment. On macOS/Linux use `.venv/bin/python`. The agent uses the existing `POST /measurements`; `GET /measurements` and the SQLite metric columns are preserved. New optional metadata columns are added in place without deleting records. The incompatible target-request API from `main` is **not** substituted for the dashboard API; its bounded probe implementation was adapted into this collector.

### Verify real collection locally

1. Run the launcher. Read the collector console or `data/agent/collector.log`: it should log **Collected** then **Uploaded** with a record ID. No manual import is needed.
2. Open `http://localhost:8000/docs` or run `Invoke-RestMethod http://localhost:8000/measurements`. Confirm a current timestamp, random participant/device UUIDs, `latency_method=icmp_echo`, actual metric values, and any diagnostic codes.
3. Leave the dashboard open at `http://localhost:8501`. Within 45 seconds the count and charts should update automatically. A successful observation time is distinct from the server health check. Collector status is inferred from received observations, **not a heartbeat**.
4. Wait five minutes for the next scheduled observation. Failed/partial records remain visible. `icmp_unavailable` means the OS/tool could not measure ICMP; null values are not zero. Missing RTT with 100% loss can mean filtering or an unreachable target, not proof of a bad access medium. Windows `time<1ms` is an upper bound and is not stored as an invented RTT.
5. Stop/restart: previous database records and device IDs should remain. A restart inside the interval does not send a burst of probes. With the backend temporarily stopped, observations stay in the local queue and upload after recovery, without duplicate central rows.

### Multiple consenting participants and label confirmation

Give each volunteer the collector code, dependencies, and their own `targets.json`. They run the agent on **their own device**, not the central dashboard machine. Configure `NETPULSE_API_URL` to the central HTTPS endpoint and securely configure the same `NETPULSE_UPLOAD_TOKEN` on the backend and authorized clients. This task does not deploy a central endpoint. Restrict access appropriately; a shared token authorizes uploads but does not cryptographically verify participants or labels.

Each first run creates random participant/device UUIDs in `data/agent/state.json`. The same state directory preserves them across restarts. Do not copy a participant's state directory to another volunteer. To associate two devices with one consenting participant, explicitly set the same random `participant_id` UUID in those devices' configs; device UUIDs remain distinct. Configure ISP and medium per device; there is no global assumption of a shared network.

To confirm the active routed interface locally:

```powershell
.\.venv\Scripts\python.exe -m agent --show-interface
```

Set `confirmed_interface` to that exact name and `verification_source` to `participant_attestation` (or `operator_record` where appropriate), with the corresponding actual `access_medium`. Until then the label stays unverified. An IP address is used only to find the routed adapter; it does not imply Wi-Fi/Ethernet. A mismatch downgrades the verified label to Unknown. A salted interface fingerprint records detectable adapter changes; no adapter name, IP, MAC, SSID, hostname, or precise location is uploaded. Changes between Wi-Fi networks on the same adapter may go undetected, so reconfirm after changing networks. Repeated observations are not independent participants.

### Scheduling, retries, storage, and logs

- One collector holds an OS lock per state directory; do not launch duplicate state directories for the same device.
- The interval is reserved on disk before probing. Missed intervals are not replayed. Config changes take effect at subsequent scheduled cycles.
- Observations enter `data/agent/queue/` as atomic JSON files before upload. This is a retry outbox, **not a second measurements database**. The existing backend SQLite database remains the source of dashboard records.
- Exponential retry delays are 5–300 seconds and survive restart; successful backlog uploads are limited to one per second. Each observation has a UUID; resending an identical payload returns the existing row. Reusing the UUID for different values returns HTTP 409.
- Invalid payloads go to `data/agent/rejected/` for review. They are never silently changed into passing measurements. Authentication/outage failures retain the queue. A 10,000-record outbox cap pauses new collection instead of discarding samples.
- The log rotates at 1 MiB with three backups. Logs do not contain tokens, IPs, MACs, or precise locations. SQLite persists across restarts; do not delete `data/` to reset the UI.

Optional environment settings: `NETPULSE_CONFIG` (default `targets.json`), `NETPULSE_AGENT_STATE_DIR` (default `data/agent`), `NETPULSE_API_URL`, `NETPULSE_DB_PATH`, and optional `NETPULSE_UPLOAD_TOKEN`. `.env` files are not loaded automatically. Avoid putting credentials in config files or sharing them in chat.

### Optional Windows Task Scheduler

Open **Task Scheduler → Create Task**. Run as your signed-in user and select **Run only when user is logged on** so service consoles remain accessible. Add an **At log on** trigger. Action: program `cmd.exe`; arguments `/c "C:\path\to\Netplus\start_netpulse.bat"`; **Start in** your actual Netplus folder. Under Settings select **Do not start a new instance**. The collector's OS lock supplies an additional guard. No administrator privileges should be necessary for Windows' standard ping command. If an existing server uses the old schema, restart it with the updated code before launching the collector. Disable the scheduled task and set `enabled=false` to prevent future sign-in collection. A computer must be awake, connected, and signed in for collection; missed intervals are not backfilled.

## Collection and interpretation limitations

The collector records median ICMP RTT, echo-reply loss, system DNS lookup duration, and optional bounded-download throughput. ICMP filtering and missing OS permissions affect availability. DNS caches, target choice, device, ISP, time of day, and other traffic confound comparisons. Confirmed labels are declarations, not independent audits. Imported records can lack collection provenance. No causal or nationwide rankings are produced.

The dashboard's latest-5000-record window can contain less than the full seven-day pilot for multiple devices; pagination retains access to older database records. No AI recommendations are generated. Demo records are generated separately in dashboard memory and never uploaded. Automated tests isolate their mocked fixtures in temporary databases.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests cover health, SQLite persistence and pagination, malformed payloads, missing/zero values, medians, verification exclusions, chart construction, HTTP failures, and Streamlit navigation/filter/import/error interactions. Mocked test results stay in temporary databases. A separate real localhost ICMP/DNS check may be skipped when the OS prohibits ping sockets; no automated test contacts the external approved target. See `tests/`.

## 2–3 minute recording flow

- **0:00–0:25 — Overview:** introduce NetPulse as a limited pilot; explain backend responsiveness versus the last successful observation. Show the actual KPI values or their honest empty states.
- **0:25–0:55 — Collection workspace:** show the background collector and received observation freshness. If you have a genuine measured observation, enter its real timestamp, metrics, and verification source; save it and show persistence. Never type illustrative numbers as real results.
- **0:55–1:30 — Comparison:** show available verified categories, medians, and per-metric counts. State that small pilots do not establish a universally superior medium. With one/no categories, explain what data is missing.
- **1:30–2:00 — History:** adjust date and medium filters; open the metric tabs and latency distribution. Explain a blank metric versus measured zero. With no data, show the labeled empty states.
- **2:00–2:30 — Methodology:** explain verified labels, controlled targets, sample sizes, privacy, and limited conclusions. Describe the implemented device collector; state that AI integration remains future work.
- **2:30–2:45 — Reliability:** optionally stop the backend and refresh to show the handled error state; restart it to show recovery. End with the next step: more consenting devices with confirmed labels under comparable conditions.

## Files

- `agent/`: approved probe configuration, ICMP/DNS measurement, scheduled runtime, durable queue, and upload adapter.
- `scripts/launcher.py` and the three `.bat` files: startup/setup/stop automation.
- `backend/`: shared payload models, FastAPI routes, SQLite storage.
- `dashboard/`: API client, pure analytics, Plotly charts, Streamlit UI.
- `.streamlit/config.toml`: local dark theme and server defaults.
- `tests/`: backend, analytics, API-client, and dashboard interaction tests.

No deployments, commits, or pushes are performed by setup or test commands.

## Original plan status

Before this stage, the dashboard, validated import API, SQLite storage, charts, and their tests were complete on `work`. The older agent existed only on `main` with an incompatible schema; automatic scheduling, durable upload retry, and automatic refresh were missing. This stage adapts that agent to the working API, adds scheduled collection and retries, and preserves the dashboard design. Active-interface detection and participant confirmation are implemented, but independent verification, central hosting, and AI assistance remain outside this stage. Native Windows startup and ICMP behavior require a local Windows check; Linux/cloud capability limitations are not replaced with mock telemetry.

## AIORI-3 PS-014 presentation mode

Use the **Demo Mode** toggle in the sidebar (OFF by default). ON shows the prominent
**DEMO MODE — ILLUSTRATIVE DATA, NOT REAL MEASUREMENTS** banner on every page.
The fixed seed generates 420 fictional observations for 12 fictional participants
across 5–11 January 2026 (UTC), with Wi-Fi, Ethernet and Mobile data categories.
Mobile data uses the existing `Cellular` schema value internally; the demo UI uses
its friendlier display name. Providers are fictional; locations are broad categories.
Values vary by participant and time of day and intentionally include missing metrics.
Labels remain unverified. Demo comparisons explicitly opt into fictional categories;
real comparisons still require declared verification.

Demo generation performs no network requests, uploads or database writes. The app
still checks backend health honestly; the illustrative dashboard works when the API
is unavailable. Imports are unavailable in demo mode to prevent accidental uploads.
The genuine background collector continues independently. Switch OFF to show only
API observations, including an honest empty or unavailable state. Filters have separate
state between the two modes. The fixed dates do not pretend to be current telemetry.

Overview adds participant counts, latest attempt time, average loss, daily loss,
DNS/throughput boxes, RTT boxes, count charts and missing-data coverage. Historical
Trends supports daily medians with quartiles and counts in hover details, or individual
points, alongside date/medium/participant filters. Comparison shows median RTT,
Q25/Q75 (the interquartile range), other metric medians, participant/sample counts
and the percentage missing any metric. Repeated observations are not independent
participants; neither fictional patterns nor this limited pilot establish superiority,
national representativeness or causation.

Launch from the project root in Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501
```

For a short presentation: enable Demo Mode and explain the banner; show Overview
coverage and hover details; compare categories with sample counts and RTT quartiles;
filter Historical Trends by participant and date; explain missing versus zero in
Methodology; switch Demo Mode OFF to demonstrate the separate genuine-data path.
Never describe fictional records as verified observations.
