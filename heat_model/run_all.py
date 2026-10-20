"""Re-run the heat model from the hand tags onward, in order, stopping at the first error.

  apply_tags -> link_flags -> weather -> shade -> heat -> sensor_correction (once
  Person 3's data/sensors_stream.csv exists) -> results

pull_area.py and tag_links.py are one-off steps and are not re-run here.

Run:  .venv/Scripts/python heat_model/run_all.py
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"

STEPS = ["apply_tags.py", "link_flags.py", "weather.py", "shade.py", "heat.py"]


def main():
    steps = STEPS + (["sensor_correction.py"] if (DATA / "sensors_stream.csv").exists() else []) + ["results.py"]
    for step in steps:
        print(f"\n=== {step} ===", flush=True)
        if subprocess.run([sys.executable, str(HERE / step)], cwd=HERE).returncode != 0:
            sys.exit(f"{step} failed; later steps not run.")
    if "sensor_correction.py" not in steps:
        print("\nSkipped sensor_correction.py: no data/sensors_stream.csv yet (Person 3).")


if __name__ == "__main__":
    main()
