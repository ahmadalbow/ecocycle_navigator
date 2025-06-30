import os
import time
import requests
import pandas as pd
from datetime import datetime

# Replace with your actual keys or ensure these are set in your environment
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "43ef469c307359d15fd668155c5d09de")
AQICN_API_TOKEN     = os.getenv("AQICN_API_TOKEN", "fb0651b22a80a3e174651ce8b1c458974ff8233d")

# Grid bounds for Dresden
MIN_LON, MIN_LAT = 13.55, 51.00
MAX_LON, MAX_LAT = 13.65, 51.05
STEP = 0.01  # ~1 km grid

def lonlat_grid_points(min_lon, max_lon, min_lat, max_lat, step):
    lat = min_lat
    while lat <= max_lat:
        lon = min_lon
        while lon <= max_lon:
            yield round(lat, 4), round(lon, 4)
            lon += step
        lat += step

def fetch_owm(lat, lon):
    url = (
        f"http://api.openweathermap.org/data/2.5/air_pollution"
        f"?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
    )
    r = requests.get(url, timeout=5)
    r.raise_for_status()
    comp = r.json().get("list", [{}])[0].get("components", {})
    return {
        "owm_pm2_5": comp.get("pm2_5"),
        "owm_pm10":  comp.get("pm10"),
        "owm_no2":   comp.get("no2"),
        "owm_o3":    comp.get("o3"),
        "owm_co":    comp.get("co"),
    }

def fetch_aqicn(lat, lon):
    url = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={AQICN_API_TOKEN}"
    r = requests.get(url, timeout=5)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "ok":
        return {
            "aqicn_pm2_5": None,
            "aqicn_pm10":  None,
            "aqicn_no2":   None,
            "aqicn_o3":    None,
            "aqicn_co":    None,
        }
    iaqi = data["data"].get("iaqi", {})
    return {
        "aqicn_pm2_5": iaqi.get("pm25", {}).get("v"),
        "aqicn_pm10":  iaqi.get("pm10", {}).get("v"),
        "aqicn_no2":   iaqi.get("no2",  {}).get("v"),
        "aqicn_o3":    iaqi.get("o3",   {}).get("v"),
        "aqicn_co":    iaqi.get("co",   {}).get("v"),
    }

def main():
    records = []
    for lat, lon in lonlat_grid_points(MIN_LON, MAX_LON, MIN_LAT, MAX_LAT, STEP):
        rec = {"lat": lat, "lon": lon}
        # OpenWeatherMap
        try:
            rec.update(fetch_owm(lat, lon))
        except Exception:
            rec.update({k: None for k in ["owm_pm2_5","owm_pm10","owm_no2","owm_o3","owm_co"]})
        # AQICN
        try:
            rec.update(fetch_aqicn(lat, lon))
        except Exception:
            rec.update({k: None for k in ["aqicn_pm2_5","aqicn_pm10","aqicn_no2","aqicn_o3","aqicn_co"]})
        records.append(rec)
        time.sleep(0.2)  # small delay to respect rate limits

    # Build DataFrame
    df = pd.DataFrame(records)

    # Save to CSV
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    csv_path = f"dresden_air_quality_comparison_{timestamp}.csv"
    df.to_csv(csv_path, index=False)
    print(f"Saved comparison CSV to: {csv_path}")

    # Basic analysis
    analysis = []
    for pollutant in ["pm2_5", "pm10", "no2", "o3", "co"]:
        owm_col = f"owm_{pollutant}"
        aq_col  = f"aqicn_{pollutant}"
        valid   = df[[owm_col, aq_col]].dropna()
        analysis.append({
            "pollutant": pollutant,
            "count":     len(valid),
            "mean_diff": (valid[owm_col] - valid[aq_col]).mean(),
            "corr":      valid[owm_col].corr(valid[aq_col])
        })
    print(pd.DataFrame(analysis))

if __name__ == "__main__":
    main()
