"""Cloud entrypoint: verify/extract the frozen runtime, then run the real app."""

import runpy
import sys
from zipfile import BadZipFile

import streamlit as st

from deployment_package import prepare_runtime


def main():
    try:
        runtime = prepare_runtime()
    except (OSError, ValueError, KeyError, TypeError, BadZipFile) as exc:
        st.error(f"Reviewed deployment artifacts are unavailable: {exc}")
        st.info("Restore the approved deployment package and manifest. No model or sensor data was regenerated.")
        st.stop()
    if str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
    runpy.run_path(str(runtime / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
