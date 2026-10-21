"""Person 3 read-only checks for the shared design-day data contract."""

from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

from heat_model.heat import heat_score


def shared_directory_matches(path):
    return Path(path).resolve() == (Path(__file__).resolve().parent / "data").resolve()


def design_day(path):
    """Return validated design weather; never fall back to forecast rows."""
    weather = pd.read_csv(Path(path))
    required = {"day", "date", "hour", "air_temp_c", "rh_pct", "sw_wm2", "wind_ms"}
    if not required.issubset(weather):
        raise ValueError("Weather is missing the shared design-day fields")
    weather = weather.loc[weather.day == "design"].sort_values("hour").copy()
    if (weather.date.isna().any() or weather.date.nunique() != 1
            or weather.hour.tolist() != list(range(7, 20))):
        raise ValueError("Design weather must contain one date with hours 07..19 exactly once")
    date = pd.Timestamp(weather.date.iloc[0])
    if pd.isna(date):
        raise ValueError("Design weather date must be valid")
    for column in ("air_temp_c", "rh_pct", "sw_wm2", "wind_ms"):
        weather[column] = pd.to_numeric(weather[column], errors="raise")
        if not np.isfinite(weather[column]).all():
            raise ValueError(f"Design weather contains invalid {column}")
    if (not weather.rh_pct.between(0, 100).all()
            or (weather[["sw_wm2", "wind_ms"]] < 0).any().any()):
        raise ValueError("Design weather humidity must be 0..100; radiation and wind must be nonnegative")
    return weather.set_index("hour")


def validate_heat_weather(links, weather, hours):
    """Detect mismatched exports using Person 1's formula; never replace values."""
    for hour in hours:
        row = weather.loc[hour]
        expected = heat_score(row.air_temp_c, links[f"shade_h{hour:02d}"], row.sw_wm2,
                              links.albedo, row.wind_ms)
        if not np.allclose(links[f"heat_h{hour:02d}"], expected, rtol=0, atol=.00501):
            raise ValueError("Heat and design weather disagree. Ask Person 1 to provide matching outputs; no heat was regenerated")


def source_day(directory, hours):
    """Validate a fresh source snapshot independently of Person 1's cached reader."""
    directory = Path(directory)
    weather = design_day(directory / "weather.csv")
    validate_heat_weather(gpd.read_file(directory / "links.geojson"), weather, hours)
    return str(weather.date.iloc[0])
