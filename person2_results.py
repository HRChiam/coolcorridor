"""Person 2's CLI results and CSV export; run from repo root."""
import argparse
from pathlib import Path

import engine


def cool_route_line(label: str, s: dict) -> str:
    return (f"  {label:<26} cooler route for {s['trips_with_cooler_route_pct']:5.1f}% of trips; "
            f"heat avoided {s['mean_heat_avoided_per_improved_trip']:.2f} degree-C-min per improved trip, "
            f"+{s['mean_extra_distance_pct_per_improved_trip']:.1f}% distance, "
            f"{s['mean_sun_minutes_avoided_per_improved_trip']:.2f} fewer minutes in sun")


ILLUSTRATIVE_BUDGETS = (50_000, 100_000, 250_000)


HORIZON_VIEWS = ((1, "next 12 months"), (10, "10 years"))


def money(p) -> str:
    return (f"build RM {p.attrs['spent_rm']:,.0f}, plus RM {p.attrs['upkeep_rm_per_year']:,.0f} a year upkeep "
            f"(10-year total RM {p.attrs['cost_10y_rm']:,.0f})")


def planner_view(budget: float, years: float, label: str) -> None:
    p = engine.priorities(budget, horizon_years=years)
    cut = p.attrs["area_before"] - p.attrs["area_after"]
    fixes = ", ".join(f"{n} {fix}" for fix, n in p["fix"].value_counts().items()) or "none"
    print(f"  {label:<15} {fixes}; {money(p)}; average cut over the period "
          f"-{cut:,.0f} person-degree-C-min/day (-{100 * cut / p.attrs['area_before']:.1f}%)")


def upkeep_sensitivity() -> None:
    """Do sails stay the best value over 10 years if upkeep is half or double our estimate?"""
    print("\nUPKEEP SENSITIVITY (10 years; every possible fix ranked by benefit per RM of 10-year total cost)")
    firsts, sails_beat_trees = [], []
    for scale in (0.5, 1.0, 2.0):
        options = engine.fix_options(10, upkeep_scale=scale)
        top = options.sort_values("value_10y", ascending=False).head(10)
        by_link = options.pivot_table(index="link_id", columns="fix", values="value_10y")
        both = by_link.dropna(subset=["shade_sail", "shade_trees"])
        share = (both.shade_sail > both.shade_trees).mean()
        mix = ", ".join(f"{n} {fix}" for fix, n in top["fix"].value_counts().items())
        firsts.append(top.iloc[0]["fix"])
        sails_beat_trees.append(share)
        print(f"  upkeep x{scale:g}: best value {top.iloc[0]['fix']}; top 10: {mix}; "
              f"sails beat trees on {share:.0%} of {len(both)} links")
    if min(sails_beat_trees) == 1:
        print("  -> With our assumed costs, sails beat trees on every link even if upkeep is double our estimate")
    if len(set(firsts)) == 1:
        print(f"  -> {firsts[0]} is the best 10-year value in all three runs")
    else:
        print(f"  -> The best 10-year value changes with upkeep ({' / '.join(firsts)} at x0.5 / x1 / x2): "
              "confirm real upkeep costs first in a pilot")


def budget_levels(years: float) -> None:
    """Headline planner results at three illustrative budgets, with the marginal gain."""
    print(f"\nBUDGET LEVELS ({years:g}-year view; illustrative; the app's slider covers any amount)")
    previous = None
    for budget in ILLUSTRATIVE_BUDGETS:
        p = engine.priorities(budget, horizon_years=years)
        cut = p.attrs["area_before"] - p.attrs["area_after"]
        fixes = ", ".join(f"{n} {fix}" for fix, n in p["fix"].value_counts().items())
        line = (f"  RM {budget:>7,}: -{cut:,.0f} person-degree-C-min/day "
                f"(-{100 * cut / p.attrs['area_before']:.1f}%), {cut / p.attrs['spent_rm']:.4f} per RM spent; {fixes}")
        if previous:
            extra_cut, extra_rm = cut - previous[0], p.attrs["spent_rm"] - previous[1]
            line += f"; the extra RM {extra_rm:,.0f} removes {extra_cut / extra_rm:.4f} per RM"
        print(line)
        previous = (cut, p.attrs["spent_rm"])


def comfort_test(budget: float) -> None:
    """Re-run the headline numbers with the comfort line at 30, 32 and 34 C."""
    original = engine.COMFORT_C
    print("\nCOMFORT-LINE TEST (all-day coolest routes; planner at the same budget)")
    try:
        for comfort in (30.0, 32.0, 34.0):
            engine.COMFORT_C = comfort
            s = engine.route_summary()
            p = engine.priorities(budget)
            cut = p.attrs["area_before"] - p.attrs["area_after"]
            print(f"  {comfort:.0f}C: cooler route for {s['trips_with_cooler_route_pct']:5.1f}% of trips; "
                  f"area-wide {p.attrs['area_before']:,.0f} -> {p.attrs['area_after']:,.0f} "
                  f"(-{100 * cut / p.attrs['area_before']:.1f}%); top fix {p.iloc[0]['fix']} on {p.iloc[0]['link_id']}")
    finally:
        engine.COMFORT_C = original


def main() -> None:
    parser = argparse.ArgumentParser(description="COOLNEX routing and planner outputs")
    parser.add_argument("--budget", type=float, default=100000,
                        help="Budget in RM (ASSUMED until team agrees)")
    parser.add_argument("--data", type=Path, default=None, help="Path to repo's data folder")
    parser.add_argument("--embed-flow", action="store_true",
                        help="Update flow_day and flow_hNN fields in data/links.geojson (your branch only)")
    parser.add_argument("--comfort-test", action="store_true",
                        help="Also re-run the headline numbers with the comfort line at 30 and 34 C")
    parser.add_argument("--horizon", type=float, default=engine.DEFAULT_HORIZON_YEARS,
                        help="Planner horizon in years for priorities.csv (the app offers 1 and 10)")
    args = parser.parse_args()
    if args.data:
        engine.set_data_dir(args.data)

    print("COOLNEX Person 2 | Planning indicators")
    print("IMPORTANT: Demand, prices, comfort limit and pedestrian speed are modelling assumptions.")
    print("Heat values are Person 1 modelled (may include simulated-sensor corrections).\n")
    print("ASSUMPTIONS TABLE (not empirical measurements)")
    assumptions = [
        ("Comfort threshold", f"{engine.COMFORT_C} C", "Team build plan"),
        ("Walking speed", f"{engine.WALKING_METRES_PER_MIN} metres/min", "Modelling assumption"),
        ("Max detour", f"coolest {(engine.MAX_COOLER_DETOUR - 1)*100:.0f}%, "
                       f"balanced {(engine.MAX_BALANCED_DETOUR - 1)*100:.0f}%", "Team build plan"),
        ("Routing penalty lambdas", ", ".join(map(str, engine.LAMBDA_VALUES)), "Team build plan"),
        ("Unsafe links", f"skipped; x{engine.UNSAFE_COST_FACTOR:g} cost only if a place is cut off", "Team build plan"),
        ("Trip rates per household/day", str(engine.TRIPS_PER_HOUSEHOLD), "Modelling assumption"),
        ("Planner budget", f"RM {args.budget:,.2f}", "Team must choose"),
        ("Planner horizon", f"{args.horizon:g} years (app toggle: 12 months or 10 years)", "Design choice"),
        ("Intervention prices, timing, upkeep", "See data/interventions.csv", "Unverified assumptions"),
    ]
    for label, value, source in assumptions:
        print(f"  {label}: {value} [{source}]")
    print()
    demand = engine.walking_demand()
    print(f"Walking flow assigned: {len(demand)} walking links")
    print(f"Sum of link traversals across area: {demand.flow_day.sum():,.1f} per day (not unique trips)")
    if args.embed_flow:
        path = engine.save_flow_to_links()
        print(f"Added flow_day and hourly flows to {path}")

    print("\nCOOL ROUTES (home to nearest LRT, shop, park and community place)")
    day = engine.route_summary()
    one_pm = engine.route_summary(hour=13)
    print(cool_route_line("Coolest, 7am-7pm:", day))
    print(cool_route_line("Coolest, 1pm:", one_pm))
    print(cool_route_line("Balanced, 7am-7pm:", engine.route_summary(mode="balanced")))
    print(cool_route_line("Balanced, 1pm:", engine.route_summary(hour=13, mode="balanced")))
    print(f"  Home-to-destination pairs tested: {day['evaluated_home_destination_pairs']}; "
          f"trips that need an unsafe link: {day['trips_needing_unsafe_link_pct']}%")
    print("  Of trips with any heat exposure on the shortest route (only these can be improved):")
    for label, s in (("7am-7pm", day), ("1pm", one_pm)):
        print(f"    {label}: {s['trips_with_heat_exposure_pct']:.1f}% of trips are exposed; "
              f"{s['exposed_trips_with_cooler_route_pct']:.1f}% of those have a cooler route")
    wide = engine.route_summary(hour=13, max_detour=1.30)
    print(f"  Sensitivity check, detour cap 30% instead of 25% (1pm): cooler route for "
          f"{wide['trips_with_cooler_route_pct']:.1f}% of trips "
          f"({wide['exposed_trips_with_cooler_route_pct']:.1f}% of exposed trips)")

    ranks = engine.save_priorities(args.budget, horizon_years=args.horizon)
    print(f"\nTOWNSHIP PLANNER (building budget RM {args.budget:,.2f}; benefits over {args.horizon:g} years)")
    print("Benefits count each fix's time to take effect; results use OUR ASSUMED COSTS (data/interventions.csv).")
    print(f"Area-wide exposure before: {ranks.attrs['area_before']:,.2f} person-degree-C-min/day")
    print(f"Area-wide exposure after (average over the period):  {ranks.attrs['area_after']:,.2f} person-degree-C-min/day")
    print(f"Modelled exposure reduction: {ranks.attrs['area_before'] - ranks.attrs['area_after']:,.2f} person-degree-C-min/day")
    print(f"Interventions chosen: {len(ranks)}; {money(ranks)}")
    print(f"Saved ranked choices to {engine.DATA_DIR / 'priorities.csv'}")
    if not ranks.empty:
        print("\nTop 10 ranked fixes:")
        print(ranks.head(10).to_string(index=False))
    print("\nTHE APP'S TWO VIEWS (same budget):")
    for years, label in HORIZON_VIEWS:
        planner_view(args.budget, years, label + ":")
    quick = engine.priorities(args.budget, quick_wins_only=True, horizon_years=args.horizon)
    if not quick.empty:
        print(f"\nBest quick wins (work within months), same budget: area-wide "
              f"{quick.attrs['area_before']:,.0f} -> {quick.attrs['area_after']:,.0f}")
        print(quick.head(5).to_string(index=False))

    budget_levels(args.horizon)
    upkeep_sensitivity()
    if args.comfort_test:
        comfort_test(args.budget)


if __name__ == "__main__":
    main()
