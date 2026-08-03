import logging
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from django.conf import settings
from django.utils import timezone

from leads.models import WebsiteInspection
from .url_safety import validate_public_http_url
from .runtime_settings import get_runtime_settings

logger = logging.getLogger(__name__)


class WebsiteInspectionError(Exception):
    pass


class _HomepageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title, self.description = "", ""
        self.links, self.has_viewport = [], False
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title": self._in_title = True
        if tag == "a" and attrs.get("href"): self.links.append(attrs["href"])
        if tag == "meta" and attrs.get("name", "").lower() == "description": self.description = attrs.get("content", "")[:2000]
        if tag == "meta" and attrs.get("name", "").lower() == "viewport": self.has_viewport = True

    def handle_endtag(self, tag):
        if tag == "title": self._in_title = False

    def handle_data(self, data):
        if self._in_title: self.title = (self.title + data).strip()[:500]


def inspect_lead_website(lead, http_client=requests):
    """Inspect one bounded homepage response; never recursively crawl."""
    if not lead.has_website:
        raise WebsiteInspectionError("Lead has no website listed")
    url = validate_public_http_url(lead.website_url)
    user_agent = get_runtime_settings().outbound_user_agent
    headers = {"User-Agent": user_agent, "Accept": "text/html"}
    defaults = {"inspected_at": timezone.now()}
    try:
        robots_url = urljoin(url, "/robots.txt")
        robots_response = _safe_get(http_client, robots_url, headers, (5, 10), stream=False)
        robots = RobotFileParser()
        robots.set_url(robots_url)
        robots.parse(robots_response.text[:200000].splitlines() if robots_response.ok else [])
        defaults["robots_allowed"] = robots.can_fetch(user_agent, url)
        if not defaults["robots_allowed"]:
            defaults["error_message"] = "Inspection blocked by robots.txt"
            return WebsiteInspection.objects.update_or_create(lead=lead, defaults=defaults)[0]
        response = _safe_get(http_client, url, headers, (5, 15), stream=True)
        response.raise_for_status()
        final_url = validate_public_http_url(response.url)
        content = response.content[:1000000]
        parser = _HomepageParser()
        parser.feed(content.decode(response.encoding or "utf-8", errors="replace"))
        lowered_links = [link.lower() for link in parser.links]
        defaults.update(
            final_url=final_url, http_status=response.status_code, page_title=parser.title,
            meta_description=parser.description, has_https=urlsplit(final_url).scheme == "https",
            has_viewport_meta=parser.has_viewport,
            has_contact_page=any("contact" in link for link in lowered_links),
            has_privacy_page=any("privacy" in link for link in lowered_links), error_message="",
        )
    except Exception as exc:
        logger.warning("Website inspection failed lead=%s error=%s", lead.pk, exc)
        defaults["error_message"] = str(exc)[:1000]
    return WebsiteInspection.objects.update_or_create(lead=lead, defaults=defaults)[0]


def _safe_get(http_client, url, headers, timeout, stream, max_redirects=3):
    """Follow a small number of redirects, validating every destination first."""
    current = validate_public_http_url(url)
    for _ in range(max_redirects + 1):
        response = http_client.get(current, headers=headers, timeout=timeout, allow_redirects=False, stream=stream)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        destination = response.headers.get("Location")
        if not destination:
            raise WebsiteInspectionError("Redirect response has no Location header")
        current = validate_public_http_url(urljoin(current, destination))
    raise WebsiteInspectionError("Too many redirects")
