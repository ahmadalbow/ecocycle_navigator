# routes/views.py

import os
import json

from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse

import requests
from rest_framework.response import Response
from rest_framework.decorators import api_view

from api.services.tomtom_client import TomTomClient
from api.services.scorers import AccidentScorer, NoiseScorer, TrafficScorer, AirQualityScorer


import pandas as pd
import pyproj
from shapely.geometry import Point, LineString
from shapely.ops import transform
from rtree import index
from api.services.Data import PRELOADED_AIR_QUALITY
from rest_framework import status


ACCIDENT_CSV  = r"C:\Users\ahmad\Documents\Projects\ecocycle_navigator\Data\Accidents\accidents_dresden_bikes_2016_2023.csv" 
BUFFER_M = 10.0





@api_view(['GET'])
def get_accidents(request):
    """
    Return all bike‐involved accidents as JSON:
      [{ id, latitude, longitude, timestamp }, ...]
    """
    df = pd.read_csv(ACCIDENT_CSV)
    

    # human‐readable timestamp
    df['timestamp'] = df.apply(
        lambda r: f"{int(r.UJAHR)}-{int(r.UMONAT):02d} {int(r.USTUNDE):02d}:00",
        axis=1
    )
    df = df.reset_index(drop=True)
    df['id'] = df.index

    out = df[['id','lat','lon','timestamp']].rename(
        columns={'lat':'latitude','lon':'longitude'}
    ).to_dict(orient='records')

    return JsonResponse({'accidents': out}, status=200)



@api_view(['GET'])
def get_rout(request):
    """
    Return bicycle routes + segment scores.
    Expects query params: start_lat, start_lon, end_lat, end_lon
    """
    # 1) parse & validate
    try:
        start_lat = float(request.GET['start_lat'])
        start_lon = float(request.GET['start_lon'])
        end_lat   = float(request.GET['end_lat'])
        end_lon   = float(request.GET['end_lon'])
    except (KeyError, ValueError):
        return JsonResponse({'error': 'Invalid or missing coordinates.'}, status=400)

    # 2) fetch raw routes
    tomtom     = TomTomClient("eQRZvUOMU1LkLW7lnk1Jcw1RmMRA39JF")
    raw_routes = tomtom.fetch_routes(
        (start_lat,start_lon ),
        (end_lat,   end_lon),
        travel_mode="bicycle",
        max_alternatives=3
    )
    if not raw_routes:
        return JsonResponse({'error': 'No routes found.'}, status=404)

    # 3) instantiate scorers
    accident_scorer = AccidentScorer(
        accident_csv=ACCIDENT_CSV,
        decay_lambda=0.3,
        K=1.3,
        buffer_m=BUFFER_M
    )
    traffic_scorer = TrafficScorer(
        api_key="eQRZvUOMU1LkLW7lnk1Jcw1RmMRA39JF",
        zoom=14
    )
    air_quality_scorer = AirQualityScorer()
    noise_scorer = NoiseScorer()

    # 4) build each route's response
    response_routes = []
    for rt in raw_routes:
        geom = rt['geometry']

        # a) subset accidents on this route
        acc_on_route_df = accident_scorer.get_accidents_on_route(geom)

        # b) split into ~50m segments
        segments_geo = tomtom.split_geometry(geom, segment_length_m=50.0)
 
        # c) per‐segment accident
        segments = [
            {"geometry": seg}
            for seg in segments_geo
        ]

        segments = accident_scorer.annotate_segments(
            segments,
            acc_on_route_df
        )
 
        segments = traffic_scorer.annotate_segments(segments)
        
        segments = air_quality_scorer.annotate_segments(segments)
        segments = noise_scorer.annotate_segments(segments)
        for seg in segments:
            seg["geometry"] = [
                {"latitude": lat, "longitude": lon}
                for lat, lon in seg["geometry"]
            ]

        # e) route‐level scores
        route_score_acc = accident_scorer.score_route(segments)


        response_routes.append({
            'distance_m':      rt['distance_m'],
            'duration_s':      rt['travel_time_s'],
            'geometry':        [
                {'latitude': lat, 'longitude': lon}
                for lat,lon in geom
            ],
            'segments':        segments,
            'accident_score': round(route_score_acc, 2),
            "traffic_score": traffic_scorer.score_route(segments),
            "air_quality_score": air_quality_scorer.score_route(segments),
            "noise_score": noise_scorer.score_route(segments)

        })
       
    return JsonResponse({'routes': response_routes}, status=200)

import math
import requests
from django.conf import settings
from django.http import HttpResponse, Http404
from rest_framework.decorators import api_view




from api.services.Data import PRELOADED_TILES, PRELOADED_NOISE

@api_view(['GET'])
def get_traffic_flow(request):
    features = []
    for tile in PRELOADED_TILES.values():
        layer = next(iter(tile.values()))
        features.extend(layer['features'])
    geojson = {"type": "FeatureCollection", "features": features}
    return JsonResponse(geojson, status=200)

@api_view(['GET'])
def get_noise(request):
    features = json.loads(PRELOADED_NOISE.to_json())["features"]
    return JsonResponse({"type": "FeatureCollection", "features": features}, status=200)


# @api_view(['GET'])
# def get_air_quality(request):
#     """
#     Proxies a single AQICN map tile covering Dresden.
#     Computes the center tile at a given zoom, fetches it from AQICN,
#     and returns the PNG directly to the client.
#     """
#     # Bounding box for Dresden: south, west, north, east
#     south, west, north, east = 51.0, 13.5, 51.2, 13.9
#     # Compute center of bounding box
#     center_lat = (south + north) / 2.0
#     center_lon = (west + east) / 2.0

#     # Zoom level for tile (choose a zoom that covers entire city)
#     zoom = 11

#     # Convert lat/lon to tile x,y
#     lat_rad = math.radians(center_lat)
#     n = 2 ** zoom
#     tile_x = int((center_lon + 180.0) / 360.0 * n)
#     tile_y = int((1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n)

#     # Fetch tile from AQICN
#     token = settings.AQICN_TOKEN
#     tile_url = f"https://tiles.aqicn.org/tiles/usepa-aqi/{zoom}/{tile_x}/{tile_y}.png?token={token}"
#     try:
#         resp = requests.get(tile_url, timeout=5)
#         resp.raise_for_status()
#     except requests.RequestException:
#         raise Http404("AQI tile not available")

#     # Return the PNG directly
#     return HttpResponse(resp.content, content_type='image/png')