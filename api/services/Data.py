import os, sys
import csv
import math
import requests, mapbox_vector_tile
import geopandas as gpd
from shapely.geometry import Point
import re
from datetime import datetime  # ✅ ADD THIS LINE
root = os.path.abspath(os.path.join(__file__, os.pardir, os.pardir, os.pardir))
if root not in sys.path:
    sys.path.insert(0, root)


from django.conf import settings

MIN_LON, MIN_LAT = 13.6000, 51.0000
MAX_LON, MAX_LAT = 13.8500, 51.1000
# MAX_LON, MAX_LAT = 13.8550, 51.1500
# MIN_LON, MIN_LAT = 13.5500, 51.0000
def lonlat_to_tile(lon, lat, zoom):
    n = 2 ** zoom
    xt = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    yt = int((1.0 
              - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi
             ) / 2.0 * n)
    return xt, yt



def pixel2deg(xtile, ytile, zoom, xpixel, ypixel, extent=4096):
        """
        Transformiert Tile-Koordinaten in Lon/Lat (WGS84).
        """
        n = 2.0 ** zoom
        xt = xtile + (xpixel / extent)
        yt = ytile + ((extent - ypixel) / extent)
        lon = (xt / n) * 360.0 - 180.0
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yt / n))))
        return lon, lat


# upper-right

# module‐level cache
PRELOADED_TILES = {}

def preload_dresden_tiles(zoom=15, flow_type='relative'):
    
    x0, y1 = lonlat_to_tile(MIN_LON, MIN_LAT, zoom)  # lower-left
    x1, y0 = lonlat_to_tile(MAX_LON, MAX_LAT, zoom)  
    for x in range(x0, x1+1):
        for y in range(y0, y1+1):
            key = (x, y, zoom, flow_type)
            print(key)
            url = (
              f"https://api.tomtom.com/traffic/map/4/tile/flow/"
              f"{flow_type}/{zoom}/{x}/{y}.pbf?key={settings.TOMTOM_API_KEY}"
            )
            r = requests.get(url)
            r.raise_for_status()
            tile = mapbox_vector_tile.decode(
                tile=r.content,
                transformer=lambda px, py: pixel2deg(x, y, zoom, px, py)
            )
            PRELOADED_TILES[key] = tile
   


PRELOADED_AIR_QUALITY = {}

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
        f"?lat={lat}&lon={lon}&appid={settings.OWM_KEY}"
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


def preload_air_quality_to_csv(min_lon  = MIN_LON, max_lon = MAX_LON, min_lat = MIN_LAT, max_lat = MAX_LAT, step = 0.01, output_csv= r"C:\Users\ahmad\Documents\Projects\ecocycle_navigator\Data\AirQuality\dresden_air_quality.csv"):
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
            for attempt in range(1, 4):
                url = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={settings.AQICN_TOKEN}"
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


def load_preloaded_air_quality(csv_path):
    """
    Load saved CSV and populate PRELOADED_AIR_QUALITY.
    Only rows with status=='ok' are loaded.
    """
    PRELOADED_AIR_QUALITY.clear()
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            # parse coordinates
            lat = float(row['lat'])
            lon = float(row['lon'])

            # skip if API returned error for this point
            if row.get('status') != 'ok':
                continue

            # helper to convert empty strings to None, else float
            def to_float(val):
                return float(val) if val not in (None, "") else None

            PRELOADED_AIR_QUALITY[(lat, lon)] = {
                "pm2_5": to_float(row.get("pm2_5")),
                "pm10": to_float(row.get("pm10")),
                "no2":  to_float(row.get("no2")),
                "o3":   to_float(row.get("o3")),
                "co":   to_float(row.get("co")),
                "timestamp": row.get("timestamp"),
            }



















# def preload_air_quality_data():
#     for lat, lon in lonlat_grid_points(MIN_LON, MAX_LON, MIN_LAT, MAX_LAT):
#         try:
#             # url = (
#             #     f"http://api.openweathermap.org/data/2.5/air_pollution"
#             #     f"?lat={lat}&lon={lon}&appid={settings.OPENWEATHER_API_KEY}"
#             # )
#             url = (
#                 f"http://api.openweathermap.org/data/2.5/air_pollution"
#                 f"?lat={lat}&lon={lon}&appid=43ef469c307359d15fd668155c5d09de"
#             )
#             res = requests.get(url, timeout=5)
#             res.raise_for_status()
#             pollution = res.json().get("list", [{}])[0]
#             components = pollution.get("components", {})
#             PRELOADED_AIR_QUALITY[(lat, lon)] = {
#                 "pm2_5": components.get("pm2_5", 0),
#                 "pm10": components.get("pm10", 0),
#                 "no2": components.get("no2", 0),
#                 "o3": components.get("o3", 0),
#                 "co": components.get("co", 0),
#                 "timestamp": datetime.utcnow().isoformat()
#             }
#         except Exception as e:
#             print(f"Failed to fetch data for {lat},{lon}: {e}")


PRELOADED_NOISE = None

def load_preloaded_noise_1(file_path):
    global PRELOADED_NOISE

    # 1) Read the GML
    gdf_noise = gpd.read_file(file_path)

    # 2) Ensure WGS84
    if gdf_noise.crs is None:
        gdf_noise.set_crs(epsg=4326, inplace=True)
    if gdf_noise.crs.to_string() != "EPSG:4326":
        gdf_noise = gdf_noise.to_crs(epsg=4326)

    # 3) Parse CATEGORY → numeric dB
    def category_to_db(cat: str) -> float | None:
        s = cat.lower().replace("lden", "")
        # “Above” bands
        if s.startswith("ab"):
            m = re.search(r"\d+", s)
            return float(m.group()) if m else None

        nums = re.findall(r"\d+", s)
        # Two-number band (e.g. “45” & “49”)
        if len(nums) == 2:
            low, high = map(int, nums)
            return (low + high) / 2.0
        # Single 4-digit like “4549”
        if len(nums) == 1 and len(nums[0]) == 4:
            t = nums[0]
            low, high = int(t[:2]), int(t[2:])
            return (low + high) / 2.0
        # fallback single number
        if nums:
            return float(nums[0])
        return None

    gdf_noise["noise_db"] = gdf_noise["CATEGORY"].apply(category_to_db)

    # 4) Assign to module global
    PRELOADED_NOISE = gdf_noise
  

def load_preloaded_noise(file_path):
    global PRELOADED_NOISE

    # 1) Read the GML
    gdf = gpd.read_file(file_path)         # 6 011 Features, CRS = None

    # 1) fehlendes CRS ergänzen (ETRS89 / UTM 33N)
    gdf.set_crs(epsg=25833, inplace=True)
    gdf_wgs = gdf.to_crs(epsg=4326)
    # 4) Assign to module global
    PRELOADED_NOISE = gdf_wgs
  

if __name__ == "__main__":
    load_preloaded_noise(r"C:\Users\ahmad\Documents\Projects\Map\test\LAERM.MROAD_LDEN.shp")