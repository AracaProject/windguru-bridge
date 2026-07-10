"""
ZENTRA Cloud (US, API v4) -> WindGuru upload bridge.

Runs on a schedule (e.g., GitHub Actions every 15 min). Each run:
  1. Fetches the most recent readings from ZENTRA Cloud for the device.
  2. Converts units to what WindGuru expects (knots, degC, hPa, mm, %).
  3. Builds the salt + MD5 hash authentication.
  4. Sends the GET request to the WindGuru upload API.

Required environment variables (set as GitHub Actions secrets):
  ZENTRA_TOKEN       ZENTRA Cloud API token (API menu -> Keys -> Copy token)
  ZENTRA_DEVICE_SN   Device serial number, e.g. z6-12345
  WINDGURU_UID       Station UID chosen at WindGuru registration
  WINDGURU_PASSWORD  API password set at WindGuru registration

Optional:
  STATION_ELEVATION_M  Station elevation in meters. If set, station pressure
                       is reduced to mean sea level (WindGuru's 'mslp').
                       If unset, pressure is not uploaded.
"""

import hashlib
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

ZENTRA_URL = "https://zentracloud.com/api/v4/get_readings/"
WINDGURU_URL = "https://www.windguru.cz/upload/api.php"
MAX_AGE_SECONDS = 2 * 3600  # WindGuru rejects data older than 2 hours


def env(name, required=True, default=None):
    v = os.environ.get(name, default)
    if required and not v:
        print(f"ERROR: missing environment variable {name}")
        sys.exit(1)
    return v


# ---------------------------------------------------------------- unit helpers
def to_knots(value, units):
    u = (units or "").strip().lower()
    if "m/s" in u or "mps" in u:
        return value * 1.943844
    if "km/h" in u or "kph" in u:
        return value * 0.539957
    if "mph" in u:
        return value * 0.868976
    if "knot" in u or u == "kn" or u == "kt":
        return value
    # ATMOS 41 native output is m/s; assume m/s if unit string is unrecognized
    print(f"WARNING: unrecognized wind unit '{units}', assuming m/s")
    return value * 1.943844


def to_celsius(value, units):
    u = (units or "").strip().lower()
    if "f" in u and "c" not in u:
        return (value - 32.0) * 5.0 / 9.0
    return value


def to_hpa(value, units):
    u = (units or "").strip().lower()
    if "kpa" in u:
        return value * 10.0
    if "mbar" in u or "hpa" in u:
        return value
    if "atm" in u:
        return value * 1013.25
    print(f"WARNING: unrecognized pressure unit '{units}', assuming kPa")
    return value * 10.0


def to_percent_rh(value, units):
    # ZENTRA sometimes reports RH as a 0-1 fraction
    if value is not None and value <= 1.0:
        return value * 100.0
    return value


def to_mm(value, units):
    u = (units or "").strip().lower()
    if "in" in u:
        return value * 25.4
    return value


def station_to_sea_level_hpa(p_hpa, elevation_m, temp_c):
    """Reduce station pressure to mean sea level (standard barometric formula)."""
    if temp_c is None:
        temp_c = 15.0
    t_k = temp_c + 273.15
    return p_hpa * (1 - (0.0065 * elevation_m) / (t_k + 0.0065 * elevation_m)) ** -5.257


# ------------------------------------------------------------------ ZENTRA pull
def fetch_latest_readings(token, device_sn):
    """Return {measurement_name: (value, units, unix_timestamp)} for the most
    recent reading of each measurement within the last 2 hours."""
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    params = {
        "device_sn": device_sn,
        "start_date": start.strftime("%Y-%m-%d %H:%M"),
        "output_format": "json",
        "sort_by": "descending",
        "per_page": 500,
        "page_num": 1,
    }
    headers = {"Authorization": f"Token {token}"}
    r = requests.get(ZENTRA_URL, params=params, headers=headers, timeout=60)
    if r.status_code == 429:
        print("ZENTRA rate limit hit; will succeed on next scheduled run.")
        sys.exit(0)
    r.raise_for_status()
    payload = r.json()

    data = payload.get("data", {})
    latest = {}
    for measurement, sensors in data.items():
        if not isinstance(sensors, list):
            continue
        for sensor in sensors:
            meta = sensor.get("metadata", {}) or {}
            units = meta.get("units", "")
            for reading in sensor.get("readings", []) or []:
                value = reading.get("value")
                ts = reading.get("timestamp_utc")
                if value is None or ts is None:
                    continue
                if measurement not in latest or ts > latest[measurement][2]:
                    latest[measurement] = (float(value), units, int(ts))
                break  # readings are sorted descending; first valid one is newest
    return latest


def pick(latest, *name_fragments):
    """Find a measurement whose name contains all given fragments (case-insensitive)."""
    for name, triple in latest.items():
        low = name.lower()
        if all(f in low for f in name_fragments):
            return triple
    return None


# ------------------------------------------------------------------- main flow
def main():
    token = env("ZENTRA_TOKEN")
    device_sn = env("ZENTRA_DEVICE_SN")
    uid = env("WINDGURU_UID")
    password = env("WINDGURU_PASSWORD")
    elevation = os.environ.get("STATION_ELEVATION_M")

    latest = fetch_latest_readings(token, device_sn)
    if not latest:
        print("No readings returned by ZENTRA Cloud in the last 2 hours; nothing to upload.")
        sys.exit(0)

    print("Measurements found:", ", ".join(sorted(latest.keys())))

    wind = pick(latest, "wind", "speed")
    gust = pick(latest, "gust")
    wdir = pick(latest, "wind", "direction")
    temp = pick(latest, "air", "temperature")
    rh = pick(latest, "relative", "humidity") or pick(latest, "rh")
    pres = pick(latest, "atmospheric", "pressure") or pick(latest, "barometric")
    precip = pick(latest, "precipitation") or pick(latest, "rain")

    # Timestamp of the observation = newest among core measurements
    timestamps = [t[2] for t in (wind, temp, wdir) if t]
    if not timestamps:
        print("No wind/temperature readings found; nothing to upload.")
        sys.exit(0)
    obs_time = max(timestamps)
    age = int(time.time()) - obs_time
    print(f"Newest observation is {age} s old.")
    if age > MAX_AGE_SECONDS:
        print("Observation older than 2 h; WindGuru would reject it. Skipping upload.")
        sys.exit(0)

    params = {
        "uid": uid,
        "interval": 900,           # 15-minute measurement interval
        "unixtime": obs_time,      # stamp data at measurement time
    }

    temp_c = None
    if temp:
        temp_c = to_celsius(temp[0], temp[1])
        params["temperature"] = round(temp_c, 2)
    if wind:
        params["wind_avg"] = round(to_knots(wind[0], wind[1]), 2)
    if gust:
        params["wind_max"] = round(to_knots(gust[0], gust[1]), 2)
    if wdir:
        params["wind_direction"] = int(round(wdir[0])) % 360
    if rh:
        params["rh"] = round(to_percent_rh(rh[0], rh[1]), 1)
    if precip:
        params["precip"] = round(to_mm(precip[0], precip[1]), 2)
        params["precip_interval"] = 900
    if pres and elevation:
        p_hpa = to_hpa(pres[0], pres[1])
        params["mslp"] = round(
            station_to_sea_level_hpa(p_hpa, float(elevation), temp_c), 1
        )

    # --- WindGuru authentication: salt + md5(salt + uid + password)
    salt = str(int(time.time() * 1000))
    params["salt"] = salt
    params["hash"] = hashlib.md5((salt + uid + password).encode("utf-8")).hexdigest()

    print("Uploading to WindGuru:",
          {k: v for k, v in params.items() if k not in ("hash", "salt")})
    r = requests.get(WINDGURU_URL, params=params, timeout=30)
    body = r.text.strip()
    print(f"WindGuru response [{r.status_code}]: {body}")
    if r.status_code != 200 or body != "OK":
        sys.exit(1)
    print("Upload OK.")


if __name__ == "__main__":
    main()
