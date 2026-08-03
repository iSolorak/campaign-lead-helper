from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from leads.models import Lead
from leads.services.pagespeed import analyze_lead


class Command(BaseCommand):
    help = "Force-refresh Lighthouse scores older than a chosen age."

    def add_arguments(self, parser):
        parser.add_argument("--older-than-days", type=int, default=30)

    def handle(self, *args, **options):
        days = options["older_than_days"]
        if days < 0: raise CommandError("--older-than-days must not be negative")
        cutoff = timezone.now() - timedelta(days=days)
        leads = Lead.objects.exclude(normalized_domain="").filter(is_archived=False).exclude(lighthouse_results__checked_at__gte=cutoff).distinct()
        refreshed = failed = 0
        for lead in leads.iterator():
            try: analyze_lead(lead, force=True); refreshed += 1
            except Exception as exc: failed += 1; self.stderr.write(f"Lead {lead.pk}: {exc}")
        self.stdout.write(self.style.SUCCESS(f"Refresh summary: refreshed={refreshed}, failed={failed}"))
