"""Heat model step 3: hourly weather and sun position, 7am to 7pm.

Picks one recent clear, hot day from the Open-Meteo archive (the "design day"
that the heat map and sensors replay), plus today's forecast, and adds the sun's
elevation and azimuth from pvlib. Writes data/weather.csv, one row per day+hour:
  day (design | forecast), date, hour, air_temp_c, rh_pct, wind_ms,
  sw_wm2 (sunlight on flat ground), sun_elev_deg, sun_azim_deg (0 = north, clockwise)

Run:  .venv/Scripts/python heat_model/weather.py [--date YYYY-MM-DD]
"""

import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pvlib
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LAT, LON = 2.99605, 101.57558
TZ = "Asia/Kuala_Lumpur"
HOURS = range(7, 20)
LOOKBACK_DAYS = 60
ARCHIVE_LAG_DAYS = 5  # the newest archive days are forecast-filled; skip them

HOURLY = "temperature_2m,relative_humidity_2m,wind_speed_10m,shortwave_radiation_instant"
COMMON = {"latitude": LAT, "longitude": LON, "timezone": TZ, "wind_speed_unit": "ms"}


def get(url, **params):
    r = requests.get(url, params={**COMMON, **params}, timeout=60)
    r.raise_for_status()
    return r.json()


def pick_design_day():
    """Among the sunniest quarter of recent days, take the hottest."""
    end = date.today() - timedelta(days=ARCHIVE_LAG_DAYS)
    start = end - timedelta(days=LOOKBACK_DAYS)
    d = get("https://archive-api.open-meteo.com/v1/archive", start_date=start, end_date=end,
            daily="temperature_2m_max,shortwave_radiation_sum,precipitation_sum")["daily"]
    days = pd.DataFrame(d)
    sunny = days[days.shortwave_radiation_sum >= days.shortwave_radiation_sum.quantile(0.75)]
    best = sunny.sort_values("temperature_2m_max", ascending=False).iloc[0]
    print(f"Design day {best.time}: max {best.temperature_2m_max}°C, "
          f"sun {best.shortwave_radiation_sum} MJ/m², rain {best.precipitation_sum} mm "
          f"(sunniest quarter of {len(days)} days, hottest of those)")
    return best.time


def hourly(url, label, **params):
    h = pd.DataFrame(get(url, hourly=HOURLY, **params)["hourly"])
    h["time"] = pd.to_datetime(h["time"]).dt.tz_localize(TZ)
    h = h[h.time.dt.hour.isin(HOURS)].copy()
    sun = pvlib.solarposition.get_solarposition(h.time, LAT, LON)
    return pd.DataFrame({
        "day": label,
        "date": h.time.dt.date.astype(str),
        "hour": h.time.dt.hour,
        "air_temp_c": h.temperature_2m,
        "rh_pct": h.relative_humidity_2m,
        "wind_ms": h.wind_speed_10m,
        "sw_wm2": h.shortwave_radiation_instant,
        "sun_elev_deg": sun["apparent_elevation"].round(2).values,
        "sun_azim_deg": sun["azimuth"].round(2).values,
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="use this design day instead of picking one")
    args = parser.parse_args()

    design_date = args.date or pick_design_day()
    design = hourly("https://archive-api.open-meteo.com/v1/archive", "design",
                    start_date=design_date, end_date=design_date)
    today = date.today().isoformat()
    forecast = hourly("https://api.open-meteo.com/v1/forecast", "forecast", start_date=today, end_date=today)

    weather = pd.concat([design, forecast], ignore_index=True)
    weather.to_csv(DATA / "weather.csv", index=False)
    print(design.drop(columns=["day", "date"]).to_string(index=False))
    print(f"Wrote weather.csv (design {design_date}, forecast {today})")


if __name__ == "__main__":
    main()
