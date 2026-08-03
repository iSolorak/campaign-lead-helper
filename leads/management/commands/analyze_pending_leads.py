from django.core.management.base import BaseCommand

from leads.models import Lead
from leads.services.pagespeed import analyze_lead


class Command(BaseCommand):
    help = "Analyze website leads that have no fresh Lighthouse results."

    def handle(self, *args, **options):
        analyzed = skipped = failed = 0
        for lead in Lead.objects.exclude(normalized_domain="").filter(is_archived=False).iterator():
            try:
                results = analyze_lead(lead)
                if results: analyzed += 1
                else: skipped += 1
            except Exception as exc:
                failed += 1
                self.stderr.write(f"Lead {lead.pk}: {exc}")
        self.stdout.write(self.style.SUCCESS(f"PageSpeed summary: analyzed={analyzed}, fresh_skipped={skipped}, failed={failed}"))
