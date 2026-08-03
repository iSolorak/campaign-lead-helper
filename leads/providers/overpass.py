import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

import requests
from django.conf import settings

from .base import (
    LeadCandidate, ProviderRateLimitError, ProviderResponseError,
    ProviderTimeoutError, UnsupportedCategoryError,
)
from leads.services.runtime_settings import get_runtime_settings

logger = logging.getLogger(__name__)

CATEGORY_TAGS = {
    "hair_salon": ("shop", "hairdresser"),
    "clothing_shop": ("shop", "clothes"),
    "beauty_salon": ("shop", "beauty"),
    "restaurant": ("amenity", "restaurant"),
    "cafe": ("amenity", "cafe"),
    "dentist": ("amenity", "dentist"),
    "photographer": ("craft", "photographer"),
    "accountant": ("office", "accountant"),
}

CATEGORY_ALIASES = {
    "barber": "hair_salon",
    "barbers": "hair_salon",
    "barber_shop": "hair_salon",
    "barber_shops": "hair_salon",
    "barbershop": "hair_salon",
    "barbershops": "hair_salon",
    "hairdresser": "hair_salon",
    "hairdressers": "hair_salon",
    "hair_salons": "hair_salon",
    "coffee": "cafe",
    "coffee_shop": "cafe",
    "coffee_shops": "cafe",
    "coffeeshop": "cafe",
    "cafes": "cafe",
    "clothes": "clothing_shop",
    "clothing": "clothing_shop",
    "clothing_store": "clothing_shop",
    "clothing_stores": "clothing_shop",
    "beauty": "beauty_salon",
    "beauty_salons": "beauty_salon",
    "restaurants": "restaurant",
    "dentists": "dentist",
    "dental_clinic": "dentist",
    "dental_clinics": "dentist",
    "photography": "photographer",
    "photographers": "photographer",
    "accountants": "accountant",
}

COUNTRY_CODES = {
    "greece": "GR", "hellas": "GR", "ellada": "GR",
    "united states": "US", "united states of america": "US", "usa": "US",
    "united kingdom": "GB", "uk": "GB", "germany": "DE", "france": "FR",
    "italy": "IT", "spain": "ES", "cyprus": "CY", "bulgaria": "BG", "turkey": "TR",
}

FALLBACK_ENDPOINTS = (
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)


def normalize_category(value: str) -> str:
    """Convert common human category names to a supported canonical key."""
    key = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return CATEGORY_ALIASES.get(key, key)


class OverpassProvider:
    """Discover named businesses with one bounded Overpass area query."""

    def __init__(self, endpoint=None, user_agent=None, timeout=(5.0, 30.0), max_attempts=3,
                 http_client=requests, fallback_endpoints=None):
        runtime = get_runtime_settings()
        self.endpoint = endpoint or runtime.overpass_api_url
        configured_fallbacks = FALLBACK_ENDPOINTS if fallback_endpoints is None else fallback_endpoints
        self.endpoints = tuple(dict.fromkeys((self.endpoint, *configured_fallbacks)))
        self.user_agent = user_agent or runtime.outbound_user_agent
        self.timeout = timeout
        self.max_attempts = max(1, min(max_attempts, 3))
        self.http_client = http_client

    def search(self, *, category: str, location: str, country: str = "", query: str = "", limit: int = 100) -> List[LeadCandidate]:
        category = normalize_category(category)
        if category not in CATEGORY_TAGS:
            supported = ", ".join(sorted(CATEGORY_TAGS))
            raise UnsupportedCategoryError(
                f"Unsupported Overpass category '{category}'. Supported categories: {supported}"
            )
        if not location.strip():
            raise ProviderResponseError("A location is required for Overpass searches")
        key, value = CATEGORY_TAGS[category]
        query = self._query(location, country, key, value, limit)
        data = self._request(query)
        elements = data.get("elements")
        if not isinstance(elements, list):
            raise ProviderResponseError("Overpass response has no valid elements list")
        results = []
        for element in elements:
            if country and not self._element_matches_country(element, country):
                logger.warning(
                    "Discarding Overpass result outside requested country element=%s:%s country=%s",
                    element.get("type") if isinstance(element, Mapping) else "unknown",
                    element.get("id") if isinstance(element, Mapping) else "unknown",
                    country,
                )
                continue
            candidate = self._parse_element(element, category, country)
            if candidate:
                results.append(candidate)
            if len(results) >= limit:
                break
        return results

    def _request(self, query: str) -> Mapping[str, Any]:
        last_error = None
        for attempt in range(self.max_attempts):
            endpoint = self.endpoints[attempt % len(self.endpoints)]
            next_endpoint = self.endpoints[(attempt + 1) % len(self.endpoints)]
            try:
                logger.info("Overpass request attempt=%s endpoint=%s", attempt + 1, endpoint)
                response = self.http_client.post(
                    endpoint, data={"data": query},
                    headers={"User-Agent": self.user_agent}, timeout=self.timeout,
                )
            except requests.Timeout as exc:
                last_error = ProviderTimeoutError("Overpass request timed out")
                if attempt + 1 == self.max_attempts:
                    raise last_error from exc
                logger.warning("Overpass endpoint timed out; trying fallback endpoint=%s", next_endpoint)
                continue
            except requests.RequestException as exc:
                last_error = ProviderResponseError("Overpass request failed")
                if attempt + 1 == self.max_attempts:
                    raise last_error from exc
                logger.warning("Overpass endpoint failed; trying fallback endpoint=%s", next_endpoint)
                continue
            if response.status_code == 429:
                last_error = ProviderRateLimitError("Overpass rate limit reached; try again later")
                if attempt + 1 < self.max_attempts:
                    logger.warning("Overpass endpoint rate limited; trying fallback endpoint=%s", next_endpoint)
                    continue
                raise last_error
            if response.status_code >= 500:
                last_error = ProviderResponseError(f"Overpass returned HTTP {response.status_code}")
                if attempt + 1 < self.max_attempts:
                    logger.warning(
                        "Overpass endpoint returned HTTP %s; trying fallback endpoint=%s",
                        response.status_code, next_endpoint,
                    )
                    continue
                raise last_error
            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                raise ProviderResponseError(f"Overpass returned HTTP {response.status_code}") from exc
            try:
                data = response.json()
            except ValueError as exc:
                raise ProviderResponseError("Overpass returned malformed JSON") from exc
            if not isinstance(data, Mapping):
                raise ProviderResponseError("Overpass returned an unexpected response")
            return data
        raise last_error or ProviderResponseError("Overpass request failed")

    @staticmethod
    def _query(location: str, country: str, key: str, value: str, limit: int = 100) -> str:
        escaped = location.replace("\\", "\\\\").replace('"', '\\"')
        escaped_english_suffix = re.escape(location.strip()).replace("\\", "\\\\").replace('"', '\\"')
        country = country.strip()
        if country:
            country_code = COUNTRY_CODES.get(country.casefold(), country.upper() if len(country) == 2 else "")
            if country_code:
                country_query = (
                    f'area["ISO3166-1"="{country_code}"]["boundary"="administrative"]'
                    f'["admin_level"="2"]->.countryArea;'
                )
            else:
                escaped_country = country.replace("\\", "\\\\").replace('"', '\\"')
                country_query = (
                    f'(area["name"="{escaped_country}"]["boundary"="administrative"]["admin_level"="2"];'
                    f'area["name:en"="{escaped_country}"]["boundary"="administrative"]["admin_level"="2"];)->.countryArea;'
                )
            location_query = (
                f'(rel["name"="{escaped}"]["boundary"="administrative"](area.countryArea);'
                f'rel["name:en"="{escaped}"]["boundary"="administrative"](area.countryArea);'
                f'rel["name:en"~"(^| of ){escaped_english_suffix}$",i]'
                f'["boundary"="administrative"](area.countryArea);)'
                f'->.searchBoundaries;.searchBoundaries map_to_area->.searchArea;'
            )
        else:
            country_query = ""
            location_query = f'area["name"="{escaped}"]["boundary"="administrative"]->.searchArea;'
        return (
            f'[out:json][timeout:40];{country_query}{location_query}'
            f'(nwr["{key}"="{value}"]'
            f'{"(area.countryArea)" if country else ""}(area.searchArea););'
            f'out center tags {max(1, min(int(limit), 500))};'
        )

    @staticmethod
    def _country_code(value: Any) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return ""
        return COUNTRY_CODES.get(
            normalized.casefold(), normalized.upper() if len(normalized) == 2 else ""
        )

    @classmethod
    def _element_matches_country(cls, element: Any, expected_country: str) -> bool:
        """Reject an element only when OSM explicitly declares another country.

        Most business elements have no country tag, so geographic enforcement is
        primarily performed by the intersection of the country and city areas in
        the Overpass query.
        """
        if not isinstance(element, Mapping):
            return False
        tags = element.get("tags")
        if not isinstance(tags, Mapping):
            return True
        expected_code = cls._country_code(expected_country)
        for tag_name in ("addr:country", "is_in:country_code", "ISO3166-1"):
            raw_country = str(tags.get(tag_name, "")).strip()
            if not raw_country:
                continue
            actual_code = cls._country_code(raw_country)
            if expected_code and actual_code and actual_code != expected_code:
                return False
            if not expected_code and raw_country.casefold() != expected_country.strip().casefold():
                return False
        return True

    @classmethod
    def _parse_element(cls, element: Any, category: str, default_country: str = "") -> Optional[LeadCandidate]:
        if not isinstance(element, Mapping) or element.get("type") not in {"node", "way", "relation"}:
            return None
        tags = element.get("tags")
        tags = tags if isinstance(tags, Mapping) else {}
        name = str(tags.get("name", "")).strip()
        if not name or element.get("id") is None:
            return None
        coordinates = element if element.get("type") == "node" else element.get("center", {})
        coordinates = coordinates if isinstance(coordinates, Mapping) else {}
        website = tags.get("website") or tags.get("contact:website") or tags.get("url") or ""
        phone = tags.get("phone") or tags.get("contact:phone") or ""
        email = tags.get("email") or tags.get("contact:email") or ""
        return LeadCandidate(
            source="overpass",
            source_id=f'{element["type"]}:{element["id"]}',
            business_name=name,
            category=category,
            address=cls._format_address(tags),
            city=str(tags.get("addr:city", "")),
            country=str(default_country or tags.get("addr:country", "")),
            phone=str(phone), website_url=str(website), email=str(email),
            latitude=cls._number(coordinates.get("lat")),
            longitude=cls._number(coordinates.get("lon")),
        )

    @staticmethod
    def _format_address(tags: Mapping[str, Any]) -> str:
        street = " ".join(str(value) for value in (tags.get("addr:housenumber"), tags.get("addr:street")) if value)
        return ", ".join(value for value in (street, str(tags.get("addr:postcode", "")), str(tags.get("addr:city", ""))) if value)

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
