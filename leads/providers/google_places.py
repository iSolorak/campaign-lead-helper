from typing import List

from django.conf import settings

from leads.services.places import GooglePlacesClient, PlacesError

from .base import LeadCandidate, ProviderConfigurationError, ProviderResponseError
from leads.services.runtime_settings import get_runtime_settings


class GooglePlacesProvider:
    """Optional Google provider; disabled unless explicitly configured."""

    def __init__(self):
        config = get_runtime_settings()
        if not config.google_places_enabled:
            raise ProviderConfigurationError("Google Places provider is disabled")
        if not config.google_places_api_key:
            raise ProviderConfigurationError("Google Places provider requires an API key")
        self.client = GooglePlacesClient(api_key=config.google_places_api_key)

    def search(self, *, category: str, location: str, country: str = "", query: str = "", limit: int = 100) -> List[LeadCandidate]:
        candidates, token = [], None
        try:
            while len(candidates) < limit:
                if query.strip():
                    text_query = query.strip()
                    if country and country.casefold() not in text_query.casefold():
                        text_query = f"{text_query}, {country}"
                else:
                    readable_category = category.replace("_", " ")
                    text_query = f"{readable_category} in {location}{', ' + country if country else ''}"
                result = self.client.text_search(text_query, page_size=min(20, limit - len(candidates)), page_token=token)
                candidates.extend(LeadCandidate(
                    source="google_places", source_id=place.place_id,
                    business_name=place.display_name or "", category=category,
                    address=place.formatted_address or "", country=country, phone=place.international_phone_number or place.national_phone_number or "",
                    website_url=place.website_uri or "", latitude=place.latitude, longitude=place.longitude,
                ) for place in result.places if place.place_id and place.display_name)
                token = result.next_page_token
                if not token:
                    break
        except PlacesError as exc:
            raise ProviderResponseError(str(exc)) from exc
        return candidates[:limit]
