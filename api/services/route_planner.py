# routes/services/route_planner.py

from typing import List, Tuple, Dict
from .tomtom_client import TomTomClient
from .scorers import AccidentScorer, AirQualityScorer, NoiseScorer, TrafficScorer

class RoutePlanner:
    """
    Orchestrates fetching raw routes, splitting into segments,
    scoring each segment, and aggregating results.
    """
    def __init__(
        self,
        tomtom_client:    TomTomClient,
        accident_scorer:  AccidentScorer,
        air_scorer:       AirQualityScorer,
        noise_scorer:     NoiseScorer,
        traffic_scorer:   TrafficScorer,
        segment_length_m: float = 50.0
    ):
        self.tomtom            = tomtom_client
        self.accident_scorer   = accident_scorer
        self.air_scorer        = air_scorer
        self.noise_scorer      = noise_scorer
        self.traffic_scorer    = traffic_scorer
        self.segment_length_m  = segment_length_m

    def get_scored_routes(
        self,
        start:        Tuple[float, float],
        end:          Tuple[float, float],
        max_alternatives: int = 3
    ) -> List[Dict]:
        """
        1) Fetch raw routes from TomTom.
        2) For each route:
           a) Split geometry into ~segment_length_m segments.
           b) Score each segment by all four scorers.
           c) Compute average score per criterion for the whole route.
        3) Return a list of dicts in the shape:
           {
             'geometry': [ (lat,lon), ... ],
             'scores': {
               'accident': float,
               'air_quality': float,
               'noise': float,
               'traffic': float
             },
             'segments': [
               {
                 'geometry': [ (lat,lon), ... ],
                 'accident': float,
                 'air_quality': float,
                 'noise': float,
                 'traffic': float
               },
               ...
             ]
           }
        """
        # 1) fetch routes
        raw_routes = self.tomtom.fetch_routes(
            start,
            end,
            travel_mode="bicycle",
            max_alternatives=max_alternatives
        )
        scored = []

        for rt in raw_routes:
            # 2a) split into segments
            segments = self.tomtom.split_geometry(
                rt["geometry"],
                segment_length_m=self.segment_length_m
            )

            seg_scores = []
            # 2b) score each segment
            for seg in segments:
                seg_scores.append({
                    "geometry":    seg,
                    "accident":    self.accident_scorer.score_segment(seg),
                    "air_quality": self.air_scorer.score_segment(seg),
                    "noise":       self.noise_scorer.score_segment(seg),
                    "traffic":     self.traffic_scorer.score_segment(seg),
                })

            # 2c) aggregate to route-level averages
            route_scores = {}
            for key in ("accident", "air_quality", "noise", "traffic"):
                vals = [s[key] for s in seg_scores]
                route_scores[key] = sum(vals) / len(vals) if vals else 0.0

            scored.append({
                "geometry": rt["geometry"],
                "scores":   route_scores,
                "segments": seg_scores,
            })

        return scored
