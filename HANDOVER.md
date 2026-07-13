# Weather Station → WindGuru: System Documentation & Handover

**System:** Automatic publication of Araca weather station data to WindGuru
**Built:** July 2026, by Yan Hess, with technical assistance from Claude (Anthropic's AI assistant), which designed the architecture and wrote the code
**Status:** In production since 11 July 2026
**Audience:** Anyone who needs to understand, maintain, fix, or shut down this system without prior context.

---

## 1. What this system does, in one paragraph

The Araca station (METER ZL6 logger + ATMOS 41 sensor) measures weather every
15 minutes and sends it to ZENTRA Cloud (METER's platform). This system copies
that data, once per hour, to WindGuru — a public weather portal. Publishing
there has two benefits: anyone can see the station's live data, and after
months of accumulated history WindGuru's machine-learning produces a weather
forecast tuned specifically to the station's location, improving predictions
for the reserve. The system runs entirely on free cloud services; no computer
at Araca is involved.

## 2. The moving parts

| Component | What it is | Account/where |
|---|---|---|
| Weather station | ZL6 logger + ATMOS 41, measures every 15 min | Physical, at the reserve |
| ZENTRA Cloud | Receives the station's data (US server) | zentracloud.com — araca.project.br(at)gmail.com |
| GitHub repository | Holds the code and runs it on demand | github.com/AracaProject/windguru-bridge |
| cron-job.org | Free scheduler; tells GitHub to run the code every hour | console.cron-job.org — y.hess(at)antonelli-foundations.org |
| WindGuru station | Public page showing the data | stations.windguru.cz, station "RPPN Alto..." (UID stored as a GitHub secret) |

## 3. How data flows

1. Station measures every 15 min → uploads to ZENTRA Cloud automatically
   (METER's own system, independent of ours).
2. Every hour, cron-job.org sends an authenticated request to GitHub's API
   saying "run the workflow now".
3. GitHub runs `windguru_bridge_batch.py` on a temporary Linux machine
   (20–40 seconds). The script downloads the recent readings from ZENTRA
   Cloud's API, converts units (wind to knots, pressure to sea-level hPa),
   and uploads each 15-minute observation of the last 2 hours to WindGuru,
   each stamped with the real measurement time.
4. WindGuru displays the data. Duplicate uploads overwrite the same point,
   so the hourly overlap causes no errors and no gaps.

## 4. Credentials — where every secret lives

No passwords or tokens appear in the code. They are stored in two places:

**GitHub repository secrets** (repo → Settings → Secrets and variables →
Actions): `ZENTRA_TOKEN` (ZENTRA Cloud API key), `ZENTRA_DEVICE_SN` (logger
serial), `WINDGURU_UID` + `WINDGURU_PASSWORD` (WindGuru station credentials),
`STATION_ELEVATION_M` (station elevation).

**cron-job.org** (inside the cronjob's settings): a GitHub "fine-grained
personal access token". It can do only one thing — start workflows in this
one repository — so its leak risk is minimal.

Losing access to accounts: ZENTRA credentials can be re-issued at
zentracloud.com; WindGuru password can be reset via the station owner's
WindGuru account; the GitHub token can be regenerated at GitHub → Settings →
Developer settings → Fine-grained tokens.

## 5. Routine maintenance (the only recurring task)

**Once a year, before 12 July 2027:** the GitHub token and the cron-job.org
schedule both expire. Renewal takes ~5 minutes:

1. GitHub → Settings → Developer settings → Fine-grained tokens → regenerate
   the `cronjob-dispatch` token (same settings: only this repo, Actions
   read & write).
2. cron-job.org → the "WindGuru batch trigger" job → paste the new token in
   the Authorization header, as: `Bearer <token>` (the word Bearer, a space,
   then the token).
3. Extend the job's expiry date another year.
4. Test: the job's "test run" button should return status **204**, and a new
   run should appear at github.com/AracaProject/windguru-bridge/actions.

## 6. If something breaks — quick diagnosis

| Symptom | Likely cause | Fix |
|---|---|---|
| cron-job.org emails "execution failed", status 401 | GitHub token expired or header malformed | Section 5 |
| Runs appear in GitHub Actions but are red | Open the run log; the script prints its error | Log says 401/403 from ZENTRA → renew `ZENTRA_TOKEN` secret. Log says "Wrong hash"/not OK from WindGuru → `WINDGURU_UID`/`WINDGURU_PASSWORD` secrets wrong |
| Runs green but WindGuru shows no new data | WindGuru side or wrong UID | Check station page login on stations.windguru.cz |
| No data in ZENTRA Cloud itself | Station/connectivity problem at the reserve | Hardware/METER support — outside this system |
| Gap on WindGuru graph longer than 2 h | Any outage lasting >2 h (WindGuru refuses old data) | Nothing to fix retroactively; ZENTRA Cloud keeps the complete record — nothing is scientifically lost |

## 7. Known limitations and future risks

- **2-hour backfill limit** is WindGuru's rule, not ours. Outages >2 h leave
  permanent holes on WindGuru only; ZENTRA Cloud always has the full data.
- **ZENTRA API version:** the script uses ZENTRA's API v4. METER launched
  ZENTRA Cloud 2.0 (API v5) in 2026; if v4 is ever retired the script's
  fetch function will need updating — everything else stays the same.
- **GitHub account quirk:** this GitHub account has a partial restriction
  (cannot download third-party "marketplace actions", and GitHub's built-in
  scheduler ran unreliably). The system was designed around both: the
  workflow uses only plain commands, and scheduling is external. A support
  ticket was filed in July 2026; if resolved, nothing needs to change.
- **Free-tier dependence:** GitHub Actions and cron-job.org free tiers are
  generous for this workload (24 short runs/day), but policies can change.
  The design is portable: any machine that can run Python + send two HTTPS
  requests can replace it (see `windguru_bridge_batch.py`, ~200 lines).

## 8. How to shut the system down

Disable or delete the cronjob at cron-job.org — that alone stops everything.
Optionally: disable the workflow on GitHub (Actions → ••• → Disable), revoke
the GitHub token, and delete the WindGuru station via its owner account.
Nothing about the station→ZENTRA flow is affected; that is METER's system.

## 9. Brief history (for context)

Built 10–13 July 2026. Notable decisions: WindGuru chosen over Weather
Underground/Windy because it is the only platform generating a
station-tuned forecast (the project's goal for the 120 ha reserve);
GitHub Actions chosen for zero cost; batch upload + external hourly
scheduler adopted after GitHub's native 15-minute schedule proved
unreliable on this account. The AI assistant Claude designed the
architecture, wrote all code, and diagnosed the deployment issues; Yan Hess
executed all account setup, reviewed changes, and holds all credentials.
