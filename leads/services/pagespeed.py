import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Optional

import requests
from django.conf import settings
from django.utils import timezone

from leads.models import Lead, LighthouseResult
from .url_safety import validate_public_http_url
from .runtime_settings import get_runtime_settings

logger = logging.getLogger(__name__)
PAGESPEED_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


class PageSpeedError(Exception):
    pass


@dataclass(frozen=True)
class PageSpeedData:
    strategy: str
    performance: Optional[int]
    accessibility: Optional[int]
    best_practices: Optional[int]
    seo: Optional[int]
    first_contentful_paint_ms: Optional[float]
    largest_contentful_paint_ms: Optional[float]
    cumulative_layout_shift: Optional[float]
    total_blocking_time_ms: Optional[float]
    final_url: str


class PageSpeedClient:
    """Strict, typed client for the Google PageSpeed Insights API."""

    def __init__(self, api_key=None, timeout=(5.0, 45.0), http_client=requests):
        self.api_key = api_key if api_key is not None else get_runtime_settings().google_pagespeed_api_key
        self.timeout = timeout
        self.http_client = http_client

    def analyze(self, url, strategy):
        if strategy not in LighthouseResult.Strategy.values:
            raise ValueError("strategy must be mobile or desktop")
        url = validate_public_http_url(url)
        params = [("url", url), ("strategy", strategy)]
        params.extend(("category", value) for value in ("performance", "accessibility", "best-practices", "seo"))
        if self.api_key:
            params.append(("key", self.api_key))
        try:
            response = self.http_client.get(PAGESPEED_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise PageSpeedError("PageSpeed analysis timed out") from exc
        except (requests.RequestException, ValueError) as exc:
            raise PageSpeedError("PageSpeed analysis failed") from exc
        try:
            lighthouse = payload["lighthouseResult"]
            categories = lighthouse.get("categories", {})
            audits = lighthouse.get("audits", {})
            return PageSpeedData(
                strategy=strategy,
                performance=self._score(categories, "performance"),
                accessibility=self._score(categories, "accessibility"),
                best_practices=self._score(categories, "best-practices"),
                seo=self._score(categories, "seo"),
                first_contentful_paint_ms=self._audit(audits, "first-contentful-paint"),
                largest_contentful_paint_ms=self._audit(audits, "largest-contentful-paint"),
                cumulative_layout_shift=self._audit(audits, "cumulative-layout-shift"),
                total_blocking_time_ms=self._audit(audits, "total-blocking-time"),
                final_url=str(lighthouse.get("finalUrl", url)),
            )
        except (KeyError, TypeError) as exc:
            raise PageSpeedError("PageSpeed returned a malformed response") from exc

    @staticmethod
    def _score(categories, name):
        value = categories.get(name, {}).get("score")
        return round(float(value) * 100) if isinstance(value, (int, float)) else None

    @staticmethod
    def _audit(audits, name):
        value = audits.get(name, {}).get("numericValue")
        return float(value) if isinstance(value, (int, float)) else None


def analyze_lead(lead, force=False, client=None, freshness_days=None):
    """Analyze mobile and desktop independently and retain success/failure history."""
    if not lead.has_website:
        raise PageSpeedError("Lead has no website listed")
    freshness_days = freshness_days if freshness_days is not None else settings.PAGESPEED_FRESHNESS_DAYS
    cutoff = timezone.now() - timedelta(days=freshness_days)
    if not force and lead.lighthouse_results.filter(checked_at__gte=cutoff).exists():
        return []
    client = client or PageSpeedClient()
    results = []
    for strategy in LighthouseResult.Strategy.values:
        try:
            data = client.analyze(lead.website_url, strategy)
            result = LighthouseResult.objects.create(
                lead=lead, strategy=strategy, performance=data.performance,
                accessibility=data.accessibility, best_practices=data.best_practices,
                seo=data.seo, first_contentful_paint_ms=data.first_contentful_paint_ms,
                largest_contentful_paint_ms=data.largest_contentful_paint_ms,
                cumulative_layout_shift=data.cumulative_layout_shift,
                total_blocking_time_ms=data.total_blocking_time_ms, final_url=data.final_url,
            )
        except Exception as exc:
            logger.warning("PageSpeed failed lead=%s strategy=%s error=%s", lead.pk, strategy, exc)
            result = LighthouseResult.objects.create(lead=lead, strategy=strategy, error_message=str(exc)[:1000])
        results.append(result)
    lead.last_checked_at = timezone.now()
    lead.save(update_fields=("last_checked_at", "updated_at"))
    lead.recalculate_priority()
    return results
