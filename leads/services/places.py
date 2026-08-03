from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Union

import requests
from django.conf import settings


TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DEFAULT_FIELD_MASK = (
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.types",
    "places.primaryType",
    "places.businessStatus",
    "places.websiteUri",
    "places.googleMapsUri",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.rating",
    "places.userRatingCount",
    "nextPageToken",
)

Timeout = Union[float, Tuple[float, float]]
FieldMask = Union[str, Iterable[str]]


class PlacesError(Exception):
    """Base exception for the Places service."""


class PlacesConfigurationError(PlacesError):
    """Raised when the client does not have the configuration it needs."""


class PlacesAPIError(PlacesError):
    """Raised when Google Places cannot return a usable response."""


@dataclass(frozen=True)
class PlaceResult:
    place_id: str
    display_name: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    types: Tuple[str, ...] = ()
    primary_type: Optional[str] = None
    business_status: Optional[str] = None
    website_uri: Optional[str] = None
    google_maps_uri: Optional[str] = None
    national_phone_number: Optional[str] = None
    international_phone_number: Optional[str] = None
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None


@dataclass(frozen=True)
class TextSearchResult:
    places: Tuple[PlaceResult, ...]
    next_page_token: Optional[str] = None


class GooglePlacesClient:
    """Small client for Google Places Text Search (New).

    The client only translates HTTP responses into dataclasses. Persisting those
    results, if desired, is deliberately the caller's responsibility.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        field_mask: FieldMask = DEFAULT_FIELD_MASK,
        timeout: Timeout = (3.05, 10.0),
        endpoint: str = TEXT_SEARCH_URL,
        http_client: Any = requests,
    ) -> None:
        self.api_key = api_key or getattr(settings, "GOOGLE_PLACES_API_KEY", "")
        if not self.api_key:
            raise PlacesConfigurationError(
                "A Google Places API key is required; pass api_key or set "
                "GOOGLE_PLACES_API_KEY."
            )

        self.field_mask = self._format_field_mask(field_mask)
        self.timeout = timeout
        self.endpoint = endpoint
        self.http_client = http_client

    def text_search(
        self,
        text_query: str,
        *,
        field_mask: Optional[FieldMask] = None,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
        included_type: Optional[str] = None,
        strict_type_filtering: Optional[bool] = None,
        language_code: Optional[str] = None,
        region_code: Optional[str] = None,
    ) -> TextSearchResult:
        if not text_query or not text_query.strip():
            raise ValueError("text_query must not be empty")
        if page_size is not None and not 1 <= page_size <= 20:
            raise ValueError("page_size must be between 1 and 20")

        payload: Dict[str, Any] = {"textQuery": text_query.strip()}
        optional_parameters = {
            "pageSize": page_size,
            "pageToken": page_token,
            "includedType": included_type,
            "strictTypeFiltering": strict_type_filtering,
            "languageCode": language_code,
            "regionCode": region_code,
        }
        payload.update(
            {key: value for key, value in optional_parameters.items() if value is not None}
        )

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": self._format_field_mask(field_mask)
            if field_mask is not None
            else self.field_mask,
        }

        try:
            response = self.http_client.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise PlacesAPIError("Google Places could not be reached") from exc

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            message = self._extract_google_error(response)
            status_code = getattr(response, "status_code", "unknown")
            raise PlacesAPIError(
                f"Google Places returned HTTP {status_code}: {message}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise PlacesAPIError("Google Places returned invalid JSON") from exc

        if not isinstance(data, Mapping):
            raise PlacesAPIError("Google Places returned an unexpected response")

        raw_places = data.get("places", [])
        if not isinstance(raw_places, list):
            raise PlacesAPIError("Google Places returned an invalid places collection")

        return TextSearchResult(
            places=tuple(self._parse_place(place) for place in raw_places),
            next_page_token=self._optional_string(data.get("nextPageToken")),
        )

    # A concise alias for callers that already know this is a text-search client.
    search = text_search
    search_text = text_search

    @staticmethod
    def _format_field_mask(field_mask: FieldMask) -> str:
        if isinstance(field_mask, str):
            fields = field_mask.split(",")
        else:
            fields = field_mask
        formatted = ",".join(field.strip() for field in fields if field.strip())
        if not formatted:
            raise PlacesConfigurationError("field_mask must contain at least one field")
        return formatted

    @classmethod
    def _parse_place(cls, data: Any) -> PlaceResult:
        if not isinstance(data, Mapping):
            raise PlacesAPIError("Google Places returned an invalid place")

        display_name = data.get("displayName")
        location = data.get("location")
        display_name = display_name if isinstance(display_name, Mapping) else {}
        location = location if isinstance(location, Mapping) else {}
        raw_types = data.get("types", [])
        types = (
            tuple(value for value in raw_types if isinstance(value, str))
            if isinstance(raw_types, list)
            else ()
        )

        return PlaceResult(
            place_id=cls._optional_string(data.get("id")) or "",
            display_name=cls._optional_string(display_name.get("text")),
            formatted_address=cls._optional_string(data.get("formattedAddress")),
            latitude=cls._optional_number(location.get("latitude")),
            longitude=cls._optional_number(location.get("longitude")),
            types=types,
            primary_type=cls._optional_string(data.get("primaryType")),
            business_status=cls._optional_string(data.get("businessStatus")),
            website_uri=cls._optional_string(data.get("websiteUri")),
            google_maps_uri=cls._optional_string(data.get("googleMapsUri")),
            national_phone_number=cls._optional_string(
                data.get("nationalPhoneNumber")
            ),
            international_phone_number=cls._optional_string(
                data.get("internationalPhoneNumber")
            ),
            rating=cls._optional_number(data.get("rating")),
            user_rating_count=cls._optional_integer(data.get("userRatingCount")),
        )

    @staticmethod
    def _optional_string(value: Any) -> Optional[str]:
        return value if isinstance(value, str) else None

    @staticmethod
    def _optional_number(value: Any) -> Optional[float]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @staticmethod
    def _optional_integer(value: Any) -> Optional[int]:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    @staticmethod
    def _extract_google_error(response: Any) -> str:
        try:
            data = response.json()
        except (ValueError, AttributeError):
            return "Request was rejected"
        if isinstance(data, Mapping):
            error = data.get("error")
            if isinstance(error, Mapping) and isinstance(error.get("message"), str):
                return error["message"]
        return "Request was rejected"


# Convenient shorter name for dependency injection and type annotations.
PlacesClient = GooglePlacesClient
