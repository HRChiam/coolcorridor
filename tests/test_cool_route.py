"""Real routing integration and Streamlit interactions; no shared output writes."""

import copy
import json
from pathlib import Path
import sys

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cool_route
import engine


@pytest.fixture(scope="module")
def real_routes():
    places = cool_route.load_places()
    origin_id, destination_id = cool_route.default_place_ids(places)
    routes, errors = cool_route.fetch_routes(places, origin_id, destination_id, 14)
    assert not errors
    return places, routes


def app():
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)


def test_defaults_use_real_shop_and_station(real_routes):
    places, routes = real_routes
    assert len(places) == 66
    origin_id, destination_id = cool_route.default_place_ids(places)
    indexed = places.set_index("place_id")
    assert indexed.loc[origin_id, "name"] == "99 Speedmart"
    assert indexed.loc[origin_id, "kind"] == "shop"
    assert indexed.loc[destination_id, "name"] == "SP31 KJ37 Putra Heights"
    assert indexed.loc[destination_id, "label"] == "Putra Heights LRT Station"
    assert indexed.loc["P034", "label"].endswith("(opens Feb 2027)")
    assert all(r["hour"] == 14 for r in routes.values())


def test_real_geometry_and_metrics_match_network_without_writes(real_routes):
    places, routes = real_routes
    paths = [ROOT / "engine.py", *(ROOT / "heat_model").glob("*.py"), *(ROOT / "data").glob("*")]
    before = {p: p.read_bytes() for p in paths if p.is_file()}
    # Independent read of frozen link geometries and hourly properties.
    network = json.loads((engine.DATA_DIR / "links.geojson").read_text(encoding="utf-8"))
    links = {f["properties"]["link_id"]: f for f in network["features"]}
    for mode, route in routes.items():
        expected = [links[lid] for lid in route["link_ids"]]
        # Shapely emits tuples; GeoJSON on disk contains equivalent JSON lists.
        actual_geometry = json.loads(json.dumps([f["geometry"] for f in route["geometry"]["features"]]))
        assert actual_geometry == [f["geometry"] for f in expected]
        distance = sum(f["properties"]["length_m"] for f in expected)
        sun = sum(f["properties"]["length_m"] / engine.WALKING_METRES_PER_MIN
                  * (1 - f["properties"]["shade_h14"]) for f in expected)
        heat = sum(f["properties"]["length_m"] / engine.WALKING_METRES_PER_MIN
                   * max(0, f["properties"]["heat_h14"] - engine.COMFORT_C) for f in expected)
        assert route["distance_m"] == pytest.approx(distance, abs=0.005)
        assert route["walking_time_min"] == pytest.approx(distance / engine.WALKING_METRES_PER_MIN, abs=0.00051)
        assert route["minutes_in_sun"] == pytest.approx(sun, abs=0.00051)
        assert route["heat_exposure"] == pytest.approx(heat, abs=0.00051)
        paths_for_map = cool_route.route_paths(route, mode)
        assert [r["path"] for r in paths_for_map] == [f["geometry"]["coordinates"] for f in expected]
    assert routes["coolest"]["distance_m"] <= routes["shortest"]["distance_m"] * engine.MAX_COOLER_DETOUR
    assert routes["coolest"]["heat_exposure"] < routes["shortest"]["heat_exposure"]
    for path, content in before.items():
        assert path.read_bytes() == content


def test_map_contains_real_paths_endpoints_and_visibility_controls(real_routes):
    places, routes = real_routes
    by_id = places.set_index("place_id")
    origin = by_id.loc["P043"].to_dict()
    destination = by_id.loc["P066"].to_dict()
    deck = json.loads(cool_route.build_route_map(routes, origin, destination).to_json())
    layers = {layer["id"]: layer for layer in deck["layers"]}
    assert layers["route-shortest"]["@@type"] == "PathLayer"
    assert layers["route-coolest"]["@@type"] == "PathLayer"
    assert layers["route-shortest"]["getWidth"] > layers["route-coolest"]["getWidth"]
    assert layers["places"]["data"][0]["position"] == [origin["lon"], origin["lat"]]
    assert layers["places"]["data"][1]["position"] == [destination["lon"], destination["lat"]]
    assert deck["initialViewState"]["longitude"] > 101
    hidden = json.loads(cool_route.build_route_map(routes, origin, destination, ("coolest",)).to_json())
    assert "route-shortest" not in {layer["id"] for layer in hidden["layers"]}
    assert "route-coolest" in {layer["id"] for layer in hidden["layers"]}


def test_comparison_values_match_engine_results(real_routes):
    _, routes = real_routes
    table = cool_route.comparison_table(routes)
    assert table.loc["Distance (m)", "Shortest route"] == routes["shortest"]["distance_m"]
    assert table.loc["Walking time (min)", "Coolest route"] == routes["coolest"]["walking_time_min"]
    summary = cool_route.comparison_metrics(routes)
    assert summary["heat_avoided"] == pytest.approx(routes["coolest"]["heat_avoided"], abs=0.001)
    assert summary["extra_distance_pct"] == pytest.approx(routes["coolest"]["extra_distance_pct"], abs=0.005)


@pytest.mark.parametrize("origin,destination,hour", [
    ("P043", "P043", 14), ("missing", "P066", 14), ("P043", "P066", 20),
    ("P043", "P066", 14.5),
])
def test_invalid_selection_never_calls_engine(monkeypatch, origin, destination, hour):
    def unexpected(*args, **kwargs):
        pytest.fail("Engine must not be called for invalid selections")
    monkeypatch.setattr(engine, "route", unexpected)
    with pytest.raises(ValueError):
        cool_route.fetch_routes(cool_route.load_places(), origin, destination, hour)


@pytest.mark.parametrize("damage", ["no_result", "no_geometry", "no_metrics", "nan_metric"])
def test_missing_or_invalid_route_results_are_reported(monkeypatch, real_routes, damage):
    places, routes = real_routes
    result = copy.deepcopy(routes["shortest"])
    if damage == "no_result":
        result = None
    elif damage == "no_geometry":
        result["geometry"]["features"] = []
    elif damage == "no_metrics":
        del result["heat_exposure"]
    else:
        result["distance_m"] = float("nan")
    monkeypatch.setattr(engine, "route", lambda *args, **kwargs: result)
    actual, errors = cool_route.fetch_routes(places, "P043", "P066", 14)
    assert not actual
    assert set(errors) == {"shortest", "coolest"}


def test_app_default_calls_both_real_modes_and_displays_metrics(monkeypatch, real_routes):
    _, routes = real_routes
    original = engine.route
    calls = []
    def tracked(origin, destination, hour, mode):
        calls.append((origin, destination, hour, mode))
        return original(origin, destination, hour, mode)
    monkeypatch.setattr(engine, "route", tracked)
    at = app().run()
    assert not at.exception
    assert calls == [("P043", "P066", 14, "shortest"), ("P043", "P066", 14, "coolest")]
    assert at.selectbox(key="route_origin").value == "P043"
    assert at.selectbox(key="route_destination").value == "P066"
    assert at.select_slider(key="route_hour").value == 14
    assert at.get("deck_gl_json_chart")
    assert len(at.dataframe) == 1
    pd.testing.assert_frame_equal(at.dataframe[0].value, cool_route.comparison_table(routes).round(3))
    assert at.metric[0].value.startswith("6.782")


def test_app_time_and_place_changes_show_current_results():
    at = app().run()
    at.select_slider(key="route_hour").set_value(7).run()
    assert not at.exception
    assert at.metric[0].value.startswith("0.000")
    assert any("same walking links" in message.value for message in at.info)
    at.selectbox(key="route_origin").select("P051").run()
    assert not at.exception
    expected = engine.route("P051", "P066", 7, "shortest")
    assert at.dataframe[0].value.loc["Distance (m)", "Shortest route"] == expected["distance_m"]
    at.select_slider(key="route_hour").set_value(19).run()
    assert not at.exception
    assert at.metric[0].value.startswith("0.000")


def test_app_invalid_selection_clears_previous_map():
    at = app().run()
    at.selectbox(key="route_origin").select("P066").run()
    assert not at.exception
    assert any("different origin" in message.value for message in at.warning)
    assert not at.get("deck_gl_json_chart")
    assert not at.dataframe


def test_app_no_routes_and_partial_results(monkeypatch, real_routes):
    _, routes = real_routes
    monkeypatch.setattr(engine, "route", lambda *args, **kwargs: None)
    at = app().run()
    assert not at.exception
    assert len(at.warning) == 2
    assert any("No route results" in message.value for message in at.info)
    assert not at.get("deck_gl_json_chart")

    def partial(origin, destination, hour, mode):
        if mode == "coolest":
            raise ValueError("No connected walking path")
        return routes["shortest"]
    monkeypatch.setattr(engine, "route", partial)
    at = app().run()
    assert not at.exception
    assert at.get("deck_gl_json_chart")
    assert list(at.dataframe[0].value.columns) == ["Shortest route"]
    assert any("Only one route" in message.value for message in at.info)


def test_app_missing_places_file(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "DATA_DIR", tmp_path)
    at = app().run()
    assert not at.exception
    assert any("Places could not be loaded" in message.value for message in at.error)
    assert not at.selectbox


def test_layer_units_are_literal_strings_with_bounded_pixel_sizes(real_routes):
    """Bare 'pixels' serializes as an accessor, causing invalid shader sizes."""
    places, routes = real_routes
    by_id = places.set_index("place_id")
    deck = json.loads(cool_route.build_route_map(
        routes, by_id.loc["P043"].to_dict(), by_id.loc["P066"].to_dict()).to_json())
    layers = {layer["id"]: layer for layer in deck["layers"]}
    for name in ("route-shortest", "route-coolest"):
        assert layers[name]["widthUnits"] == "pixels"
        assert layers[name]["widthMaxPixels"] <= 12
        assert 0 < layers[name]["getWidth"] <= layers[name]["widthMaxPixels"]
    assert layers["places"]["radiusUnits"] == "pixels"
    assert 0 < layers["places"]["getRadius"] <= layers["places"]["radiusMaxPixels"] <= 16
    assert layers["place-labels"]["sizeUnits"] == "pixels"
    assert layers["place-labels"]["getTextAnchor"] == "middle"
    assert layers["place-labels"]["getAlignmentBaseline"] == "center"
    for layer in layers.values():
        # Geospatial viewport defaults to LNGLAT across deck.gl versions.
        assert "coordinateSystem" not in layer


def test_map_coordinates_and_viewport_are_geographic(real_routes):
    import geopandas as gpd

    places, routes = real_routes
    links = gpd.read_file(engine.DATA_DIR / "links.geojson")
    assert links.crs.to_epsg() == 4326
    by_id = places.set_index("place_id")
    deck = json.loads(cool_route.build_route_map(
        routes, by_id.loc["P043"].to_dict(), by_id.loc["P066"].to_dict()).to_json())
    west, south, east, north = links.total_bounds
    for layer in deck["layers"]:
        for row in layer["data"]:
            coordinates = row["path"] if "path" in row else [row["position"]]
            for lon, lat in coordinates:
                assert west <= lon <= east
                assert south <= lat <= north
    view = deck["initialViewState"]
    assert west <= view["longitude"] <= east
    assert south <= view["latitude"] <= north
    assert 10 <= view["zoom"] <= 18
    assert deck["mapProvider"] == "carto"
    assert deck["mapStyle"] == cool_route.pdk.map_styles.CARTO_LIGHT


def test_projected_place_input_is_transformed_to_epsg4326(tmp_path):
    from pyproj import Transformer

    original = cool_route.load_places()
    payload = json.loads((engine.DATA_DIR / "places.geojson").read_text(encoding="utf-8"))
    transformer = Transformer.from_crs(4326, 3857, always_xy=True)
    for feature in payload["features"]:
        feature["geometry"]["coordinates"] = list(transformer.transform(*feature["geometry"]["coordinates"]))
    payload["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
    path = tmp_path / "projected.geojson"
    path.write_text(json.dumps(payload), encoding="utf-8")
    actual = cool_route.load_places(path)
    assert actual.lon.to_numpy() == pytest.approx(original.lon.to_numpy(), abs=1e-9)
    assert actual.lat.to_numpy() == pytest.approx(original.lat.to_numpy(), abs=1e-9)


@pytest.mark.parametrize("coordinates", [[3, 101], [11000000, 300000], [float("nan"), 3]])
def test_bad_route_coordinate_order_or_projection_is_rejected(real_routes, coordinates):
    _, routes = real_routes
    route = copy.deepcopy(routes["shortest"])
    route["geometry"]["features"][0]["geometry"]["coordinates"] = [coordinates, coordinates]
    with pytest.raises(ValueError, match="longitude/latitude"):
        cool_route.route_paths(route, "shortest")


def test_identical_routes_keep_distinct_colors_and_draw_order():
    places = cool_route.load_places()
    routes, errors = cool_route.fetch_routes(places, "P043", "P066", 7)
    assert not errors
    assert routes["shortest"]["link_ids"] == routes["coolest"]["link_ids"]
    by_id = places.set_index("place_id")
    # Even reversed input must put the wider orange path below narrow green.
    deck = json.loads(cool_route.build_route_map(
        dict(reversed(list(routes.items()))), by_id.loc["P043"].to_dict(), by_id.loc["P066"].to_dict()).to_json())
    shortest, coolest = deck["layers"][:2]
    assert shortest["id"] == "route-shortest"
    assert coolest["id"] == "route-coolest"
    assert shortest["getColor"] != coolest["getColor"]
    assert shortest["getWidth"] > coolest["getWidth"]
    assert [r["path"] for r in shortest["data"]] == [r["path"] for r in coolest["data"]]
