
from __future__ import annotations
import math
import os
import sys
from datetime import datetime
from typing import Any, List, Dict
import pandas as pd
import pyproj
from pyproj import Transformer
import mapbox_vector_tile  # pip install mapbox-vector-tile
import requests
from shapely.ops import transform
from datetime import datetime
from typing import List, Any
from rtree import index
from shapely.geometry import Point,LineString, MultiLineString

# get the folder two levels up from this file:
root = os.path.abspath(os.path.join(__file__, os.pardir, os.pardir, os.pardir))
if root not in sys.path:
    sys.path.insert(0, root)

from ecocycle_navigator import settings
# now absolute imports from 'api' will work:
from api.services.tomtom_client import TomTomClient
from api.services.Data import PRELOADED_NOISE, PRELOADED_TILES, load_preloaded_noise
from api.services.Data import PRELOADED_AIR_QUALITY
from abc import ABC, abstractmethod


class IRouteScorer(ABC):
    """Interface for classes that annotate and score route segments."""

    @abstractmethod
    def annotate_segments(self, segments: List[Dict]) -> List[Dict]:
        """Add scoring information to each segment."""
        raise NotImplementedError

    @abstractmethod
    def score_route(self, segments: List[Dict]) -> float:
        """Return a numeric score for the entire route."""
        raise NotImplementedError



class AccidentScorer(IRouteScorer):
    def __init__(
        self,
        accident_csv: str,
        decay_lambda: float = 0.5,
        K: float = 3.0,
        buffer_m: float = 10.0,
    ):
        self.decay_lambda = decay_lambda
        self.K = K
        self.buffer_m = buffer_m

        # projection from WGS84 -> UTM33N (meters)
        self.project = pyproj.Transformer.from_crs(
            "epsg:4326", "epsg:32633", always_xy=True
        ).transform

        # load & filter
        df = pd.read_csv(accident_csv)
        # df["lon"] = df["XGCSWGS84"].str.replace(",", ".").astype(float)
        # df["lat"] = df["YGCSWGS84"].str.replace(",", ".").astype(float)
        df["pt_wgs"] = df.apply(lambda r: Point(r.lon, r.lat), axis=1)
        df["pt_proj"] = df["pt_wgs"].apply(lambda p: transform(self.project, p))
        df["timestamp"] = df.apply(
            lambda r: datetime(int(r.UJAHR), int(r.UMONAT), 1, int(r.USTUNDE)),
            axis=1,
        )
        df = df.reset_index(drop=True)
        df["id"] = df.index

        self.df = df

        # build R-tree
        idx = index.Index()
        for i, p in enumerate(df["pt_proj"]):
            idx.insert(i, (p.x, p.y, p.x, p.y))
        self.idx = idx

    def get_accidents_on_route(self, route_geom: list) -> pd.DataFrame:
        line = LineString([(p[1], p[0]) for p in route_geom])
        line_proj = transform(self.project, line)
        buf = line_proj.buffer(self.buffer_m)

        candidates = list(self.idx.intersection(buf.bounds))
        df = self.df.loc[candidates]
        return df[df["pt_proj"].apply(buf.contains)].copy()

    def annotate_segments(
        self, segments: list, accidents_df: pd.DataFrame
    ) -> list:
        now = datetime.utcnow()
        out = []

        for seg in segments:
            coords = seg["geometry"] 
            line      = LineString([(p[1], p[0]) for p in coords])
            proj_line = transform(self.project, line)
            buf       = proj_line.buffer(self.buffer_m)

            seg_acc = accidents_df[accidents_df["pt_proj"].apply(buf.contains)]

            W = 0.0
            for _, r in seg_acc.iterrows():
                age = (now - r["timestamp"]).total_seconds() / (365 * 24 * 3600)
                W += math.exp(-self.decay_lambda * age)

            score = 1 + 9 * (self.K / (W + self.K))
            seg["accident_score"] = round(score, 2)
            seg["accidents"] = seg_acc["timestamp"].dt.strftime("%Y-%m %H:00").tolist()
            

        return segments

    def score_route(self, segments: list) -> float:
        """
        Compute an overall route score from a list of segment dicts:
          routeScore = (3 * l + a) / 4,
        where:
          - l = min(segment['accident_score'] for each segment)
          - a = average of all segment['accident_score']
        """
        if not segments:
            return 0.0

        scores = [seg["accident_score"] for seg in segments]
        l = min(scores)
        a = sum(scores) / len(scores)
        # print(f"l = {l}, a = {a}")
        route_score = (3 * l + a) / 4.0
        return round(route_score, 2)

class AirQualityScorer(IRouteScorer):
    # EU index breakpoints (µg/m³) for each pollutant
    EU_THRESHOLDS = {
        "pm25": [10, 20, 25, 50, 75],    # Good ≤10, Fair ≤20, Mod ≤25, Poor ≤50, VeryPoor ≤75
        "pm10": [20, 40, 50, 100, 150],
        "no2":  [40, 90, 120, 230, 340],
        "o3":   [50, 100, 130, 240, 380],
    }



    def annotate_segments(self, segments: list) -> list:
        for seg in segments:
            coords = seg["geometry"]
            mid = coords[len(coords) // 2]
            lat, lon = mid[0], mid[1]
            data = PRELOADED_AIR_QUALITY.get(self._nearest_cache_key(lat, lon))
            if not data:
                seg["air_quality_score"] = None
                continue
            pm25 = data.get("pm2_5")
            pm10 = data.get("pm10")
            no2  = data.get("no2")
            o3   = data.get("o3")

            subs = []
            if pm25  is not None: subs.append(self._score_pollutant(pm25,  "pm25"))
            if pm10  is not None: subs.append(self._score_pollutant(pm10,  "pm10"))
            if no2   is not None: subs.append(self._score_pollutant(no2,   "no2"))
            if o3    is not None: subs.append(self._score_pollutant(o3,    "o3"))

            score = min(subs) if subs else None
            seg["air_quality_score"] = score
            seg["pm25"] = pm25
            seg["pm10"] = pm10
            seg["no2"] = no2
            seg["o3"] = o3
            
        return segments

    def score_point(self, lat, lon):
        # Look up the nearest cached data
        data = PRELOADED_AIR_QUALITY.get(self._nearest_cache_key(lat, lon))
        if not data:
            return None

        # Extract concentrations
        pm25 = data.get("pm2_5")
        pm10 = data.get("pm10")
        no2  = data.get("no2")
        o3   = data.get("o3")
        # print(self._nearest_cache_key(lat, lon), data)
        # Compute sub-scores
        subs = []
        if pm25  is not None: subs.append(self._score_pollutant(pm25,  "pm25"))
        if pm10  is not None: subs.append(self._score_pollutant(pm10,  "pm10"))
        if no2   is not None: subs.append(self._score_pollutant(no2,   "no2"))
        if o3    is not None: subs.append(self._score_pollutant(o3,    "o3"))

        return sum(subs)/4 if subs else None

    def _nearest_cache_key(self, lat, lon):
        return (round(lat, 2), round(lon, 2))

    def _score_pollutant(self, value, pollutant):
        """
        Map a concentration to a 1–10 score using the EU breakpoints.
        """
        bps = self.EU_THRESHOLDS[pollutant]

        # Determine EU category 1–6
        if   value <= bps[0]:      cat = 1  # Good
        elif value <= bps[1]:      cat = 2  # Fair
        elif value <= bps[2]:      cat = 3  # Moderate
        elif value <= bps[3]:      cat = 4  # Poor
        elif value <= bps[4]:      cat = 5  # Very Poor
        else:                       cat = 6  # Extremely Poor

        # Categories 1→10, 6→1
        if cat == 1: return 10
        if cat == 6: return  1

        # Split categories 2–5 into two scores each
        low, high = bps[cat-2], bps[cat-1]
        midpoint = (low + high) / 2.0

        if   cat == 2:  # Fair → 9/8
            return 9 if value <= midpoint else 8
        elif cat == 3:  # Moderate → 7/6
            return 7 if value <= midpoint else 6
        elif cat == 4:  # Poor → 5/4
            return 5 if value <= midpoint else 4
        else:           # cat == 5 → Very Poor → 3/2
            return 3 if value <= midpoint else 2
        

    def score_route(self, segments: list) -> float:
        """
        Compute an overall route score from a list of segment dicts:
          routeScore = (3 * l + a) / 4,
        where:
          - l = min(segment['accident_score'] for each segment)
          - a = average of all segment['accident_score']
        """
        if not segments:
            return 0.0

        scores = [seg["air_quality_score"] for seg in segments]
        
        l = min(scores)
        a = sum(scores) / len(scores)
        # print(f"l = {l}, a = {a}")
        route_score = (3 * l + a) / 4.0
        return round(route_score, 2)








class TrafficScorer(IRouteScorer):
    def __init__(self, api_key: str, zoom: int = 12, flow_type: str = 'relative'):
        """
        API-Key und Zoom-Level setzen. flow_type: 'relative' oder 'absolute'.
        """
        self.api_key = api_key
        self.zoom = zoom
        self.flow_type = flow_type  # Beispiel: 'relative'
        self.tile_cache = {}       # Cache für bereits geladene Kacheln

    def annotate_segments(self, segments: list) -> list:
        """
        Annotiert jedes Segment in der Liste mit Verkehrs-Score.
        Erwartet segments als Liste von dicts z.B. {'lat': ..., 'lon': ...}.
        Gibt Liste mit jeweils neuem Feld 'score' zurück.
        """
        
        for seg in segments:
            coords = seg["geometry"] 
            mid = coords[len(coords)//2]
            lat, lon = mid[0], mid[1]

            # Tile-Koordinaten berechnen (z.B. SlippyMap-Formeln)
            n = 2 ** self.zoom
            x_tile = int((lon + 180.0) / 360.0 * n)
            lat_rad = math.radians(lat)
            y_tile = int((1.0 - math.log(math.tan(lat_rad) + 1/math.cos(lat_rad)) / math.pi) / 2.0 * n)

            # Tile abrufen oder aus Cache
            cache_key = (x_tile, y_tile, self.zoom, self.flow_type)
            if cache_key in PRELOADED_TILES:
                tile_dict = PRELOADED_TILES[cache_key]
            elif cache_key not in self.tile_cache:
                url = (f"https://api.tomtom.com/traffic/map/4/tile/flow/"
                       f"{self.flow_type}/{self.zoom}/{x_tile}/{y_tile}.pbf?key={self.api_key}")
                res = requests.get(url)
                
                res.raise_for_status()
                tile_data = res.content
                # Dekodieren mit Transformation zu Lat/Lon
                tile_dict = mapbox_vector_tile.decode(
                    tile=tile_data,
                    transformer=lambda x, y: self.pixel2deg(x_tile, y_tile, self.zoom, x, y)
                )
                self.tile_cache[cache_key] = tile_dict
            else:
                tile_dict = self.tile_cache[cache_key]

            # Repräsentationspunkt als Shapely-Objekt
            point = Point(lon, lat)
            best_feature = None
            best_dist = float('inf')

            # Layer finden (TomTom verwendet meist nur einen Layer "Traffic flow")
            layer = next(iter(tile_dict.values()))
            for feat in layer['features']:
                geom = feat['geometry']
                coords = geom['coordinates']
    
                if geom['type'] == 'LineString':
                    line = LineString(coords)
                elif geom['type'] == 'MultiLineString':
                    try:
                        # Variante A: Alle Linien verbinden (flach machen)
                        lines = [LineString(part) for part in coords]
                        line = MultiLineString(lines)
                    except Exception:
                        continue  # ungültige Geometrie überspringen
                else:
                    continue  # andere Geometrietypen ignorieren
                dist = point.distance(line)
                if dist < best_dist:
                    best_dist = dist
                    best_feature = feat

            if best_feature:
                props = best_feature['properties']
                score = None
                # Im relativen Modus ist traffic_level = currentSpeed/freeFlowSpeed
                if self.flow_type == 'relative' and 'traffic_level' in props:
                    ratio = props['traffic_level']
                    score = 1 + 9 * ratio

                # Im absoluten Modus wäre traffic_level aktuelle Geschwindigkeit
                elif self.flow_type == 'absolute' and 'traffic_level' in props:
                    score = None
                seg["traffic_score"] = score
            else:
                # Kein Verkehrsfeature gefunden
                seg["traffic_score"] = None

        return segments

    def pixel2deg(self, xtile, ytile, zoom, xpixel, ypixel, extent=4096):
        """
        Transformiert Tile-Koordinaten in Lon/Lat (WGS84).
        """
        n = 2.0 ** zoom
        xt = xtile + (xpixel / extent)
        yt = ytile + ((extent - ypixel) / extent)
        lon = (xt / n) * 360.0 - 180.0
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yt / n))))
        return lon, lat

    def score_route(self, segments: list) -> float:
        """
        Berechnet den Durchschnitts-Score über annotierte Segmente.
        Ungültige (None) Werte werden ignoriert.
        """
        scores = [s['traffic_score'] for s in segments if s.get('traffic_score') is not None]
        return (sum(scores) / len(scores)) if scores else 0.0


class NoiseScorer(IRouteScorer):
    """
    Rate each road segment’s noise exposure (road-traffic L_den dB(A))
    and convert it to a 1–10 comfort score for cyclists.
    """

    def __init__(self):

        # --- NEW: prepare a metric‐projected noise GDF once ---
        global PRELOADED_NOISE
        # assume PRELOADED_NOISE is loaded in EPSG:4326
        self.noise_metric = PRELOADED_NOISE
        # transformer from WGS84 → UTM33N
        self.to_32633 = Transformer.from_crs("EPSG:4326", "EPSG:32633", always_xy=True).transform
        self.idx = index.Index()
        self.noise_metric = self.noise_metric.reset_index(drop=True)
        for i, geom in enumerate(self.noise_metric.geometry):
            self.idx.insert(i, geom.bounds)

    # ───────────────────────────────────
    # Helpers
    # ───────────────────────────────────
    def _db_to_score(self, db: float) -> int | None:
        """
        Mappt L_den (dB) auf einen 1-10-Komfortwert.
        • ≤ 55 dB  → 10  (quasi WHO-Zielwert erreicht)
        • ≥ 75 dB  →  1  (gesundheitlich sehr belastend)
        • linear dazwischen
        """
        if db is None:
            return None

        if db <= 57:
            return 10
        if db >= 75:
            return 1

        # lineare Interpolation 55 → 10  …  75 → 1
        span_db = 75 - 57          # 20 dB
        slope   = 9 / span_db      # 0,45 Score-Punkte pro dB
        score   = 10 - (db - 57) * slope

        return int(round(score))



    
    def annotate_segments(self, segments: List[Dict]) -> List[Dict]:
        """
        Add `"noise_score"` to each segment dict.
        Expects segment["geometry"] to be a list of (lat, lon) tuples.
        """
        def _extract_db(row) -> float | None:
            """
            Liefert einen numerischen dB-Wert aus einem Zeilen-Objekt zurück,
            egal ob die Daten eine Spalte `noise_db` oder `DB_LOW`/`DB_HIGH`
            (oder nur eine davon) besitzen.
            """
            # 1) Altes Schema: fertige Spalte
            if "noise_db" in row and pd.notna(row["noise_db"]):
                return float(row["noise_db"])

            # 2) Neues Schema: DB_LOW / DB_HIGH
            if {"DB_LOW", "DB_HIGH"}.issubset(row.index):
                low, high = row["DB_LOW"], row["DB_HIGH"]

                if pd.notna(low) and pd.notna(high) and float(high) == 0.0:
                    return float(low)

                if pd.notna(low) and pd.notna(high):
                    return (float(low) + float(high)) / 2.0

                if pd.notna(low):
                    return float(low)

                if pd.notna(high):
                    return float(high)

            # 3) Fallback: erste numerische Zelle
            for col in row.index:
                val = row[col]
                if pd.notna(val) and isinstance(val, (int, float)):
                    return float(val)

            return None
        for seg in segments:
            # ───────── Mittelpunkt ermitteln ─────────
            mid_lat, mid_lon = seg["geometry"][len(seg["geometry"]) // 2]
            pt_utm = Point(mid_lon, mid_lat)                   # WGS84-Punkt     # → UTM 33 N

            cand_idx = list(self.idx.intersection((pt_utm.x, pt_utm.y, pt_utm.x, pt_utm.y)))
            candidates = self.noise_metric.iloc[cand_idx]
            matches = candidates[candidates.geometry.contains(pt_utm)]

            if matches.empty:
           
                buf = pt_utm.buffer(0.00050)  # ≈25 m
                cand_idx = list(self.idx.intersection(buf.bounds))
                candidates = self.noise_metric.iloc[cand_idx]
                matches = candidates[candidates.geometry.intersects(buf)]

            # ───────── dB entnehmen & Score berechnen ─────────
            if not matches.empty:
                db_val = _extract_db(matches.iloc[0])
                seg["noise_score"] = self._db_to_score(db_val) if db_val is not None else None
                seg["noise_db"] = db_val
                
            else:
                seg["noise_score"] = None
                seg["noise_db"] = None
                

        return segments


    def score_route(self, segments: List[Dict]) -> float:
        """
        Mean of all non-None noise scores in the route.
        """
        vals = [s["noise_score"] for s in segments if s.get("noise_score") is not None]
        return sum(vals) / len(vals) if vals else 0.0





ACCIDENT_CSV = r"C:\Users\ahmad\Documents\Projects\ecocycle_navigator\Data\Accidents\accidents_dresden_bikes.csv"
# Your TomTom key (or set TOMTOM_API_KEY in your environment)
TOMTOM_KEY   = "eQRZvUOMU1LkLW7lnk1Jcw1RmMRA39JF"

# ——— MAIN ———————————————————————————————————————————————————————————————
if __name__ == "__main__":
    # 1) Initialize clients & scorers


    traffic_scorer = TrafficScorer(api_key=settings.TOMTOM_API_KEY, zoom=12)
    # segments = [{'lat': 52.52, 'lon': 13.40}, {'lat': 52.525, 'lon': 13.405} ] # aus Routenberechnung
    # annotated = traffic_scorer.annotate_segments(segments)
    # route_score = traffic_scorer.score_route(annotated)

    tomtom = TomTomClient(api_key=settings.TOMTOM_API_KEY)
    # accident_scorer = AccidentScorer(
    #     accident_csv=ACCIDENT_CSV,
    #     decay_lambda=0.5,
    #     K=3.0,
    #     buffer_m=10.0
    # )
    # traffic_scorer = TrafficScorer(
    #     tomtom_client=tomtom,
    #     zoom=15
    # )

    # # 2) Define a test route (latitude, longitude)
    lat1, lon1 = 51.047017, 13.738455
    lat2, lon2 = 51.051370, 13.940820

    # # TomTom wants (lon, lat)
    start = (lat1, lon1)
    end   = (lat2, lon2)

    # # 3) Fetch up to 3 bicycle routes
    routes = tomtom.fetch_routes(
        start, end,
        travel_mode="bicycle",
        max_alternatives=3
    )
    # if not routes:
    #     print("No routes returned by TomTom.")
    #     exit(1)

    # # 4) Take the first route and break into 50 m segments
    geometry = routes[0]["geometry"]
    segments = tomtom.split_geometry(geometry, segment_length_m=50.0)
    # print(f"Route has {len(segments)} segments.\n")
    # trf_score = traffic_scorer.annotate_segments(segments)
    # # 5) Score each segment and print
    load_preloaded_noise()
    noise_scror = NoiseScorer()
    noise_scror.annotate_segments(segments)
