from django.urls import path
from .views import calendar_view, health, metadata

urlpatterns = [
    path("health/", health, name="health"),
    path("meta/", metadata, name="metadata"),
    path("calendar/", calendar_view, name="calendar"),
]
