import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from math import asin, cos, radians, sin, sqrt
from typing import Optional

from leads.models import Lead, normalize_domain
from leads.providers.base import LeadCandidate


def normalize_identity(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


@dataclass(frozen=True)
class DuplicateAssessment:
    exact: bool = False
    probable: bool = False
    reason: str = ""


def assess_duplicate(candidate: LeadCandidate) -> DuplicateAssessment:
    if Lead.objects.filter(source=candidate.source, source_id=candidate.source_id).exists():
        return DuplicateAssessment(exact=True, reason="same source record")
    domain = normalize_domain(candidate.website_url)
    if domain and Lead.objects.filter(normalized_domain=domain).exists():
        return DuplicateAssessment(probable=True, reason="same normalized domain")
    name = normalize_identity(candidate.business_name)
    phone = normalize_identity(candidate.phone)
    address = normalize_identity(candidate.address)
    possible = Lead.objects.filter(business_name__iexact=candidate.business_name)[:30]
    for lead in possible:
        if phone and phone == normalize_identity(lead.phone):
            return DuplicateAssessment(probable=True, reason="same name and phone")
        if address and address == normalize_identity(lead.address):
            return DuplicateAssessment(probable=True, reason="same name and address")
        if _nearby(candidate, lead) and SequenceMatcher(None, name, normalize_identity(lead.business_name)).ratio() >= 0.9:
            return DuplicateAssessment(probable=True, reason="similar nearby business")
    return DuplicateAssessment()


def _nearby(candidate, lead):
    if None in (candidate.latitude, candidate.longitude, lead.latitude, lead.longitude):
        return False
    lat1, lon1, lat2, lon2 = map(radians, (candidate.latitude, candidate.longitude, lead.latitude, lead.longitude))
    distance = 2 * 6371 * asin(sqrt(sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin((lon2-lon1)/2)**2))
    return distance <= 0.2
