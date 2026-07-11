# windguru-bridge

Serverless bridge that publishes live measurements from the **Araca Project**
weather station to [WindGuru](https://stations.windguru.cz/), every 15 minutes,
with zero infrastructure.

<!-- Once you know your WindGuru station number, link it here: -->
**Live data:** https://www.windguru.cz/station/XXXX

## What it does

```
METER ZL6 datalogger + ATMOS 41 sensor  (measures every 15 min)
        │
        ▼
ZENTRA Cloud  (receives telemetry)
        │   REST API v4
        ▼
GitHub Actions  (this repo — scheduled run every 15 min)
        │   unit conversion + MD5-authenticated GET
        ▼
WindGuru station  (public live data + AI-tuned local forecast)
```

Each scheduled run:

1. pulls the most recent readings from the ZENTRA Cloud API;
2. converts units (m/s → knots, kPa → hPa, station pressure → mean sea level);
3. authenticates with WindGuru's salt + MD5 scheme;
4. uploads wind (avg/gust/direction), temperature, humidity, rainfall and
   pressure, timestamped at the true measurement time.

Uploads older than 2 h are skipped automatically (WindGuru rejects them), and a
keepalive step prevents GitHub from pausing the schedule in quiet periods.

## Why

The Araca Project monitors a 120-hectare site in the mountain region of
Rio de Janeiro, Brazil. Publishing the station's data lets anyone use it — and
once enough history accumulates, WindGuru's machine-learning correction
produces a forecast tuned to this exact location.

## Repository layout

| File | Purpose |
|---|---|
| `windguru_bridge.py` | The bridge script (Python, stdlib + `requests`) |
| `.github/workflows/windguru.yml` | 15-minute schedule on GitHub Actions |

## Running your own

Fork it, then create these repository **Actions secrets**:

| Secret | Value |
|---|---|
| `ZENTRA_TOKEN` | ZENTRA Cloud API token (API → Keys) |
| `ZENTRA_DEVICE_SN` | Logger serial number, e.g. `z6-12345` |
| `WINDGURU_UID` | Station UID from [WindGuru registration](https://stations.windguru.cz/register.php?id_type=16) |
| `WINDGURU_PASSWORD` | API password set at registration |
| `STATION_ELEVATION_M` | Station elevation in meters (optional; enables sea-level pressure) |

Enable Actions, run the workflow once manually to test, and you're live.
No secrets ever appear in the code or logs.

---

*Maintained by the Araca Project.*
