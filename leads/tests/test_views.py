from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from unittest.mock import Mock, patch

from leads.models import Campaign, EmailTemplate, IntegrationSettings, Lead, LighthouseResult, OutreachMessage


class ViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "owner", password="secret", is_staff=True
        )
        self.lead = Lead.objects.create(source="x", source_id="1", business_name="Cafe Alpha", city="Athens")

    def test_login_required(self):
        response = self.client.get(reverse("lead-list")); self.assertEqual(response.status_code, 302); self.assertIn("/accounts/login/", response.url)

    def test_non_staff_users_cannot_access_dashboard_routes(self):
        non_staff = get_user_model().objects.create_user("viewer", password="secret")
        self.client.force_login(non_staff)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("campaign-list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("lead-list")).status_code, 403)

    def test_filtering_and_pagination_page(self):
        self.client.force_login(self.user)
        Lead.objects.create(source="x", source_id="2", business_name="Dentist Beta", city="Piraeus")
        response = self.client.get(reverse("lead-list"), {"q": "Alpha", "city": "Athens"})
        self.assertContains(response, "Cafe Alpha"); self.assertNotContains(response, "Dentist Beta")
        self.assertContains(response, "Not fetched")

    def test_lighthouse_results_are_visible_on_lead_pages(self):
        self.client.force_login(self.user)
        LighthouseResult.objects.create(
            lead=self.lead, strategy="mobile", performance=73,
            accessibility=91, best_practices=88, seo=95,
        )
        detail = self.client.get(reverse("lead-detail", args=[self.lead.pk]))
        self.assertContains(detail, "Performance 73")
        self.assertContains(detail, "Accessibility 91")
        listing = self.client.get(reverse("lead-list"))
        self.assertContains(listing, ">73</span>", html=False)

    def test_staff_can_confirm_and_delete_multiple_selected_leads(self):
        self.client.force_login(self.user)
        second = Lead.objects.create(
            source="manual", source_id="2", business_name="Second"
        )
        untouched = Lead.objects.create(
            source="manual", source_id="3", business_name="Untouched"
        )
        url = reverse("lead-bulk-delete")

        confirmation = self.client.post(
            url, {"lead_ids": [self.lead.pk, second.pk]}
        )

        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, "Delete selected leads?")
        self.assertEqual(Lead.objects.count(), 3)

        response = self.client.post(
            url,
            {
                "lead_ids": [self.lead.pk, second.pk],
                "confirm": "yes",
            },
        )

        self.assertRedirects(response, reverse("lead-list"))
        self.assertFalse(
            Lead.objects.filter(pk__in=[self.lead.pk, second.pk]).exists()
        )
        self.assertTrue(Lead.objects.filter(pk=untouched.pk).exists())

    def test_bulk_delete_requires_post_and_a_selection(self):
        self.client.force_login(self.user)
        url = reverse("lead-bulk-delete")
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)
        self.assertRedirects(response, reverse("lead-list"))
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())

    @patch("leads.views.analyze_lead")
    def test_staff_can_analyze_multiple_selected_leads(self, analyze_lead):
        self.client.force_login(self.user)
        website_lead = Lead.objects.create(
            source="manual",
            source_id="website-lead",
            business_name="Website Lead",
            website_url="https://example.com",
        )
        analyze_lead.return_value = [
            Mock(error_message=""),
            Mock(error_message=""),
        ]
        url = reverse("lead-bulk-analyze")

        confirmation = self.client.post(
            url, {"lead_ids": [self.lead.pk, website_lead.pk]}
        )

        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, "1</strong> of 2 selected")
        analyze_lead.assert_not_called()

        response = self.client.post(
            url,
            {
                "lead_ids": [self.lead.pk, website_lead.pk],
                "confirm": "yes",
            },
        )

        self.assertRedirects(response, reverse("lead-list"))
        analyze_lead.assert_called_once_with(website_lead, force=True)

    def test_bulk_analyze_requires_post_and_a_selection(self):
        self.client.force_login(self.user)
        url = reverse("lead-bulk-analyze")
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), reverse("lead-list"))

    def test_integration_settings_are_saved_without_exposing_keys(self):
        self.client.force_login(self.user)
        url = reverse("integration-settings")
        response = self.client.post(url, {
            "google_places_enabled": "on",
            "google_places_api_key": "places-secret",
            "google_pagespeed_api_key": "pagespeed-secret",
            "overpass_api_url": "https://overpass.example/api",
            "outbound_user_agent": "Leadboard/1.0 (contact: me@example.com)",
            "email_backend": "django.core.mail.backends.smtp.EmailBackend",
            "email_host": "smtp.example.com", "email_port": 587,
            "email_host_user": "mailer@example.com",
            "email_host_password": "smtp-secret", "email_use_tls": "on",
            "default_from_email": "mailer@example.com",
        })
        self.assertRedirects(response, url)
        configured = IntegrationSettings.objects.get()
        self.assertTrue(configured.google_places_enabled)
        self.assertEqual(configured.google_places_api_key, "places-secret")
        self.assertEqual(configured.google_pagespeed_api_key, "pagespeed-secret")
        self.assertEqual(configured.email_host_password, "smtp-secret")
        page = self.client.get(url)
        self.assertNotContains(page, "places-secret")
        self.assertNotContains(page, "pagespeed-secret")
        self.assertNotContains(page, "smtp-secret")

        self.client.post(url, {
            "google_places_enabled": "on",
            "google_places_api_key": "",
            "google_pagespeed_api_key": "",
            "overpass_api_url": "https://overpass.example/api",
            "outbound_user_agent": "Leadboard/1.0 (contact: me@example.com)",
            "email_backend": "django.core.mail.backends.smtp.EmailBackend",
            "email_host": "smtp.example.com", "email_port": 587,
            "email_host_user": "mailer@example.com",
            "email_host_password": "", "email_use_tls": "on",
            "default_from_email": "mailer@example.com",
        })
        configured.refresh_from_db()
        self.assertEqual(configured.google_places_api_key, "places-secret")
        self.assertEqual(configured.email_host_password, "smtp-secret")

    def test_non_staff_cannot_access_integration_settings(self):
        non_staff = get_user_model().objects.create_user("settings-viewer")
        self.client.force_login(non_staff)
        self.assertEqual(
            self.client.get(reverse("integration-settings")).status_code, 403
        )

    @patch("leads.views.GooglePlacesClient")
    def test_google_places_connection_can_be_tested_from_settings(self, client):
        self.client.force_login(self.user)
        IntegrationSettings.objects.create(google_places_api_key="secret")
        client.return_value.text_search.return_value.places = ()

        response = self.client.post(reverse("test-google-places"))

        self.assertRedirects(response, reverse("integration-settings"))
        client.return_value.text_search.assert_called_once()
        messages = list(response.wsgi_request._messages)
        self.assertIn("connection succeeded", str(messages[0]).lower())

    def test_dashboard_renders_summary(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New leads")
        self.assertContains(response, "Analyze pending websites")

    @patch("leads.views.call_command")
    def test_pending_lighthouse_analysis_runs_from_dashboard(self, call_command):
        self.client.force_login(self.user)
        response = self.client.post(reverse("analyze-pending-websites"))
        self.assertRedirects(response, reverse("dashboard"))
        call_command.assert_called_once()
        self.assertEqual(call_command.call_args.args[0], "analyze_pending_leads")
        self.assertEqual(
            self.client.get(reverse("analyze-pending-websites")).status_code,
            405,
        )

    def test_theme_defaults_dark_and_light_choice_persists_in_session(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'data-theme="dark"')
        response = self.client.post(
            reverse("toggle-theme"), {"next": reverse("dashboard")}
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(self.client.session["theme"], "light")
        self.assertContains(
            self.client.get(reverse("campaign-list")), 'data-theme="light"'
        )
        self.client.post(reverse("toggle-theme"), {"next": reverse("dashboard")})
        self.assertEqual(self.client.session["theme"], "dark")

    def test_add_note_status_and_manual_outreach(self):
        self.client.force_login(self.user)
        self.client.post(reverse("add-note", args=[self.lead.pk]), {"text": "Review later"})
        self.client.post(reverse("update-status", args=[self.lead.pk]), {"status": "ready"})
        self.client.post(reverse("manual-outreach", args=[self.lead.pk]), {"channel": "instagram", "recipient": "@cafe", "body": "Sent manually", "status": "sent"})
        self.lead.refresh_from_db(); self.assertEqual(self.lead.notes.count(), 1); self.assertEqual(self.lead.status, "ready"); self.assertEqual(self.lead.outreach_messages.get().channel, "instagram")

    def test_send_email_requires_post(self):
        self.client.force_login(self.user)
        message = OutreachMessage.objects.create(lead=self.lead, channel="email", recipient="a@example.com", subject="Hi", body="Body")
        self.assertEqual(self.client.get(reverse("send-email", args=[message.pk])).status_code, 200)

    def test_campaigns_can_be_created_and_edited_from_dashboard(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("campaign-create"), {
            "name": "Athens Barbers", "search_term": "Barber Shops",
            "location": "Athens", "country": "Greece", "provider": "overpass", "is_active": "on",
            "target_with_website": 10, "target_without_website": 10,
        })
        self.assertRedirects(response, reverse("campaign-list"))
        campaign = Campaign.objects.get(name="Athens Barbers")
        self.assertEqual(campaign.search_term, "hair_salon")
        self.assertContains(self.client.get(reverse("campaign-list")), "Athens Barbers")

    def test_google_campaign_accepts_a_free_text_query(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("campaign-create"), {
            "name": "Relevant Athens Bars", "search_term": "bar",
            "text_search_query": "Bar near Athens", "location": "Athens",
            "country": "Greece", "provider": "google_places", "is_active": "on",
            "target_with_website": 10, "target_without_website": 10,
        })
        self.assertRedirects(response, reverse("campaign-list"))
        campaign = Campaign.objects.get(name="Relevant Athens Bars")
        self.assertEqual(campaign.text_search_query, "Bar near Athens")

    @patch("leads.views.call_command")
    def test_campaign_collection_runs_from_dashboard_with_post(self, call_command):
        self.client.force_login(self.user)
        campaign = Campaign.objects.create(name="Coffee", search_term="coffee", location="Athens")
        response = self.client.post(reverse("campaign-collect", args=[campaign.pk]))
        self.assertRedirects(response, reverse("campaign-list"))
        call_command.assert_called_once()
        self.assertEqual(call_command.call_args.args[0], "collect_leads")
        self.assertEqual(self.client.get(reverse("campaign-collect", args=[campaign.pk])).status_code, 405)

    def test_email_templates_can_be_created_from_dashboard(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("email-template-create"), {
            "name": "Introduction", "subject_template": "Hello {business_name}",
            "body_template": "I found your business in {city}.", "is_active": "on",
        })
        self.assertRedirects(response, reverse("email-template-list"))
        self.assertTrue(EmailTemplate.objects.filter(name="Introduction").exists())

    def test_manual_lead_can_be_created_from_dashboard(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("lead-create"), {
            "business_name": "Manual Shop", "category": "shop", "status": "new",
            "website_verification_status": "not_checked",
        })
        lead = Lead.objects.get(business_name="Manual Shop")
        self.assertRedirects(response, reverse("lead-detail", args=[lead.pk]))
        self.assertEqual(lead.source, "manual")
