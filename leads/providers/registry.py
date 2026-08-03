from django.conf import settings

from .base import ProviderConfigurationError
from .google_places import GooglePlacesProvider
from .overpass import OverpassProvider
from leads.services.runtime_settings import get_runtime_settings


def get_provider(name):
    """Return an enabled provider instance by stable provider name."""
    runtime = get_runtime_settings()
    if name == "overpass":
        return OverpassProvider(endpoint=runtime.overpass_api_url)
    if name == "google_places" and runtime.google_places_enabled:
        return GooglePlacesProvider()
    config = settings.LEAD_PROVIDERS.get(name)
    if not config or not config.get("enabled"):
        raise ProviderConfigurationError(f"Discovery provider '{name}' is disabled or unknown")
    raise ProviderConfigurationError(f"Unknown discovery provider: {name}")
