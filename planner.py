"""Read-only presentation of Person 2's investment planning and what-if APIs."""

import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pydeck as pdk
from pydeck.types import String
import streamlit as st

import engine
from cool_route import _coordinate
from app_data import design_day, validate_heat_weather, shared_directory_matches

BENEFIT_UNIT = "person·°C·min/day"
FIX_LABELS = {"shade_trees": "Shade trees", "shade_sail": "Shade sail",
              "covered_walkway": "Covered walkway", "cool_paving": "Cool paving"}
FIX_COLORS = {"shade_trees": [30, 137, 85], "shade_sail": [216, 104, 31],
              "covered_walkway": [124, 73, 175], "cool_paving": [30, 120, 192]}
ERRORS = (OSError, ValueError, TypeError, KeyError, RuntimeError)


def validate_budget(value):
    if isinstance(value, (bool, str)):
        raise ValueError("Budget must be a finite nonnegative number in RM")
    budget = float(value)
    if not math.isfinite(budget) or budget < 0:
        raise ValueError("Budget must be a finite nonnegative number in RM")
    return budget


def input_signature():
    """Invalidate read-only app caches when engine inputs change; no global setters."""
    paths = [Path(engine.__file__)] + [Path(engine.DATA_DIR) / name for name in
              ("links.geojson", "places.geojson", "weather.csv", "interventions.csv")]
    return tuple((str(p.resolve()), p.stat().st_mtime_ns, p.stat().st_size) for p in paths)


def load_planning_data(data_dir=None):
    directory = Path(engine.DATA_DIR if data_dir is None else data_dir)
    links = gpd.read_file(directory / "links.geojson")
    if links.empty or links.crs is None:
        raise ValueError("Walking network must be nonempty and declare its CRS")
    links = links.to_crs(4326)
    required = {"link_id", "length_m", "albedo"} | {f"heat_h{h:02d}" for h in engine.HOURS}
    if not required.issubset(links):
        raise ValueError(f"Walking network missing fields: {sorted(required - set(links.columns))}")
    if links.link_id.isna().any() or links.link_id.duplicated().any():
        raise ValueError("Walking link IDs must be present and unique")
    links["link_id"] = links.link_id.astype(str)
    for col in required - {"link_id"}:
        links[col] = pd.to_numeric(links[col], errors="raise")
        if not np.isfinite(links[col]).all():
            raise ValueError(f"Walking network has invalid {col}")
    if (links.length_m <= 0).any() or not links.albedo.between(0, 1).all():
        raise ValueError("Link lengths must be positive and albedo must be in 0..1")
    if links.geometry.isna().any() or links.geometry.is_empty.any():
        raise ValueError("Walking network contains missing geometry; coordinate the shared input with Person 1")
    fixes = pd.read_csv(directory / "interventions.csv")
    required_fixes = {"fix", "cost_rm_per_m", "shade_gain", "albedo_gain", "note"}
    if fixes.empty or not required_fixes.issubset(fixes):
        raise ValueError("Interventions must supply fix, cost_rm_per_m, shade_gain, albedo_gain and note")
    if fixes.fix.isna().any() or fixes.fix.duplicated().any():
        raise ValueError("Intervention names must be present and unique")
    for col in ("cost_rm_per_m", "shade_gain", "albedo_gain"):
        fixes[col] = pd.to_numeric(fixes[col], errors="raise")
        if not np.isfinite(fixes[col]).all() or (fixes[col] < 0).any():
            raise ValueError(f"Invalid intervention {col}")
    if (fixes.cost_rm_per_m <= 0).any():
        raise ValueError("Intervention costs must be positive")
    return links, fixes


def validate_recommendations(result, budget, links, fixes):
    """Check allocation independently before labelling it selected within budget."""
    budget = validate_budget(budget)
    if not isinstance(result, pd.DataFrame) or not set(engine.PRIORITY_COLUMNS).issubset(result):
        raise ValueError("Engine returned missing or incomplete recommendation fields")
    table = result.copy(deep=True)
    if not table.link_id.isin(links.link_id).all() or not table.fix.isin(fixes.fix).all():
        raise ValueError("Engine returned an unknown link or unsupported intervention")
    if table.link_id.duplicated().any():
        raise ValueError("Engine selected more than one intervention for a link")
    for col in ("rank", "cost_rm", "heat_drop", "person_min_saved_day", "benefit_per_rm"):
        table[col] = pd.to_numeric(table[col], errors="raise")
        if not np.isfinite(table[col]).all() or (table[col] < 0).any():
            raise ValueError(f"Engine returned invalid {col}")
    if table["rank"].tolist() != list(range(1, len(table) + 1)):
        raise ValueError("Engine ranks must be consecutive in selection order")
    if (table.cost_rm <= 0).any() or (table.person_min_saved_day <= 0).any():
        raise ValueError("Selected interventions must have positive costs and benefits")
    spent = math.fsum(table.cost_rm)
    if spent > budget + 1e-7:
        raise ValueError("Engine selection exceeds the budget; allocation cannot be presented as funded")
    for attr, expected in (("budget_rm", budget), ("spent_rm", spent)):
        if attr in table.attrs and not math.isclose(float(table.attrs[attr]), expected, abs_tol=1e-7):
            raise ValueError(f"Engine {attr} disagrees with the checked allocation")
    summary = {"spent": spent, "remaining": max(0.0, budget - spent),
               "benefit": math.fsum(table.person_min_saved_day), "count": len(table)}
    return table, summary


@st.cache_data(show_spinner=False, max_entries=32)
def _cached_priorities(budget, signature):
    return engine.priorities(budget)


def fetch_recommendations(budget, links, fixes):
    budget = validate_budget(budget)
    validate_heat_weather(links, design_day(Path(engine.DATA_DIR) / "weather.csv"), engine.HOURS)
    return validate_recommendations(_cached_priorities(budget, input_signature()), budget, links, fixes)


def preview_table(result):
    if not isinstance(result, dict):
        raise ValueError("Engine returned no intervention preview")
    rows = []
    for hour in engine.HOURS:
        key = f"h{hour:02d}"
        row = {"Hour": f"{hour:02d}:00"}
        for phase in ("before", "after"):
            state = result[phase]
            heat = float(state["heat_by_hour"][key])
            shade = float(state["shade_by_hour"][key])
            albedo = float(state["albedo"])
            if not all(math.isfinite(v) for v in (heat, shade, albedo)) or not (0 <= shade <= 1 and 0 <= albedo <= 1):
                raise ValueError("Engine preview contains invalid heat, shade or albedo")
            row[f"{phase.title()} heat index (°C)"] = heat
            row[f"{phase.title()} shade (%)"] = shade * 100
        rows.append(row)
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False, max_entries=64)
def _cached_preview(link_id, fix, signature):
    return engine.apply_fix(link_id, fix)


def fetch_preview(link_id, fix, links, fixes):
    if link_id not in set(links.link_id) or fix not in set(fixes.fix):
        raise ValueError("Choose a real walking link and a supported intervention")
    validate_heat_weather(links, design_day(Path(engine.DATA_DIR) / "weather.csv"), engine.HOURS)
    result = _cached_preview(link_id, fix, input_signature())
    if not isinstance(result, dict) or result.get("link_id") != link_id or result.get("fix") != fix:
        raise ValueError("Engine preview is missing or belongs to a different selection")
    preview_table(result)
    for key in ("cost_rm", "heat_drop", "person_min_saved_day", "benefit_per_rm", "area_before", "area_after"):
        value = float(result[key])
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Engine preview contains invalid {key}")
    if result.get("area_units") != "person-degree-C-minutes above comfort threshold per day":
        raise ValueError("Engine preview exposure units are missing or unsupported")
    return result


def planning_paths(links, recommendations):
    selected = recommendations.set_index("link_id").to_dict("index")
    base, highlighted, skipped = [], [], []
    for row in links.itertuples():
        geometry = row.geometry
        if geometry is None or geometry.is_empty or geometry.geom_type not in ("LineString", "MultiLineString"):
            skipped.append(row.link_id)
            continue
        parts = [geometry] if geometry.geom_type == "LineString" else geometry.geoms
        try:
            paths = [[_coordinate(list(c)) for c in part.coords] for part in parts]
            if any(len(path) < 2 for path in paths):
                raise ValueError("Incomplete line")
        except (ValueError, TypeError):
            skipped.append(row.link_id)
            continue
        option = selected.get(row.link_id)
        for path in paths:
            record = {"path": path, "title": row.link_id, "detail": "Walking network · no selected investment"}
            base.append(record)
            if option:
                highlighted.append({**record, "color": FIX_COLORS.get(option["fix"], [20, 140, 155]),
                    "title": f"#{option['rank']:g} · {row.link_id} · {FIX_LABELS.get(option['fix'], option['fix'])}",
                    "detail": f"Selected within budget · RM {option['cost_rm']:,.2f}\n"
                              f"Modelled saving: {option['person_min_saved_day']:,.3f} {BENEFIT_UNIT}\n"
                              f"13:00 heat-index drop: {option['heat_drop']:.4f} °C\n"
                              f"Benefit/RM: {option['benefit_per_rm']:.5f} {BENEFIT_UNIT}/RM"})
    if not base:
        raise ValueError("No valid walking-link geometry is available for the investment map")
    return base, highlighted, skipped


def build_planner_map(base, highlighted):
    layers = []
    for name, data, width, color in (("network", base, 2, [160, 168, 177]),
                                      ("selected", highlighted, 6, "color")):
        layers.append(pdk.Layer("PathLayer", id=f"planner-{name}", data=data,
            get_path="path", get_color=color, get_width=width,
            width_units=String("pixels"), width_min_pixels=1, width_max_pixels=10,
            cap_rounded=True, joint_rounded=True, pickable=True))
    view = pdk.data_utils.compute_view([p for row in base for p in row["path"]])
    view.zoom = min(18, max(10, view.zoom - .7))
    return pdk.Deck(layers=layers, initial_view_state=view, map_provider="carto",
                    map_style=pdk.map_styles.CARTO_LIGHT, tooltip={"text": "{title}\n{detail}"})


def recommendation_table(table):
    display = table.copy()
    display["fix"] = display["fix"].map(lambda f: FIX_LABELS.get(f, f))
    display["Selection"] = "Selected within budget (proposal)"
    return display.rename(columns={"rank": "Rank", "link_id": "Link", "fix": "Intervention",
        "cost_rm": "Cost (RM)", "heat_drop": "13:00 heat-index drop (°C)",
        "person_min_saved_day": f"Saving ({BENEFIT_UNIT})", "benefit_per_rm": f"Benefit/RM ({BENEFIT_UNIT}/RM)"})


@st.fragment
def render_planner():
    st.subheader("Township Cooling Investment Planner")
    if not shared_directory_matches(engine.DATA_DIR):
        st.error("Planner disabled: the engine data directory differs from the other tabs. Use one shared repository data bundle.")
        return
    st.info("MODELLED / SIMULATED BENEFITS — planning estimates, not verified cooling, measured air temperature "
            "or health outcomes. Costs and walking demand are assumptions.")
    budget = st.number_input("Investment budget (RM)", min_value=0.0, value=100000.0,
                             step=1000.0, format="%.2f", key="planner_budget")
    try:
        links, fixes = load_planning_data()
        with st.spinner("Ranking actual walking-link interventions…"):
            table, summary = fetch_recommendations(budget, links, fixes)
        base, highlighted, skipped = planning_paths(links, table)
    except ERRORS as exc:
        st.error(f"Planner unavailable: {exc}")
        return
    st.caption("Baseline: uncorrected model heat (heat_h07–heat_h19). The planning engine currently ignores "
               "heat_corr columns even if present. Sensor corrections are not applied by this tab.")
    spent, remaining, count = st.columns(3)
    spent.metric("Selected investment", f"RM {summary['spent']:,.2f}")
    remaining.metric("Remaining budget", f"RM {summary['remaining']:,.2f}")
    count.metric("Selected links", str(summary["count"]))
    st.metric(f"Modelled daily exposure saving ({BENEFIT_UNIT})", f"{summary['benefit']:,.3f}")
    st.caption("Total selected costs were checked against the budget. These are proposed investments, "
               "not installed works. The engine returns only funded selections; it does not expose an unfunded shortlist.")
    if table.empty:
        st.info("No positive-benefit intervention fits this budget. No investments have been manufactured.")
    st.pydeck_chart(build_planner_map(base, highlighted), height=500, key="planner_map",
                    alt="Real Putra Heights walking network with budget-selected cooling interventions")
    st.markdown(" · ".join(["Grey: walking network"] + [
        f'<span style="color:rgb{tuple(color)}">■ {FIX_LABELS[key]}</span>' for key, color in FIX_COLORS.items()]),
        unsafe_allow_html=True)
    if skipped:
        st.warning(f"Geometry unavailable or invalid for {len(skipped)} links; omitted from map only: " + ", ".join(skipped))
    st.subheader("Budget-selected recommendations")
    st.dataframe(recommendation_table(table), hide_index=True, width="stretch")
    with st.expander("How ranking, benefits and costs work"):
        st.write("Person 2's engine sorts link/fix candidates by daily exposure saving per RM, then benefit, "
                 "cost and link ID. It greedily accepts positive-benefit candidates that fit the remaining budget, "
                 "with at most one fix per link. This is not a guaranteed global optimum.")
        st.write(f"Benefit sums assumed walkers × walking minutes × reduction in degrees above the "
                 f"{engine.COMFORT_C:g}°C comfort line across 07:00–19:00. Units are {BENEFIT_UNIT}, "
                 "not minutes or person-minutes. The engine's person_min_saved_day field uses this exposure unit. "
                 "Heat-index drop refers only to 13:00; it is not an all-day average.")
        st.write("Radiation caveat: the current engine averages weather.csv rows by hour, including design-day "
                 "and forecast rows. Baseline heat is from the design day. Coordinate weather filtering and "
                 "corrected-heat support with Person 2 before treating these projections as design-day calibrated.")
        st.dataframe(fixes, hide_index=True, width="stretch")
    st.subheader("Read-only intervention preview")
    st.caption("Explore one link independently of the budget selection. Previewing does not add it to the plan "
               "or change source files. Press Preview after changing a selection.")
    ids = links.link_id.tolist()
    default_link = table.link_id.iloc[0] if not table.empty else ids[0]
    left, right = st.columns(2)
    link_id = left.selectbox("Walking link", ids, index=ids.index(default_link), key="planner_link")
    fix = right.selectbox("Improvement", fixes.fix.tolist(),
                          format_func=lambda f: FIX_LABELS.get(f, f), key="planner_fix")
    identity = (link_id, fix, input_signature())
    if st.button("Preview intervention", key="planner_preview_button"):
        try:
            with st.spinner("Calculating real engine before/after results…"):
                result = fetch_preview(link_id, fix, links, fixes)
            st.session_state["planner_preview"] = (identity, result)
        except ERRORS as exc:
            st.session_state.pop("planner_preview", None)
            st.warning(f"Preview unavailable: {exc}")
    saved = st.session_state.get("planner_preview")
    if saved and saved[0] == identity:
        result = saved[1]
        a, b, c = st.columns(3)
        a.metric("Preview cost", f"RM {result['cost_rm']:,.2f}")
        b.metric("13:00 modelled heat-index drop", f"{result['heat_drop']:.4f} °C")
        c.metric(f"Preview saving ({BENEFIT_UNIT})", f"{result['person_min_saved_day']:,.3f}")
        st.caption(f"Whole-network daily exposure: {result['area_before']:,.3f} → "
                   f"{result['area_after']:,.3f} {BENEFIT_UNIT}. Only this link changes; "
                   "walking demand is held fixed. Preview is separate from the budget plan.")
        hours = preview_table(result)
        st.line_chart(hours.set_index("Hour")[["Before heat index (°C)", "After heat index (°C)"]],
                      x_label="Hour (Asia/Kuala_Lumpur)", y_label="Modelled heat index (°C)",
                      color=["#ab5a3a", "#228755"])
        st.dataframe(hours, hide_index=True, width="stretch")
        st.caption(f"Albedo before / after: {result['before']['albedo']:.3f} / "
                   f"{result['after']['albedo']:.3f}. Modelled changes use the engine's solar-term difference.")
