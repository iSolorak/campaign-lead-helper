from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase

from leads.models import Campaign
from leads.providers.base import ProviderResponseError


class CollectionCommandTests(TestCase):
    @patch("leads.management.commands.collect_leads.get_provider")
    def test_one_campaign_failure_does_not_stop_others(self, get_provider):
        Campaign.objects.create(name="Broken", search_term="cafe", location="A")
        Campaign.objects.create(name="Working", search_term="dentist", location="B")
        broken, working = Mock(), Mock()
        broken.search.side_effect = ProviderResponseError("outage")
        working.search.return_value = []
        get_provider.side_effect = [broken, working]
        stdout, stderr = StringIO(), StringIO()
        call_command("collect_leads", stdout=stdout, stderr=stderr)
        self.assertIn("provider_errors=1", stdout.getvalue())
        self.assertEqual(working.search.call_count, 1)
