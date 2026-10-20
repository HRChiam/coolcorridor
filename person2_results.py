"""Person 2's CLI results and CSV export; run from repo root."""
import argparse
from pathlib import Path

import engine


def main() -> None:
    parser = argparse.ArgumentParser(description="CoolCorridor routing and planner outputs")
    parser.add_argument("--budget", type=float, default=100000,
                        help="Budget in RM (ASSUMED until team agrees)")
    parser.add_argument("--data", type=Path, default=None, help="Path to repo's data folder")
    parser.add_argument("--embed-flow", action="store_true",
                        help="Update flow_day and flow_hNN fields in data/links.geojson (your branch only)")
    parser.add_argument("--route-hour", type=int, default=None)
    args = parser.parse_args()
    if args.data:
        engine.set_data_dir(args.data)

    print("CoolCorridor Person 2 | Planning indicators")
    print("IMPORTANT: Demand, prices, comfort limit and pedestrian speed are modelling assumptions.")
    print("Heat values are Person 1 modelled (may include simulated-sensor corrections).\n")
    print("ASSUMPTIONS TABLE (not empirical measurements)")
    assumptions = [
        ("Comfort threshold", f"{engine.COMFORT_C} C", "Team build plan"),
        ("Walking speed", f"{engine.WALKING_METRES_PER_MIN} metres/min", "Modelling assumption"),
        ("Max detour", f"{(engine.MAX_COOLER_DETOUR - 1)*100:.0f}%", "Team build plan"),
        ("Routing penalty lambdas", ", ".join(map(str, engine.LAMBDA_VALUES)), "Team build plan"),
        ("Trip rates per household/day", str(engine.TRIPS_PER_HOUSEHOLD), "Modelling assumption"),
        ("Planner budget", f"RM {args.budget:,.2f}", "Team must choose"),
        ("Intervention prices", "See data/interventions.csv", "Unverified assumptions"),
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

    summary = engine.route_summary(hour=args.route_hour)
    label = f"{args.route_hour}:00" if args.route_hour is not None else "07:00-19:00 demand-weighted"
    print(f"\nCOOL ROUTES ({label} comparison)")
    print(f"Home-to-destination pairs tested: {summary['evaluated_home_destination_pairs']}")
    print(f"Eligible trips with cooler alternative: {summary['trips_with_cooler_route_pct']}%")
    print(f"Average heat avoided per improved trip: {summary['mean_heat_avoided_per_improved_trip']} degree-C-minutes")
    print(f"Average extra distance of improved trips: {summary['mean_extra_distance_pct_per_improved_trip']}%")

    ranks = engine.save_priorities(args.budget)
    print(f"\nTOWNSHIP PLANNER (budget RM {args.budget:,.2f})")
    print(f"Area-wide exposure before: {ranks.attrs['area_before']:,.2f} person-degree-C-min/day")
    print(f"Area-wide exposure after:  {ranks.attrs['area_after']:,.2f} person-degree-C-min/day")
    print(f"Modelled exposure reduction: {ranks.attrs['area_before'] - ranks.attrs['area_after']:,.2f} person-degree-C-min/day")
    print(f"Interventions chosen: {len(ranks)}; proposed spend RM {ranks.attrs['spent_rm']:,.2f}")
    print(f"Saved ranked choices to {engine.DATA_DIR / 'priorities.csv'}")
    if not ranks.empty:
        print("\nTop 10 ranked fixes:")
        print(ranks.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
