"""Local CoolCorridor Streamlit app. Run: python -m streamlit run app.py"""

import streamlit as st

import engine
from cool_route import (
    ROUTE_LABELS, build_route_map, comparison_metrics, comparison_table,
    default_place_ids, fetch_routes, load_places,
)


def render_cool_route() -> None:
    st.subheader("A cooler walk to your destination")
    st.write("Compare the shortest walk with a route that reduces modelled heat exposure.")
    try:
        places = load_places()
        default_origin, default_destination = default_place_ids(places)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        st.error(f"Places could not be loaded: {exc}")
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

    st.caption("Design-day replay: 6 September 2026 · Asia/Kuala_Lumpur · "
               f"Cool routes allow up to {(engine.MAX_COOLER_DETOUR - 1) * 100:.0f}% extra distance.")
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
    st.set_page_config(page_title="CoolCorridor · Cool Route", page_icon="🌿", layout="wide")
    st.title("CoolCorridor")
    st.caption("Putra Heights · Walking with less heat")
    with st.tabs(["Cool Route"])[0]:
        render_cool_route()


if __name__ == "__main__":
    main()
