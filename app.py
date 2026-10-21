"""Local CoolCorridor Streamlit app. Run: python -m streamlit run app.py"""

import streamlit as st
import pandas as pd

import engine
from app_data import source_day, shared_directory_matches
from cool_route import (
    ROUTE_LABELS, build_route_map, comparison_metrics, comparison_table,
    default_place_ids, fetch_routes, load_places,
)
from heat_map import (
    HOURS, build_heat_map, heat_summary, legend_html, load_heat_data,
    replay_date, sensor_snapshot,
)
from sensors_dashboard import render_sensors
from planner import render_planner


@st.fragment
def render_heat_map() -> None:
    st.subheader("Heat across the walking network")
    st.write("Explore modelled heat on actual walking links around Putra Heights LRT Station.")
    st.info("The heat score is a modelled index incorporating sun, shade, surfaces and wind. "
            "It is not measured air temperature. Sensor readings shown here are SIMULATED.")
    hour = st.select_slider("Heat Map replay hour", options=list(HOURS), value=14,
                            format_func=lambda h: f"{h:02d}:00", key="heat_hour")
    try:
        links = load_heat_data(hour)
        date = replay_date(hour)
        summary = heat_summary(links)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        st.error(f"Heat network unavailable: {exc}")
        return
    corrected = links.attrs["sensor_corrected"]
    if corrected:
        st.warning("This Heat Map uses corrected heat. Cool Route and Planner currently use the uncorrected baseline; "
                   "coordinate corrected-heat support with Person 2 before comparing their results.")
    st.caption(f"Design-day replay: {date} · {hour:02d}:00 Asia/Kuala_Lumpur. "
               + ("Sensor-corrected model heat; corrections may use simulated readings."
                  if corrected else "Uncorrected model heat — sensor correction outputs are unavailable for this hour."))
    avg, hottest, shade_metric, count = st.columns(4)
    avg.metric("Average link heat index", f"{summary['average']:.2f} °C")
    hottest.metric("Hottest walking link", f"{summary['hottest']:.2f} °C")
    shade_metric.metric("Network shade", f"{summary['shade']:.1%}")
    count.metric("Walking links", f"{summary['count']:,}")
    st.caption(f"Average heat gives each link equal weight. Shade is weighted by link length. "
               f"Hottest: {summary['hottest_id']} ({summary['ties']} tied link(s); lowest ID shown). "
               "Summaries cover the entire network; overlay toggles do not filter them.")
    st.markdown(legend_html(), unsafe_allow_html=True)
    st.caption("Fixed heat-index scale: 26–44°C at every hour. Values outside the scale use its end colors.")
    covered_col, canopy_col, shade_col = st.columns(3)
    covered = covered_col.checkbox("Covered walkways · blue outline", key="heat_covered")
    canopy = canopy_col.checkbox("Tree canopy · green outline", key="heat_canopy")
    shade = shade_col.checkbox("Shade · grey outline", key="heat_shade")
    try:
        sensors = sensor_snapshot(hour, date)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.warning(f"Sensor overlay unavailable: {exc}")
        sensors = pd.DataFrame(columns=["sensor_id", "link_id", "position", "air_temp_c", "rh_pct",
                                         "surface_temp_c", "status", "site_type", "timestamp"])
    if not sensors.empty:
        if sensors.attrs.get("stream_available", False):
            st.caption("SIMULATED sensor snapshots: latest same-day reading at or before the selected hour. "
                       "A reading up to five minutes old is labelled stale; older readings are withheld. "
                       "Purple dots have readings; grey dots have no recent reading. Hover for values and timestamps.")
        else:
            st.warning("Simulated sensor stream unavailable. Site locations remain visible without readings.")
    try:
        deck = build_heat_map(links, sensors, covered=covered, canopy=canopy, shade=shade)
    except (ValueError, TypeError, KeyError) as exc:
        st.error(f"Heat map could not be prepared: {exc}")
        return
    st.pydeck_chart(deck, height=600, key="heat_network_map",
                    alt="Walking network colored by modelled heat index with eight simulated sensor sites")
    st.caption("Hover a link for its heat index, shade, covered status, canopy and surface. "
               "Outlines highlight existing attributes; the central line keeps its heat color. "
               "Canopy is a link-level estimate, not a map of individual trees. "
               "This replay does not use today's forecast. Restart the app after shared model files change.")


@st.fragment
def render_cool_route() -> None:
    st.subheader("A cooler walk to your destination")
    st.write("Compare the shortest walk with a route that reduces modelled heat exposure.")
    try:
        places = load_places()
        default_origin, default_destination = default_place_ids(places)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        st.error(f"Places could not be loaded: {exc}")
        return
    if not shared_directory_matches(engine.DATA_DIR):
        st.error("Cool Route disabled: the engine data directory differs from the other tabs. Use one shared repository data bundle.")
        return

    place_ids = places.place_id.tolist()
    by_id = places.set_index("place_id")

    def place_label(place_id):
        row = by_id.loc[place_id]
        return f"{row['label']} · {row['kind']} ({place_id})"

    origin_column, destination_column, time_column = st.columns([2, 2, 1])
    with origin_column:
        origin_id = st.selectbox("From", place_ids, index=place_ids.index(default_origin),
                                 format_func=place_label, key="route_origin")
    with destination_column:
        destination_id = st.selectbox("To", place_ids, index=place_ids.index(default_destination),
                                      format_func=place_label, key="route_destination")
    with time_column:
        hour = st.select_slider("Departure time", options=list(engine.HOURS), value=14,
                                format_func=lambda h: f"{h:02d}:00", key="route_hour")

    try:
        route_date = source_day(engine.DATA_DIR, (hour,))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        st.error(f"Route heat/weather data unavailable: {exc}")
        return
    st.caption(f"Design-day replay: {route_date} · Asia/Kuala_Lumpur · "
               f"Cool routes allow up to {(engine.MAX_COOLER_DETOUR - 1) * 100:.0f}% extra distance.")
    st.caption("UNCORRECTED MODEL heat: the routing engine reads heat_h07–heat_h19. "
               "It currently does not use sensor-corrected columns.")
    try:
        with st.spinner("Comparing walking routes…"):
            routes, errors = fetch_routes(places, origin_id, destination_id, hour)
    except ValueError as exc:
        st.warning(str(exc))
        return
    for mode, error in errors.items():
        st.warning(f"{ROUTE_LABELS[mode]} unavailable: {error}")
    if not routes:
        st.info("No route results are available. Try different places or check the local data files.")
        return

    if len(routes) == 2:
        comparison = comparison_metrics(routes)
        heat_column, sun_column, distance_column = st.columns(3)
        heat_column.metric("Heat exposure avoided", f"{comparison['heat_avoided']:.3f} °C·min")
        sun_column.metric("Sun exposure avoided", f"{comparison['sun_minutes_avoided']:.2f} min")
        distance_column.metric("Extra walking distance", f"{comparison['extra_distance_m']:+.1f} m",
                               delta=f"{comparison['extra_distance_pct']:+.2f}% distance", delta_color="off")
        st.caption(f"Coolest versus shortest: {comparison['extra_walking_min']:+.2f} minutes walking.")
        if (routes["shortest"].get("link_ids")
                and routes["shortest"]["link_ids"] == routes["coolest"].get("link_ids")):
            st.info("Both options follow the same walking links. No cooler alternative was found "
                    "within the allowed detour at this time.")
        elif comparison["heat_avoided"] <= 0:
            st.info("The returned routes have no reduction in modelled heat exposure at this time.")
    else:
        st.info("Only one route is available; a shortest-versus-coolest comparison cannot be calculated.")

    first, second = st.columns(2)
    show_shortest = first.checkbox("Show shortest route (orange, wider line)", value=True,
                                   disabled="shortest" not in routes)
    show_coolest = second.checkbox("Show coolest route (green, narrower line)", value=True,
                                   disabled="coolest" not in routes)
    visible = tuple(mode for mode, show in (("shortest", show_shortest), ("coolest", show_coolest)) if show)
    if not any(mode in routes for mode in visible):
        st.info("Both route lines are hidden. Enable a route above to see its walking path.")
    origin = by_id.loc[origin_id].to_dict()
    destination = by_id.loc[destination_id].to_dict()
    st.pydeck_chart(build_route_map(routes, origin, destination, visible), height=520,
                    key="cool_route_map", alt="Shortest and coolest walking paths with origin and destination markers")
    st.caption("Orange: shortest · Green: coolest · O: origin · D: destination. "
               "Shared links show green over a wider orange line. Hover for route metrics; drag or zoom to explore. "
               "Markers show place locations; walking paths start and end at the engine’s nearest network junctions.")

    st.subheader("Route comparison")
    st.dataframe(comparison_table(routes).round(3), width="stretch")
    st.caption(f"Sun exposure weights walking time by the unshaded share of each link. "
               f"Heat exposure is walking minutes × degrees above the assumed {engine.COMFORT_C:g}°C comfort line. "
               f"Walking speed is assumed to be {engine.WALKING_METRES_PER_MIN:g} m/min. "
               "These are model estimates, not measured air temperature or health outcomes.")


def main() -> None:
    st.set_page_config(page_title="CoolCorridor · Walking with less heat", page_icon="🌿", layout="wide")
    st.title("CoolCorridor")
    st.caption("Putra Heights · Walking with less heat")
    if not shared_directory_matches(engine.DATA_DIR):
        st.error("Engine data override differs from the repository data used by Heat Map and Sensors. "
                 "Remove COOLCORRIDOR_DATA_DIR for this app or coordinate one shared data directory with the team.")
    route_tab, heat_tab, sensors_tab, planner_tab = st.tabs(
        ["Cool Route", "Heat Map", "Sensors", "Planner"], default="Sensors")
    with route_tab:
        render_cool_route()
    with heat_tab:
        render_heat_map()
    with sensors_tab:
        render_sensors()
    with planner_tab:
        render_planner()


if __name__ == "__main__":
    main()
