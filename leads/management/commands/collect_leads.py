import logging

from django.core.management.base import BaseCommand

from leads.models import Campaign
from leads.providers.base import ProviderError
from leads.providers.registry import get_provider
from leads.services.discovery import collect_candidates

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Discover new leads for active campaigns."

    def add_arguments(self, parser):
        parser.add_argument("--campaign-id", dest="campaign_ids", action="append", type=int)

    def handle(self, *args, **options):
        campaigns = Campaign.objects.filter(is_active=True)
        if options.get("campaign_ids"):
            campaigns = campaigns.filter(pk__in=options["campaign_ids"])
        total_campaigns = total_created = total_errors = 0
        for campaign in campaigns.iterator():
            total_campaigns += 1
            try:
                provider = get_provider(campaign.provider)
                request_limit = max(100, (campaign.target_with_website + campaign.target_without_website) * 5)
                candidates = provider.search(
                    category=campaign.search_term,
                    location=campaign.location,
                    country=campaign.country,
                    query=campaign.text_search_query,
                    limit=request_limit,
                )
                summary = collect_candidates(campaign, candidates)
            except ProviderError as exc:
                total_errors += 1
                logger.error("Campaign collection failed campaign=%s error=%s", campaign.pk, exc)
                self.stderr.write(f"Campaign: {campaign.name}\nProvider error: {exc}")
                continue
            total_created += summary.created_with_website + summary.created_without_website
            self.stdout.write(
                f"Campaign: {campaign.name}\n"
                f"Target with website: {campaign.target_with_website}\n"
                f"Target without website: {campaign.target_without_website}\n"
                f"Created with website: {summary.created_with_website}\n"
                f"Created without website: {summary.created_without_website}\n"
                f"Exact duplicates skipped: {summary.exact_duplicates}\n"
                f"Probable duplicates skipped or flagged: {summary.probable_duplicates}\n"
                f"Invalid records skipped: {summary.invalid}\nProvider errors: 0"
            )
        self.stdout.write(self.style.SUCCESS(f"Collection summary: campaigns={total_campaigns}, created={total_created}, provider_errors={total_errors}"))
