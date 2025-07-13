from django.apps import AppConfig



class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'
    def ready(self):
        from api.services.Data import preload_dresden_tiles,load_preloaded_air_quality,load_preloaded_noise, preload_air_quality_to_csv
        #preload_dresden_tiles(zoom=14, flow_type='relative')
        #preload_air_quality_to_csv()
        load_preloaded_air_quality(r"C:\Users\ahmad\Documents\Projects\ecocycle_navigator\Data\AirQuality\dresden_air_quality.csv")
        load_preloaded_noise(r"C:\Users\ahmad\Documents\Projects\Map\test\LAERM.MROAD_LDEN.shp")