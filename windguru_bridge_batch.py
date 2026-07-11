"""
ZENTRA Cloud (US, API v4) -> WindGuru upload bridge (batch mode).

Each run fetches ALL readings from the last 2 hours and uploads every
15-minute observation as its own WindGuru request (stamped with its true
measurement time). WindGuru rejects data older than 2 h, so anything a run
can see, it can upload; overlapping uploads across runs are harmless
(same unixtime = same data point updated).

Required env vars (GitHub Actions secrets):
  ZENTRA_TOKEN, ZENTRA_DEVICE_SN, WINDGURU_UID, WINDGURU_PASSWORD
Optional:
  STATION_ELEVATION_M  -> enables sea-level pressure (mslp)
"""

import hashlib
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

ZENTRA_URL = "https://zentracloud.com/api/v4/get_readings/"
WINDGURU_URL = "https://www.windguru.cz/upload/api.php"
MAX_AGE_SECONDS = 2 * 3600 - 120  # WindGuru limit, minus a safety margin


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
    if "knot" in u or u in ("kn", "kt"):
        return value
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
    if value is not None and value <= 1.0:
        return value * 100.0
    return value


def to_mm(value, units):
    u = (units or "").strip().lower()
    if "in" in u:
        return value * 25.4
    return value


def station_to_sea_level_hpa(p_hpa, elevation_m, temp_c):
    if temp_c is None:
        temp_c = 15.0
    t_k = temp_c + 273.15
    return p_hpa * (1 - (0.0065 * elevation_m) / (t_k + 0.0065 * elevation_m)) ** -5.257


# ------------------------------------------------------------------ ZENTRA pull
def fetch_all_readings(token, device_sn):
    """Return {measurement_name: {unix_ts: (value, units)}} for the last 2 h."""
    start = datetime.now(timezone.utc) - timedelta(hours=12)
    params = {
        "device_sn": device_sn,
        "start_date": start.strftime("%Y-%m-%d %H:%M"),
        "output_format": "json",
        "sort_by": "descending",
        "per_page": 1000,
        "page_num": 1,
    }
    headers = {"Authorization": f"Token {token}"}
    r = requests.get(ZENTRA_URL, params=params, headers=headers, timeout=60)
    if r.status_code == 429:
        print("ZENTRA rate limit hit; will succeed on next scheduled run.")
        sys.exit(0)
    r.raise_for_status()
    payload = r.json()
    pag = payload.get("pagination", {})
    if pag:
        print("ZENTRA pagination:", {k: pag.get(k) for k in list(pag)[:8]})
    data = payload.get("data", {})

    series = {}
    for measurement, sensors in data.items():
        if not isinstance(sensors, list):
            continue
        bucket = series.setdefault(measurement, {})
        for sensor in sensors:
            units = (sensor.get("metadata", {}) or {}).get("units", "")
            for reading in sensor.get("readings", []) or []:
                value, ts = reading.get("value"), reading.get("timestamp_utc")
                if value is None or ts is None:
                    continue
                bucket[int(ts)] = (float(value), units)
    return series


def find_series(series, *name_fragments):
    for name, bucket in series.items():
        low = name.lower()
        if all(f in low for f in name_fragments):
            return bucket
    return {}


def at(bucket, ts):
    """Value/units at exact timestamp, tolerating up to 60 s of skew."""
    if ts in bucket:
        return bucket[ts]
    for k, v in bucket.items():
        if abs(k - ts) <= 60:
            return v
    return None


# ------------------------------------------------------------------- main flow
def main():
    token = env("ZENTRA_TOKEN")
    device_sn = env("ZENTRA_DEVICE_SN")
    uid = env("WINDGURU_UID")
    password = env("WINDGURU_PASSWORD")
    elevation = os.environ.get("STATION_ELEVATION_M")

    series = fetch_all_readings(token, device_sn)
    if not series:
        print("No readings returned by ZENTRA Cloud in the last 2 hours.")
        sys.exit(0)

    wind = find_series(series, "wind", "speed")
    gust = find_series(series, "gust")
    wdir = find_series(series, "wind", "direction")
    temp = find_series(series, "air", "temperature")
    rh = find_series(series, "relative", "humidity") or find_series(series, "rh")
    pres = find_series(series, "atmospheric", "pressure") or find_series(series, "barometric")
    precip = find_series(series, "precipitation") or find_series(series, "rain")

    def describe(label, bucket):
        if not bucket:
            print(f"  {label}: 0 readings")
            return
        lo, hi = min(bucket), max(bucket)
        fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%d %H:%M")
        print(f"  {label}: {len(bucket)} readings, {fmt(lo)} -> {fmt(hi)} UTC")

    print("Series returned by ZENTRA (last 12 h requested):")
    describe("wind speed", wind)
    describe("gust", gust)
    describe("air temp", temp)
    describe("pressure", pres)

    now = int(time.time())
    timestamps = sorted(
        ts for ts in set(wind) | set(temp)
        if now - ts <= MAX_AGE_SECONDS
    )
    if not timestamps:
        print("No uploadable observations within WindGuru's 2 h window.")
        sys.exit(0)

    print(f"Uploading {len(timestamps)} observation(s): "
          + ", ".join(datetime.fromtimestamp(t, timezone.utc).strftime('%H:%M') for t in timestamps)
          + " UTC")

    failures = 0
    for i, ts in enumerate(timestamps):
        params = {"uid": uid, "interval": 900, "unixtime": ts}

        temp_c = None
        v = at(temp, ts)
        if v:
            temp_c = to_celsius(v[0], v[1])
            params["temperature"] = round(temp_c, 2)
        v = at(wind, ts)
        if v:
            params["wind_avg"] = round(to_knots(v[0], v[1]), 2)
        v = at(gust, ts)
        if v:
            params["wind_max"] = round(to_knots(v[0], v[1]), 2)
        v = at(wdir, ts)
        if v:
            params["wind_direction"] = int(round(v[0])) % 360
        v = at(rh, ts)
        if v:
            params["rh"] = round(to_percent_rh(v[0], v[1]), 1)
        v = at(precip, ts)
        if v:
            params["precip"] = round(to_mm(v[0], v[1]), 2)
            params["precip_interval"] = 900
        v = at(pres, ts)
        if v and elevation:
            p_hpa = to_hpa(v[0], v[1])
            params["mslp"] = round(
                station_to_sea_level_hpa(p_hpa, float(elevation), temp_c), 1)

        salt = f"{int(time.time() * 1000)}{i}"
        params["salt"] = salt
        params["hash"] = hashlib.md5((salt + uid + password).encode()).hexdigest()

        r = requests.get(WINDGURU_URL, params=params, timeout=30)
        body = r.text.strip()
        stamp = datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M")
        print(f"  {stamp} UTC -> [{r.status_code}] {body}")
        if r.status_code != 200 or body != "OK":
            failures += 1
        time.sleep(1)  # be polite to WindGuru's API

    if failures:
        print(f"{failures} upload(s) failed.")
        sys.exit(1)
    print("All uploads OK.")


if __name__ == "__main__":
    main()
