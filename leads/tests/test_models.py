from django.db import IntegrityError, transaction
from django.test import TestCase

from leads.models import Campaign, Lead, LeadNote, LighthouseResult


class ModelTests(TestCase):
    def setUp(self):
        self.campaign = Campaign.objects.create(name="Athens Hair", search_term="hair_salon", location="Athens")
        self.lead = Lead.objects.create(campaign=self.campaign, source="overpass", source_id="node:1", business_name="Salon One")

    def test_source_identity_is_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): Lead.objects.create(source="overpass", source_id="node:1", business_name="Duplicate")

    def test_notes_preserve_history(self):
        first = LeadNote.objects.create(lead=self.lead, text="First")
        second = LeadNote.objects.create(lead=self.lead, text="Second")
        self.assertEqual(list(self.lead.notes.values_list("text", flat=True)), ["Second", "First"])

    def test_latest_lighthouse_by_strategy(self):
        LighthouseResult.objects.create(lead=self.lead, strategy="mobile", performance=40)
        latest = LighthouseResult.objects.create(lead=self.lead, strategy="mobile", performance=80)
        desktop = LighthouseResult.objects.create(lead=self.lead, strategy="desktop", performance=90)
        self.assertEqual(self.lead.latest_mobile_result, latest)
        self.assertEqual(self.lead.latest_desktop_result, desktop)

    def test_priority_score_is_explainable_and_capped(self):
        self.lead.email = "confirmed@example.com"; self.lead.save()
        LighthouseResult.objects.create(lead=self.lead, strategy="mobile", performance=20, accessibility=60, seo=70)
        score, reasons = self.lead.calculate_priority_score()
        self.assertEqual(score, 100)
        self.assertIn("No website listed: +40", reasons)

    def test_status_choices_and_do_not_contact(self):
        self.assertIn(("follow_up", "Follow up"), Lead.Status.choices)
        self.lead.do_not_contact = True; self.lead.status = Lead.Status.DO_NOT_CONTACT; self.lead.save()
        self.assertTrue(self.lead.do_not_contact)
