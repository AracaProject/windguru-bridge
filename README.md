# windguru-bridge

Publishes live measurements from the **Araca Project** weather station to
[WindGuru](https://stations.windguru.cz/), every hour, with zero
infrastructure and zero cost.

<!-- Add your station number: -->
**Live data:** https://www.windguru.cz/station/16371

## How it works

```
METER ZL6 datalogger + ATMOS 41 sensor   (measures every 15 min)
        │
        ▼
ZENTRA Cloud                             (receives telemetry in real time)
        │  REST API v4
        ▼
GitHub Actions                           (this repo — runs the bridge script)
        ▲                                        │  unit conversion +
        │  triggered hourly via                  │  MD5-authenticated GET,
        │  workflow_dispatch                     ▼  one request per observation
cron-job.org (free scheduler)            WindGuru station
                                         (public data + AI-tuned local forecast)
```

Each run of `windguru_bridge_batch.py`:

1. pulls the last 12 h of readings from the ZENTRA Cloud API (one call);
2. converts units (m/s → knots, kPa → hPa, station → sea-level pressure);
3. uploads every 15-minute observation from the last 2 h as its own request,
   stamped with its true measurement time (`unixtime`). WindGuru rejects
   anything older than 2 h; re-uploading an already-sent timestamp simply
   refreshes the same data point, so overlapping runs are harmless.

**Why an external scheduler?** GitHub's built-in cron proved unreliable on
this account (runs fired hours apart). cron-job.org calls the GitHub API's
`workflow_dispatch` endpoint hourly, which always runs immediately. The
hourly cadence + 2 h upload window means consecutive runs overlap and no
observation is missed.

## Repository layout

| File | Purpose |
|---|---|
| `windguru_bridge_batch.py` | **Active** bridge script (Python, `requests` only) |
| `.github/workflows/windguru-batch.yml` | Workflow triggered by cron-job.org |
| `windguru_bridge.py` | Legacy single-observation script (kept for reference) |
| `.github/workflows/windguru.yml` | Legacy workflow — **disabled** |
| `HANDOVER.md` | Full system documentation and maintenance guide |

## Running your own

Fork it, then create these repository **Actions secrets**
(Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `ZENTRA_TOKEN` | ZENTRA Cloud API token (API → Keys) |
| `ZENTRA_DEVICE_SN` | Logger serial number, e.g. `z6-12345` |
| `WINDGURU_UID` | Station UID from [WindGuru registration](https://stations.windguru.cz/register.php?id_type=16) |
| `WINDGURU_PASSWORD` | API password set at registration |
| `STATION_ELEVATION_M` | Elevation in meters (optional; enables sea-level pressure) |

Trigger the workflow manually from the Actions tab to test, then point any
external scheduler at
`POST /repos/<owner>/<repo>/actions/workflows/windguru-batch.yml/dispatches`
with a fine-grained token (Actions: read & write on this repo only).
No secrets ever appear in the code or logs. See `HANDOVER.md` for details.

---

*Maintained by the Araca Project.*
