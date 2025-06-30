# routes/services/tomtom_client.py

import os
import math
import requests
from typing import List, Tuple, Dict, Optional

class TomTomClient:
    """
    Client for TomTom Routing & Traffic APIs.
    """

    ROUTE_URL   = "https://api.tomtom.com/routing/1/calculateRoute"
    TRAFFIC_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute"

    def __init__(self, api_key: Optional[str] = None):
        """
        :param api_key: TomTom API key (or set TOMTOM_API_KEY in env)
        """
        self.api_key = api_key or os.getenv("TOMTOM_API_KEY")
        if not self.api_key:
            raise ValueError("TomTom API key must be provided")

    def fetch_routes(
        self,
        start: Tuple[float,float],
        end:   Tuple[float,float],
        travel_mode:      str = "bicycle",
        max_alternatives: int = 3
    ) -> List[Dict]:
        """
        Returns up to max_alternatives routes. Each route dict has:
          - 'geometry': List[(lat, lon)]
          - 'distance_m': float
          - 'travel_time_s': float
        """
        coord_str = f"{start[0]},{start[1]}:{end[0]},{end[1]}"
        url = f"{self.ROUTE_URL}/{coord_str}/json"
        params = {
            "key":             self.api_key,
            "travelMode":      travel_mode,
            "maxAlternatives": max_alternatives
        }

        raw = self._get_json(url, params)
        return self._parse_routes(raw)

    def fetch_traffic_flow(
        self,
        point: Tuple[float,float],
        zoom:  int = 10
    ) -> Optional[Dict]:
        """
        Returns {'currentSpeed':..., 'freeFlowSpeed':..., ...} for the given (lat,lon).
        """
        url = f"{self.TRAFFIC_URL}/{zoom}/json"
        params = {"point": f"{point[0]},{point[1]}", "key": self.api_key}
        data = self._get_json(url, params)
        return data.get("flowSegmentData") if data else None

    def split_geometry(
        self,
        geometry: List[Tuple[float,float]],
        segment_length_m: float = 50.0
    ) -> List[List[Tuple[float,float]]]:
        """
        Break a polyline into ~segment_length_m pieces.
        Returns a list of segments, each a list of (lat,lon) coords.
        """
        segments = []
        buffer = []   # current segment
        acc_dist = 0  # accumulated distance in current segment

        def haversine(a, b):
            # returns meters between two lat/lon points
            lat1, lon1 = math.radians(a[0]), math.radians(a[1])
            lat2, lon2 = math.radians(b[0]), math.radians(b[1])
            dlat, dlon = lat2-lat1, lon2-lon1
            R = 6371000
            x = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
            return 2*R*math.asin(math.sqrt(x))

        prev = None
        for pt in geometry:
            if prev is None:
                buffer.append(pt)
            else:
                dist = haversine(prev, pt)
                acc_dist += dist
                buffer.append(pt)
                if acc_dist >= segment_length_m:
                    segments.append(buffer)
                    buffer = [pt]
                    acc_dist = 0
            prev = pt

        # add leftover points as a final segment
        if len(buffer) > 1:
            segments.append(buffer)

        return segments

    # ────────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ────────────────────────────────────────────────────────────────────────────

    def _get_json(self, url: str, params: Dict) -> Optional[Dict]:
        try:
            r = requests.get(url, params=params, timeout=10)
            print(f"Requesting: {r.url}")
            r.raise_for_status()
            r.url
            return r.json()
        except requests.RequestException as e:
            # TODO: use logging instead of print
            print(f"[TomTomClient] API error: {e}")
            return None

    def _parse_routes(self, raw: Optional[Dict]) -> List[Dict]:
        routes = []
        if not raw or "routes" not in raw:
            return routes

        for rt in raw["routes"]:
            leg = rt.get("legs", [{}])[0]
            pts = leg.get("points", [])
            geometry = [(p["latitude"], p["longitude"]) for p in pts]

            routes.append({
                "geometry":     geometry,
                "distance_m":   rt.get("summary", {}).get("lengthInMeters"),
                "travel_time_s":rt.get("summary", {}).get("travelTimeInSeconds"),
            })

        return routes

if __name__ == "__main__":
    # Replace with your actual TomTom API key (or export TOMTOM_API_KEY).
    client = TomTomClient(api_key="eQRZvUOMU1LkLW7lnk1Jcw1RmMRA39JF")

    # IMPORTANT: TomTom expects (longitude, latitude)
    # Here we define them in (lat, lon) then swap for the call.
    lat1, lon1 = 51.051358 , 13.724428
    lat2, lon2 = 51.049687 , 13.738792

    start = (lat1, lon1 )
    end   = (lat2, lon2)

    # Fetch up to 5 alternative bicycle routes
    routes = client.fetch_routes(start, end, max_alternatives=3)

    first_route = routes[0]["geometry"]
    segments = client.split_geometry(first_route, segment_length_m=50)
    
    flow = client.fetch_traffic_flow(start)
    print(flow)
