"""Heat model step 5: heat score per link per hour, 7am to 7pm, on the design day.

  H = T_air + (1 - s) * R / 1000 * (a + b * (1 - albedo)) - c * w      (°C, our simple index)

s = shade (shade.py), R = sunlight W/m², albedo = surface reflectivity, w = wind m/s.
Writes heat_h07..heat_h19 into data/links.geojson and prints the hottest walked
links at 1pm (a results number), also saved to data/hottest_links_1pm.csv.

For other modules:
  heat_score(...)  the formula itself; Person 2's apply_fix calls it with a changed
                   shade or albedo
  heat_at(hour)    links with shade and heat at that hour, for engine.py

Run after shade.py:  .venv/Scripts/python heat_model/heat.py
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd

try:
    from .effective import (clear_effective_cache, design_weather as _design_weather,
                            effective_heat_at, load_effective_links)
except ImportError:  # Keep the documented direct-script invocation working.
    from effective import (clear_effective_cache, design_weather as _design_weather,
                           effective_heat_at, load_effective_links)

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
    """Validated 6 September 2026 weather; forecasts never enter this model."""
    return _design_weather(DATA)


def _links():
    return load_effective_links(DATA)


# Retained for existing integrations that explicitly clear the old reader cache.
_links.cache_clear = clear_effective_cache


def heat_at(hour, data_dir=None):
    """Links with `shade` and `heat` (°C) at that hour of the design day.

    `heat_model` is always the uncorrected index. `heat` uses an activated,
    validated correction bundle, otherwise explicitly labelled baseline heat.
    Corrections use simulated air offsets, never real field measurements.
    """
    if data_dir is not None:
        return effective_heat_at(hour, data_dir)
    return effective_heat_at(hour, DATA, links=_links())


def main():
    from tag_links import household_use  # only needed for the report's ranking

    links = gpd.read_file(DATA / "links.geojson")
    weather = design_weather()
    for hour in HOURS:
        w = weather.loc[hour]
        links[f"heat_h{hour:02d}"] = heat_score(
            w.air_temp_c, links[f"shade_h{hour:02d}"], w.sw_wm2, links.albedo, w.wind_ms
        ).round(2)
    links.to_file(DATA / "links.geojson", driver="GeoJSON")

    heat_cols = [f"heat_h{h:02d}" for h in HOURS]
    print("hour  air °C  heat score °C: min / median / max")
    for hour, col in zip(HOURS, heat_cols):
        print(f"{hour:4d}  {weather.loc[hour].air_temp_c:6.1f}  {links[col].min():6.1f} / "
              f"{links[col].median():5.1f} / {links[col].max():5.1f}")

    # Hottest links at 1pm among links people actually walk; heat ties (e.g. every
    # fully exposed asphalt link) are broken by household walking distance.
    links["minutes_above_comfort"] = (links[heat_cols] > COMFORT_C).sum(axis=1) * 60
    links["household_m"] = household_use(links, gpd.read_file(DATA / "places.geojson")).values * links.length_m
    walked = links[links.household_m > 0]
    hottest = walked.sort_values(["heat_h13", "household_m"], ascending=False).head(10)
    hottest = hottest[["link_id", "name", "highway", "length_m", "surface", "canopy", "covered",
                       "shade_h13", "heat_h13", "minutes_above_comfort"]]
    hottest.insert(0, "rank", range(1, 11))
    hottest.to_csv(DATA / "hottest_links_1pm.csv", index=False)
    print(f"\nHottest walked links at 1pm (comfort line {COMFORT_C:.0f}°C; minutes counted 7am-7pm):")
    print(hottest.to_string(index=False))
    tie = (walked.heat_h13 >= hottest.heat_h13.iloc[-1]).sum()
    print(f"{tie} walked links score at least {hottest.heat_h13.iloc[-1]:.1f}°C at 1pm")
    print("\nWrote heat_h07..heat_h19 to links.geojson and hottest_links_1pm.csv")


if __name__ == "__main__":
    main()
