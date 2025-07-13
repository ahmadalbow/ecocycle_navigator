from django.apps import AppConfig

from api.services.scorers import (
    AccidentScorer,
    TrafficScorer,
    AirQualityScorer,
    NoiseScorer,
)


# Paths used for the preloaded datasets and scorers
ACCIDENT_CSV = (
    r"C:\Users\ahmad\Documents\Projects\ecocycle_navigator\Data\Accidents\accidents_dresden_bikes_2016_2023.csv"
)
BUFFER_M = 10.0

# Global scorer instances (populated in ``ready``)
accident_scorer: AccidentScorer | None = None
traffic_scorer: TrafficScorer | None = None
air_quality_scorer: AirQualityScorer | None = None
noise_scorer: NoiseScorer | None = None

class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'
    def ready(self):
        from api.services.Data import (
            preload_dresden_tiles,
            load_preloaded_air_quality,
            load_preloaded_noise,
            preload_air_quality_to_csv,
        )

        # preload_dresden_tiles(zoom=14, flow_type='relative')
        # preload_air_quality_to_csv()
        load_preloaded_air_quality(
            r"C:\Users\ahmad\Documents\Projects\ecocycle_navigator\Data\AirQuality\dresden_air_quality.csv"
        )
        load_preloaded_noise(
            r"C:\Users\ahmad\Documents\Projects\ecocycle_navigator\Data\Noise\LAERM.MROAD_LDEN.shp"
        )

        global accident_scorer, traffic_scorer, air_quality_scorer, noise_scorer
        accident_scorer = AccidentScorer(
            accident_csv=ACCIDENT_CSV,
            decay_lambda=0.3,
            K=1.3,
            buffer_m=BUFFER_M,
        )
        traffic_scorer = TrafficScorer(
            api_key="eQRZvUOMU1LkLW7lnk1Jcw1RmMRA39JF",
            zoom=14,
        )
        air_quality_scorer = AirQualityScorer()
        noise_scorer = NoiseScorer()