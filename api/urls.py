from django.urls import path

from .views import (
    DPRouteWithFuelView,
    GreedyRouteWithFuelView,
    HealthView,
    RouteWithFuelView,
)

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("route-with-fuel/", RouteWithFuelView.as_view(), name="route-with-fuel"),
    path(
        "route-with-fuel/greedy/",
        GreedyRouteWithFuelView.as_view(),
        name="route-with-fuel-greedy",
    ),
    path(
        "route-with-fuel/dp/",
        DPRouteWithFuelView.as_view(),
        name="route-with-fuel-dp",
    ),
]
