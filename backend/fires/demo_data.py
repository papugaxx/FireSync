"""Synthetic fixtures for frontend integration, not NASA observations."""
from calendar import monthrange
from datetime import date

DEMO_REGION_ID = "example-region"
DEMO_YEAR = 2024
DEMO_MONTH = 8


def demo_metadata():
    return {
        "region_id": DEMO_REGION_ID,
        "region_name": "Тестовый регион",
        "date_from": "2024-08-01",
        "date_to": "2024-08-31",
        "default_date": "2024-08-14",
        "timezone": "UTC",
        "is_demo": True,
    }


def demo_calendar():
    known_days = {14: (12, 18), 15: (0, 0)}
    days = []
    for day in range(1, monthrange(DEMO_YEAR, DEMO_MONTH)[1] + 1):
        modis, viirs = known_days.get(day, (None, None))
        days.append({
            "date": date(DEMO_YEAR, DEMO_MONTH, day).isoformat(),
            "modis_active_cells": modis,
            "viirs_active_cells": viirs,
        })
    return {
        "region_id": DEMO_REGION_ID,
        "year": DEMO_YEAR,
        "month": DEMO_MONTH,
        "is_demo": True,
        "days": days,
    }
