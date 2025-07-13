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
import time
import api.apps as api_apps


ACCIDENT_CSV  = r"C:\Users\ahmad\Documents\Projects\ecocycle_navigator\Data\Accidents\accidents_dresden_bikes_2016_2023.csv" 
BUFFER_M = 10.0








@api_view(['GET'])
def get_route(request):
    """
    Return bicycle routes + segment scores, with detailed timing instrumentation.
    Expects query params: start_lat, start_lon, end_lat, end_lon
    """
    # Start total timer
    start_total = time.perf_counter()

    # 1) parse & validate
    try:
        start_lat = float(request.GET['start_lat'])
        start_lon = float(request.GET['start_lon'])
        end_lat   = float(request.GET['end_lat'])
        end_lon   = float(request.GET['end_lon'])
        max_alternatives =int(request.GET['max_routes']) 
    except (KeyError, ValueError):
        return JsonResponse({'error': 'Invalid or missing coordinates.'}, status=400)

    # 2) fetch raw routes
    tomtom = TomTomClient("eQRZvUOMU1LkLW7lnk1Jcw1RmMRA39JF")
    t0 = time.perf_counter()
    raw_routes = tomtom.fetch_routes(
        (start_lat, start_lon),
        (end_lat,   end_lon),
        travel_mode="bicycle",
        max_alternatives=max_alternatives
    )
    fetch_time = time.perf_counter() - t0

    if not raw_routes:
        return JsonResponse({'error': 'No routes found.'}, status=404)

    
    # 3) instantiate scorers
    accident_scorer = api_apps.accident_scorer
    traffic_scorer = api_apps.traffic_scorer
    air_quality_scorer = api_apps.air_quality_scorer
    noise_scorer = api_apps.noise_scorer

    # 4) process each route
    t_routes_start = time.perf_counter()
    all_acc_subset = []
    all_segmentation = []
    all_acc_annot = []
    all_traffic_annot = []
    all_air_annot = []
    all_noise_annot = []
    all_route_scoring = []

    response_routes = []
    for rt in raw_routes:
        geom = rt['geometry']

        # a) subset accidents on this route
        t1 = time.perf_counter()
        acc_on_route_df = accident_scorer.get_accidents_on_route(geom)
        t_acc_subset = time.perf_counter() - t1
        all_acc_subset.append(t_acc_subset)

        # b) split into ~50m segments
        t2 = time.perf_counter()
        segments_geo = tomtom.split_geometry(geom, segment_length_m=50.0)
        t_segmentation = time.perf_counter() - t2
        all_segmentation.append(t_segmentation)

        # initialize segment dicts
        segments = [{"geometry": seg} for seg in segments_geo]

        # c) accident annotation
        t3 = time.perf_counter()
        segments = accident_scorer.annotate_segments(segments, acc_on_route_df)
        t_acc_annot = time.perf_counter() - t3
        all_acc_annot.append(t_acc_annot)

        # d) traffic annotation
        t4 = time.perf_counter()
        segments = traffic_scorer.annotate_segments(segments)
        t_traffic_annot = time.perf_counter() - t4
        all_traffic_annot.append(t_traffic_annot)

        # e) air quality annotation
        t5 = time.perf_counter()
        segments = air_quality_scorer.annotate_segments(segments)
        t_air_annot = time.perf_counter() - t5
        all_air_annot.append(t_air_annot)

        # f) noise annotation
        t6 = time.perf_counter()
        segments = noise_scorer.annotate_segments(segments)
        t_noise_annot = time.perf_counter() - t6
        all_noise_annot.append(t_noise_annot)

        # g) route-level scoring
        t7 = time.perf_counter()
        route_score_acc     = accident_scorer.score_route(segments)
        route_score_traffic = traffic_scorer.score_route(segments)
        route_score_air     = air_quality_scorer.score_route(segments)
        route_score_noise   = noise_scorer.score_route(segments)
        t_route_score = time.perf_counter() - t7
        all_route_scoring.append(t_route_score)

        # prepare JSON-friendly geometry
        response_routes.append({
            'distance_m':        rt['distance_m'],
            'duration_s':        rt['travel_time_s'],
            'geometry':          [{'latitude': lat, 'longitude': lon} for lat, lon in geom],
            'segments':          [
                {
                    'geometry': [{'latitude': lat, 'longitude': lon} for lat, lon in seg['geometry']],
                    'accident_score': seg.get('accident_score'),
                    'traffic_score': seg.get('traffic_score'),
                    'air_quality_score': seg.get('air_quality_score'),
                    'noise_score': seg.get('noise_score'),
                }
                for seg in segments
            ],
            'accident_score':     round(route_score_acc, 2),
            'traffic_score':      round(route_score_traffic, 2),
            'air_quality_score':  round(route_score_air, 2),
            'noise_score':        round(route_score_noise, 2),
        })

    total_routes_time = time.perf_counter() - t_routes_start
    total_time = time.perf_counter() - start_total

    # Compute averages
    n = len(raw_routes)
    performance = {
        'fetch_time_s':       round(fetch_time, 10),
        'avg_acc_subset_s':   round(sum(all_acc_subset) , 10),
        'avg_acc_annot_s':    round(sum(all_acc_annot) , 10),
        'avg_traffic_annot_s':round(sum(all_traffic_annot) , 10),
        'avg_air_annot_s':    round(sum(all_air_annot) , 10),
        'avg_noise_annot_s':  round(sum(all_noise_annot) , 10),
        'total_routes_time_s':round(total_routes_time, 10),
        'total_time_s':       round(total_time, 10),
    }

    # Print performance to console for logging
    print("=== EcoCycle Navigator Performance Metrics ===")
    for k, v in performance.items():
        print(f"{k}: {v}s")
    print("=============================================")

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