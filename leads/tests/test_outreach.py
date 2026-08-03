from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from leads.models import Lead, OutreachMessage
from leads.services.outreach import send_email_message


class OutreachTests(TestCase):
    def setUp(self):
        self.lead = Lead.objects.create(source="x", source_id="1", business_name="One", email="one@example.com")
        self.message = OutreachMessage.objects.create(lead=self.lead, channel="email", recipient="one@example.com", subject="Hello", body="Body")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_success_marks_sent_and_contacted(self):
        self.assertTrue(send_email_message(self.message)); self.message.refresh_from_db(); self.lead.refresh_from_db()
        self.assertEqual(self.message.status, "sent"); self.assertEqual(self.lead.status, "contacted")

    @patch("leads.services.outreach.send_mail", side_effect=RuntimeError("SMTP down"))
    def test_failure_is_saved_and_status_unchanged(self, send):
        self.assertFalse(send_email_message(self.message)); self.message.refresh_from_db(); self.lead.refresh_from_db()
        self.assertEqual(self.message.status, "failed"); self.assertEqual(self.lead.status, "new"); self.assertEqual(self.message.body, "Body")

    def test_do_not_contact_and_invalid_recipient_are_blocked(self):
        self.lead.do_not_contact = True; self.lead.save()
        with self.assertRaises(ValidationError): send_email_message(self.message)
        self.lead.do_not_contact = False; self.lead.save(); self.message.recipient = "bad"
        with self.assertRaises(ValidationError): send_email_message(self.message)
