import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction

from leads.models import Campaign, Lead, normalize_domain
from leads.providers.base import LeadCandidate
from leads.services.deduplication import assess_duplicate

logger = logging.getLogger(__name__)


@dataclass
class DiscoverySummary:
    created_with_website: int = 0
    created_without_website: int = 0
    exact_duplicates: int = 0
    probable_duplicates: int = 0
    invalid: int = 0


def collect_candidates(campaign: Campaign, candidates):
    """Persist a bounded, idempotent candidate batch for one campaign."""
    summary = DiscoverySummary()
    for candidate in candidates:
        if summary.created_with_website >= campaign.target_with_website and summary.created_without_website >= campaign.target_without_website:
            break
        if not candidate.source_id or not candidate.business_name.strip():
            summary.invalid += 1
            continue
        domain = normalize_domain(candidate.website_url)
        if candidate.website_url and not domain:
            summary.invalid += 1
            continue
        if domain and summary.created_with_website >= campaign.target_with_website:
            continue
        if not domain and summary.created_without_website >= campaign.target_without_website:
            continue
        duplicate = assess_duplicate(candidate)
        if duplicate.exact:
            summary.exact_duplicates += 1
            continue
        if duplicate.probable:
            summary.probable_duplicates += 1
            logger.warning("Probable duplicate source=%s source_id=%s reason=%s", candidate.source, candidate.source_id, duplicate.reason)
            continue
        try:
            with transaction.atomic():
                lead = Lead.objects.create(
                    campaign=campaign, source=candidate.source, source_id=candidate.source_id,
                    business_name=candidate.business_name.strip(), category=candidate.category,
                    address=candidate.address, city=candidate.city, country=candidate.country,
                    latitude=candidate.latitude, longitude=candidate.longitude, phone=candidate.phone,
                    website_url=candidate.website_url, email=candidate.email,
                    website_verification_status=(Lead.WebsiteVerification.NOT_CHECKED if domain else Lead.WebsiteVerification.CONFIRMED_NONE),
                )
                lead.recalculate_priority()
        except IntegrityError:
            summary.exact_duplicates += 1
            continue
        if domain:
            summary.created_with_website += 1
        else:
            summary.created_without_website += 1
    return summary
