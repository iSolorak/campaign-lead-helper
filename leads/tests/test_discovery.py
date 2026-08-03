from django.test import TestCase

from leads.models import Campaign, Lead
from leads.providers.base import LeadCandidate
from leads.services.discovery import collect_candidates


class DiscoveryTests(TestCase):
    def setUp(self):
        self.campaign = Campaign.objects.create(name="Test", search_term="cafe", location="Athens", target_with_website=2, target_without_website=2)

    def candidates(self):
        return [
            LeadCandidate("overpass", "node:1", "One", website_url="https://one.test"),
            LeadCandidate("overpass", "node:2", "Two", website_url="https://two.test"),
            LeadCandidate("overpass", "node:3", "Three"), LeadCandidate("overpass", "node:4", "Four"),
            LeadCandidate("overpass", "node:5", "Five"),
        ]

    def test_targets_and_idempotency(self):
        first = collect_candidates(self.campaign, self.candidates())
        second = collect_candidates(self.campaign, self.candidates())
        self.assertEqual((first.created_with_website, first.created_without_website), (2, 2))
        self.assertEqual(Lead.objects.count(), 5); self.assertEqual(second.exact_duplicates, 4)
        self.assertEqual(Lead.objects.values("source", "source_id").distinct().count(), 5)

    def test_probable_domain_duplicate_is_flagged(self):
        Lead.objects.create(source="manual", source_id="1", business_name="Other", website_url="https://www.one.test/path")
        summary = collect_candidates(self.campaign, [LeadCandidate("overpass", "node:9", "One branch", website_url="http://one.test")])
        self.assertEqual(summary.probable_duplicates, 1); self.assertEqual(Lead.objects.count(), 1)

    def test_exhausted_results_do_not_overfill(self):
        summary = collect_candidates(self.campaign, [LeadCandidate("overpass", "node:1", "Only")])
        self.assertEqual(summary.created_without_website, 1)
