from dataclasses import dataclass

from django.conf import settings
from django.db import OperationalError, ProgrammingError

from leads.models import IntegrationSettings


@dataclass(frozen=True)
class RuntimeSettings:
    google_places_enabled: bool
    google_places_api_key: str
    google_pagespeed_api_key: str
    overpass_api_url: str
    outbound_user_agent: str
    email_backend: str
    email_host: str
    email_port: int
    email_host_user: str
    email_host_password: str
    email_use_tls: bool
    email_use_ssl: bool
    default_from_email: str


def get_runtime_settings():
    """Read dashboard settings, falling back safely before migrations exist."""
    try:
        configured = IntegrationSettings.objects.order_by("pk").first()
    except (OperationalError, ProgrammingError):
        configured = None
    if configured:
        return RuntimeSettings(
            google_places_enabled=configured.google_places_enabled,
            google_places_api_key=configured.google_places_api_key,
            google_pagespeed_api_key=configured.google_pagespeed_api_key,
            overpass_api_url=configured.overpass_api_url,
            outbound_user_agent=configured.outbound_user_agent,
            email_backend=configured.email_backend,
            email_host=configured.email_host,
            email_port=configured.email_port,
            email_host_user=configured.email_host_user,
            email_host_password=configured.email_host_password,
            email_use_tls=configured.email_use_tls,
            email_use_ssl=configured.email_use_ssl,
            default_from_email=configured.default_from_email,
        )
    google_config = settings.LEAD_PROVIDERS.get("google_places", {})
    return RuntimeSettings(
        google_places_enabled=bool(google_config.get("enabled")),
        google_places_api_key=google_config.get("api_key", ""),
        google_pagespeed_api_key=settings.GOOGLE_PAGESPEED_API_KEY,
        overpass_api_url=settings.OVERPASS_API_URL,
        outbound_user_agent=settings.OUTBOUND_USER_AGENT,
        email_backend=settings.EMAIL_BACKEND,
        email_host=settings.EMAIL_HOST,
        email_port=settings.EMAIL_PORT,
        email_host_user=settings.EMAIL_HOST_USER,
        email_host_password=settings.EMAIL_HOST_PASSWORD,
        email_use_tls=settings.EMAIL_USE_TLS,
        email_use_ssl=getattr(settings, "EMAIL_USE_SSL", False),
        default_from_email=settings.DEFAULT_FROM_EMAIL,
    )
