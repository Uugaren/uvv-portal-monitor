"""
Módulo de Web Scraping para o Portal UVV usando Playwright.
"""
from .client import UVVPortalClient
from .activities import ActivityScraper, ActivityItem, format_activities_json
from .schedule import ScheduleScraper, ScheduleItem

__all__ = ["UVVPortalClient", "ActivityScraper", "ActivityItem", "ScheduleScraper", "ScheduleItem", "format_activities_json"]

