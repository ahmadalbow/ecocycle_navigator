import csv
import requests

# ——— GRID DEFINITION FOR DRESDEN ———
MIN_LON, MIN_LAT = 13.6000, 51.0000
MAX_LON, MAX_LAT = 13.8500, 51.1000
STEP = 0.01

AQICN_TOKEN = "fb0651b22a80a3e174651ce8b1c458974ff8233d"
OWM_KEY     = "43ef469c307359d15fd668155c5d09de"
OUTPUT_CSV  = "dresden_air_quality_02.csv"

MAX_RETRIES = 3  # still retry AQICN, but with no delay

# -------------------------------------------------------------

def lonlat_grid_points(min_lon, max_lon, min_lat, max_lat, step=0.01):
    lat = min_lat
    while lat <= max_lat:
        lon = min_lon
        while lon <= max_lon:
            yield round(lat, 2), round(lon, 2)
            lon += step
        lat += step

def fetch_owm_components(lat, lon):
    url = (
        f"http://api.openweathermap.org/data/2.5/air_pollution"
        f"?lat={lat}&lon={lon}&appid={OWM_KEY}"
    )
    r = requests.get(url, timeout=5)
    r.raise_for_status()
    comp = r.json().get("list", [{}])[0].get("components", {})
    return {
        "pm2_5": comp.get("pm2_5"),
        "pm10":  comp.get("pm10"),
        "no2":   comp.get("no2"),
        "o3":    comp.get("o3"),
    }

def preload_air_quality_to_csv(
    min_lon, max_lon, min_lat, max_lat, step, aq_token, output_csv
):
    fieldnames = [
        "lat", "lon",
        "pm2_5", "pm10", "no2", "o3",
        "timestamp",
        "status", "error"
    ]

    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for lat, lon in lonlat_grid_points(min_lon, max_lon, min_lat, max_lat, step):
            row = {
                "lat": lat, "lon": lon,
                "pm2_5": None, "pm10": None, "no2": None, "o3": None,
                "timestamp": None,
                "status": None, "error": None
            }

            # 1) try AQICN up to MAX_RETRIES – no sleep between attempts
            for attempt in range(1, MAX_RETRIES + 1):
                url = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={aq_token}"
                try:
                    resp = requests.get(url, timeout=5)
                    resp.raise_for_status()
                    data = resp.json()
                    row["status"] = data.get("status")

                    if row["status"] == "ok":
                        iaqi = data["data"].get("iaqi", {})
                        row.update({
                            "pm2_5": iaqi.get("pm25", {}).get("v"),
                            "pm10":  iaqi.get("pm10", {}).get("v"),
                            "no2":   iaqi.get("no2",  {}).get("v"),
                            "o3":    iaqi.get("o3",   {}).get("v"),
                            "timestamp": data["data"]["time"]["iso"],
                        })
                        break
                    else:
                        row["error"] = f"AQICN status={row['status']}"
                except Exception as e:
                    row["status"] = "error"
                    row["error"]  = f"AQICN error={e}"

                # immediately loop again (no delay) until attempts exhausted

            # 2) fallback to OWM for any missing pollutant
            missing = [p for p in ("pm2_5", "pm10", "no2", "o3") if row[p] is None]
            if missing:
                try:
                    owm = fetch_owm_components(lat, lon)
                    for p in missing:
                        row[p] = owm.get(p)
                    row["error"] = (row["error"] or "") + "; filled_from_OWM"
                except Exception as e:
                    row["error"] = (row["error"] or "") + f"; OWM error={e}"

            writer.writerow(row)
            print(f"Wrote {lat},{lon}: status={row['status']} missing={missing}")

# -------------------------------------------------------------

def load_air_quality_csv(path):
    import pandas as pd
    return pd.read_csv(path, parse_dates=["timestamp"], keep_default_na=False)

if __name__ == "__main__":
    preload_air_quality_to_csv(
        MIN_LON, MAX_LON, MIN_LAT, MAX_LAT, STEP, AQICN_TOKEN, OUTPUT_CSV
    )
    print(f"\nDone! Data saved to {OUTPUT_CSV}")
