"""Heat model step 5: heat score per link per hour, 7am to 7pm, on the design day.

  H = T_air + (1 - s) * R / 1000 * (a + b * (1 - albedo)) - c * w      (°C, our simple index)

s = shade (shade.py), R = sunlight W/m², albedo = surface reflectivity, w = wind m/s.
Writes heat_h07..heat_h19 into data/links.geojson. Any sensor-corrected columns
from an earlier run are removed, since they were built on the old heat; re-run
sensor_correction.py (run_all.py does). The results numbers are in results.py.

For other modules:
  heat_score(...)  the formula itself; Person 2's apply_fix calls it with a changed
                   shade or albedo
  heat_at(hour)    links with shade and heat at that hour, for engine.py

Run after shade.py:  .venv/Scripts/python heat_model/heat.py
"""

from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# Assumptions (copy into the Assumptions table)
A, B, C = 8.0, 4.0, 0.5
COMFORT_C = 32.0  # comfort line, shared with Person 2's heat exposure
HOURS = range(7, 20)
TZ = "Asia/Kuala_Lumpur"


def heat_score(air_temp_c, shade, sw_wm2, albedo, wind_ms):
    """Heat score in °C; works on numbers, numpy arrays or pandas columns."""
    return air_temp_c + (1 - shade) * sw_wm2 / 1000 * (A + B * (1 - albedo)) - C * wind_ms


def design_weather():
    """Design-day weather, one row per hour."""
    weather = pd.read_csv(DATA / "weather.csv")
    return weather[weather.day == "design"].set_index("hour")


@lru_cache(maxsize=1)
def _links():
    return gpd.read_file(DATA / "links.geojson")


def heat_at(hour):
    """Links with `shade` and `heat` (°C) at that hour of the design day.

    `heat` is sensor-corrected once sensor_correction.py has run; `heat_model` is
    the uncorrected score. `unsafe` and `confidence` come from link_flags.py.
    """
    links = _links()
    cols = ["link_id", "u", "v", "name", "length_m", "covered", "canopy", "surface", "albedo"]
    cols += [c for c in ("unsafe", "confidence") if c in links] + ["geometry"]
    out = links[cols].copy()
    out["shade"] = links[f"shade_h{hour:02d}"]
    out["heat_model"] = links[f"heat_h{hour:02d}"]
    corrected = f"heat_corr_h{hour:02d}"
    out["heat"] = links[corrected] if corrected in links else out["heat_model"]
    return out


def main():
    links = gpd.read_file(DATA / "links.geojson")
    weather = design_weather()
    for hour in HOURS:
        w = weather.loc[hour]
        links[f"heat_h{hour:02d}"] = heat_score(
            w.air_temp_c, links[f"shade_h{hour:02d}"], w.sw_wm2, links.albedo, w.wind_ms
        ).round(2)
    stale = [c for c in links.columns if c.startswith("heat_corr_h")]
    links = links.drop(columns=stale)
    links.to_file(DATA / "links.geojson", driver="GeoJSON")

    heat_cols = [f"heat_h{h:02d}" for h in HOURS]
    print("hour  air °C  heat score °C: min / median / max")
    for hour, col in zip(HOURS, heat_cols):
        print(f"{hour:4d}  {weather.loc[hour].air_temp_c:6.1f}  {links[col].min():6.1f} / "
              f"{links[col].median():5.1f} / {links[col].max():5.1f}")
    print("\nWrote heat_h07..heat_h19 to links.geojson"
          + ("; removed the old sensor-corrected columns, re-run sensor_correction.py" if stale else ""))


if __name__ == "__main__":
    main()
