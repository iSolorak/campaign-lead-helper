from unittest.mock import Mock, patch

import requests
from django.test import TestCase

from leads.models import Lead, LighthouseResult
from leads.services.pagespeed import PageSpeedClient, PageSpeedError, analyze_lead


class PageSpeedTests(TestCase):
    def setUp(self): self.lead = Lead.objects.create(source="x", source_id="1", business_name="One", website_url="https://example.com")

    @patch("leads.services.pagespeed.validate_public_http_url", return_value="https://example.com")
    def test_parses_scores_and_optional_audits(self, validate):
        response = Mock(); response.raise_for_status.return_value = None
        response.json.return_value = {"lighthouseResult": {"finalUrl": "https://www.example.com/", "categories": {"performance": {"score": .82}, "accessibility": {"score": .91}, "best-practices": {"score": .75}, "seo": {"score": 1}}, "audits": {"first-contentful-paint": {"numericValue": 1234}}}}
        client = PageSpeedClient(http_client=Mock(get=Mock(return_value=response)))
        data = client.analyze(self.lead.website_url, "mobile")
        self.assertEqual((data.performance, data.accessibility, data.best_practices, data.seo), (82, 91, 75, 100)); self.assertEqual(data.first_contentful_paint_ms, 1234); self.assertIsNone(data.total_blocking_time_ms)

    @patch("leads.services.pagespeed.validate_public_http_url", return_value="https://example.com")
    def test_timeout(self, validate):
        client = PageSpeedClient(http_client=Mock(get=Mock(side_effect=requests.Timeout())))
        with self.assertRaises(PageSpeedError): client.analyze(self.lead.website_url, "desktop")

    def test_analysis_stores_both_strategies_and_freshness(self):
        client = Mock(); client.analyze.side_effect = lambda url, strategy: __import__("leads.services.pagespeed", fromlist=["PageSpeedData"]).PageSpeedData(strategy, 80, None, None, None, None, None, None, None, url)
        self.assertEqual(len(analyze_lead(self.lead, client=client)), 2)
        self.assertEqual(analyze_lead(self.lead, client=client), [])
        self.assertEqual(len(analyze_lead(self.lead, force=True, client=client)), 2)
        self.assertEqual(LighthouseResult.objects.count(), 4)

    def test_api_failure_is_saved_not_score_zero(self):
        client = Mock(); client.analyze.side_effect = PageSpeedError("outage")
        results = analyze_lead(self.lead, client=client)
        self.assertTrue(all(result.performance is None and result.error_message for result in results))
