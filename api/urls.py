from django.contrib import admin
from django.urls import path
from api import views

urlpatterns = [
    path("get_route", views.get_route),
    path("accidents/", views.get_accidents),
    # path("air_quality/", views.get_air_quality),
    path("traffic_flow/", views.get_traffic_flow),
    path("noise/", views.get_noise),
]
