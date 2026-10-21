"""Person 3 read-only checks for the shared design-day data contract."""

from pathlib import Path

import numpy as np
import geopandas as gpd

from heat_model.heat import heat_score
from heat_model.effective import design_weather


def shared_directory_matches(path):
    return Path(path).resolve() == (Path(__file__).resolve().parent / "data").resolve()


def design_day(path):
    """Return validated design weather; never fall back to forecast rows."""
    return design_weather(path)


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


def heat_source_label(metadata):
    """Describe the validated effective model without implying field accuracy."""
    if metadata.get("heat_source") == "corrected":
        return ("Sensor-corrected model heat using SIMULATED data; offline calibration "
                "is not validation against field measurements. "
                f"Correction version: {metadata.get('correction_version', 'unavailable')}.")
    return ("Uncorrected model heat (baseline fallback): no usable activated sensor "
            "correction for this hour or dataset.")
