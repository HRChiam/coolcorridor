"""Person 1's results numbers, printed from the heat model's outputs.

  1. Hottest links at 1pm       top 10 walked links by heat score, with minutes above
                                the comfort line (7am-7pm); saved to data/hottest_links_1pm.csv
  2. Shade coverage at 1pm      share of the walking network's length in shade, today
                                and after the budget's fixes (Person 2's data/priorities.csv)
  3. Pipeline check             model error vs the simulated sensors, before and after
                                correction (data/sensor_pipeline_check.csv). NOT validation.

Heat is the sensor-corrected score where the correction has run, else the model.
Run last (run_all.py does):  .venv/Scripts/python heat_model/results.py
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from heat import COMFORT_C, HOURS
from tag_links import household_use

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HOUR = 13


def best_heat(links, hour):
    """Sensor-corrected heat at that hour if the correction has run, else the model."""
    corrected = f"heat_corr_h{hour:02d}"
    return links[corrected] if corrected in links else links[f"heat_h{hour:02d}"]


def shade_coverage(shade, length_m):
    """Share of network length in shade (each link's shade is its shaded share)."""
    return float(np.sum(np.asarray(shade) * np.asarray(length_m)) / np.sum(length_m))


def shade_after_fixes(links, fixes, interventions, hour=HOUR):
    """Shade per link after the fixes; a fix blocks shade_gain of the remaining sun."""
    shade = links.set_index("link_id")[f"shade_h{hour:02d}"].copy()
    gain = fixes.merge(interventions[["fix", "shade_gain"]], on="fix", how="left")
    gain = gain.set_index("link_id").shade_gain.fillna(0).groupby(level=0).max()
    shade.loc[gain.index] = shade.loc[gain.index] + (1 - shade.loc[gain.index]) * gain
    return shade


def hottest_links(links):
    """Top 10 walked links at 1pm; heat ties are broken by household walking distance."""
    heat = pd.DataFrame({h: best_heat(links, h) for h in HOURS})
    links = links.assign(heat_1pm=heat[HOUR], minutes_above_comfort=(heat > COMFORT_C).sum(axis=1) * 60)
    places = gpd.read_file(DATA / "places.geojson")
    links["household_m"] = household_use(links, places).values * links.length_m
    walked = links[links.household_m > 0]
    top = walked.sort_values(["heat_1pm", "household_m"], ascending=False).head(10)
    top = top[["link_id", "name", "highway", "length_m", "surface", "canopy", "covered",
               f"shade_h{HOUR}", "heat_1pm", "minutes_above_comfort"]]
    top.insert(0, "rank", range(1, len(top) + 1))
    return top


def main():
    links = gpd.read_file(DATA / "links.geojson")
    corrected = f"heat_corr_h{HOUR}" in links
    print("=== Person 1 results ===")

    top = hottest_links(links)
    top.to_csv(DATA / "hottest_links_1pm.csv", index=False)
    print(f"\n1. Hottest walked links at 1pm ({'sensor-corrected' if corrected else 'model'} heat score, °C; "
          f"minutes above the {COMFORT_C:.0f}°C comfort line, 7am-7pm)")
    print(top[["rank", "link_id", "name", "surface", "heat_1pm", "minutes_above_comfort"]].to_string(index=False))

    today = shade_coverage(links[f"shade_h{HOUR}"], links.length_m)
    print(f"\n2. Shade coverage at 1pm: {today:.1%} of the walking network's length "
          f"({links.length_m.sum() / 1000:.1f} km) is in shade today")
    priorities_path = DATA / "priorities.csv"
    if priorities_path.exists():
        fixes = pd.read_csv(priorities_path)
        shade = shade_after_fixes(links, fixes, pd.read_csv(DATA / "interventions.csv"))
        after = shade_coverage(shade.values, links.set_index("link_id").length_m.loc[shade.index].values)
        print(f"   After the budget's fixes ({len(fixes)} fixes, RM {fixes.cost_rm.sum():,.0f}, "
              f"from Person 2's priorities.csv): {after:.1%} ({100 * (after - today):+.1f} points)")
    else:
        print("   After the budget's fixes: waiting for Person 2's data/priorities.csv")

    check_path = DATA / "sensor_pipeline_check.csv"
    if check_path.exists():
        all_ = pd.read_csv(check_path, index_col=0).loc["all"]
        print(f"\n3. Pipeline check (NOT validation: the sensors are simulated from our own assumptions): "
              f"model error vs simulated sensors {all_.error_before:.2f} °C before correction, "
              f"{all_.error_after:.2f} °C after")
    else:
        print("\n3. Pipeline check: waiting for Person 3's data/sensors_stream.csv")


if __name__ == "__main__":
    main()
