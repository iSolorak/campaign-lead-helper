from dataclasses import dataclass
from typing import List, Optional, Protocol


class ProviderError(Exception):
    """Base discovery provider failure."""


class ProviderConfigurationError(ProviderError):
    """The selected provider is disabled or incorrectly configured."""


class ProviderTimeoutError(ProviderError):
    """The provider did not respond within the configured timeout."""


class ProviderRateLimitError(ProviderError):
    """The provider rejected a request due to rate limiting."""


class ProviderResponseError(ProviderError):
    """The provider returned malformed or unsuccessful data."""


class UnsupportedCategoryError(ProviderError):
    """The provider cannot search the requested category."""


@dataclass(frozen=True)
class LeadCandidate:
    source: str
    source_id: str
    business_name: str
    category: str = ""
    address: str = ""
    city: str = ""
    country: str = ""
    phone: str = ""
    website_url: str = ""
    email: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class DiscoveryProvider(Protocol):
    def search(self, *, category: str, location: str, country: str = "", query: str = "", limit: int = 100) -> List[LeadCandidate]:
        """Return at most ``limit`` candidates without writing to the database."""
        ...
