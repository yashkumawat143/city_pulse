"""
generate_data.py
----------------
CLI entry point for the CityPulse synthetic data simulation.

v2.0: the generation logic itself now lives in simulation.py (importable by
tests and demo tooling). This file stays so the documented workflow still works:

    python generate_data.py

Datasets produced (in ./data/):
    weather.csv     -> timestamp, zone, temperature, rainfall_mm, condition
    traffic.csv     -> timestamp, zone, congestion_pct, incidents
    complaints.csv  -> timestamp, zone, category, count

Story baked into the data (unchanged):
    A rainfall event hits Zone A around hour 3 of the 6-hour window.
    As rainfall rises, traffic congestion in Zone A rises shortly after,
    and waterlogging complaints (plus overall complaint volume) spike.
    Zone B and Zone C stay close to their normal baseline throughout.
"""

import simulation

EVENT_ZONE = simulation.EVENT_ZONE


def main() -> None:
    print("Generating weather data...")
    weather_df, traffic_df, complaints_df = simulation.write_data()

    data_dir = simulation.DATA_DIR
    print(f"\nDone. Files written to: {data_dir}")
    print(f"  weather.csv     -> {len(weather_df)} rows")
    print(f"  traffic.csv     -> {len(traffic_df)} rows")
    print(f"  complaints.csv  -> {len(complaints_df)} rows")

    # Quick sanity peek so you can eyeball the event without opening the CSVs.
    event_rows = weather_df[
        (weather_df["zone"] == EVENT_ZONE) & (weather_df["rainfall_mm"] > 10)
    ]
    print(f"\nZone A heavy-rain rows (rainfall_mm > 10): {len(event_rows)}")


if __name__ == "__main__":
    main()
