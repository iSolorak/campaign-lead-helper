from unittest.mock import Mock

import requests
from django.test import TestCase

from leads.providers.base import ProviderRateLimitError, ProviderResponseError, ProviderTimeoutError, UnsupportedCategoryError
from leads.providers.overpass import OverpassProvider, normalize_category


class OverpassTests(TestCase):
    def provider(self, response=None):
        client = Mock(); client.post.return_value = response
        return OverpassProvider(http_client=client, max_attempts=1), client

    def test_parses_nodes_ways_relations_and_alternate_tags(self):
        response = Mock(status_code=200); response.raise_for_status.return_value = None
        response.json.return_value = {"elements": [
            {"type": "node", "id": 1, "lat": 1, "lon": 2, "tags": {"name": "Node", "contact:website": "https://node.test", "contact:phone": "123", "addr:street": "Main", "addr:housenumber": "1"}},
            {"type": "way", "id": 2, "center": {"lat": 3, "lon": 4}, "tags": {"name": "Way", "url": "way.test"}},
            {"type": "relation", "id": 3, "center": {"lat": 5, "lon": 6}, "tags": {"name": "Relation"}},
            {"type": "node", "id": 4, "tags": {}},
        ]}
        provider, client = self.provider(response)
        results = provider.search(category="cafe", location="Athens")
        self.assertEqual([item.source_id for item in results], ["node:1", "way:2", "relation:3"])
        self.assertEqual(results[0].phone, "123"); self.assertEqual(results[1].latitude, 3.0)
        self.assertEqual(client.post.call_args.kwargs["timeout"], (5.0, 30.0))

    def test_timeout_rate_limit_malformed_and_category(self):
        provider, client = self.provider(); client.post.side_effect = requests.Timeout()
        with self.assertRaises(ProviderTimeoutError): provider.search(category="cafe", location="Athens")
        response = Mock(status_code=429); provider, _ = self.provider(response)
        with self.assertRaises(ProviderRateLimitError): provider.search(category="cafe", location="Athens")
        response = Mock(status_code=200); response.raise_for_status.return_value = None; response.json.side_effect = ValueError()
        provider, _ = self.provider(response)
        with self.assertRaises(ProviderResponseError): provider.search(category="cafe", location="Athens")
        with self.assertRaises(UnsupportedCategoryError): provider.search(category="unknown", location="Athens")

    def test_common_category_names_are_normalized(self):
        self.assertEqual(normalize_category("barber"), "hair_salon")
        self.assertEqual(normalize_category("Barber Shops"), "hair_salon")
        self.assertEqual(normalize_category("coffee"), "cafe")
        self.assertEqual(normalize_category("Coffee Shop"), "cafe")

        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = {"elements": []}
        provider, client = self.provider(response)
        provider.search(category="barber", location="Athens")
        query = client.post.call_args.kwargs["data"]["data"]
        self.assertIn('["shop"="hairdresser"]', query)

    def test_country_scopes_the_city_area(self):
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = {"elements": []}
        provider, client = self.provider(response)

        provider.search(category="cafe", location="Athens", country="Greece")

        query = client.post.call_args.kwargs["data"]["data"]
        self.assertIn('["ISO3166-1"="GR"]', query)
        self.assertIn('["admin_level"="2"]->.countryArea', query)
        self.assertIn('["name"="Athens"]', query)
        self.assertIn('rel["name"="Athens"]["boundary"="administrative"](area.countryArea)', query)
        self.assertIn('["name:en"~"(^| of )Athens$",i]', query)
        self.assertIn('.searchBoundaries map_to_area->.searchArea', query)
        self.assertNotIn('area["name"="Athens"]', query)
        self.assertIn('["amenity"="cafe"](area.countryArea)(area.searchArea)', query)

    def test_explicitly_foreign_results_are_discarded(self):
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = {"elements": [
            {"type": "node", "id": 1, "lat": 37.98, "lon": 23.72,
             "tags": {"name": "Athens Cafe", "addr:country": "GR"}},
            {"type": "node", "id": 2, "lat": 33.95, "lon": -83.38,
             "tags": {"name": "Georgia Cafe", "addr:country": "US"}},
        ]}
        provider, _ = self.provider(response)

        results = provider.search(category="cafe", location="Athens", country="Greece")

        self.assertEqual([item.source_id for item in results], ["node:1"])
        self.assertEqual(results[0].country, "Greece")

    def test_504_fails_over_to_secondary_endpoint(self):
        unavailable = Mock(status_code=504)
        successful = Mock(status_code=200)
        successful.raise_for_status.return_value = None
        successful.json.return_value = {"elements": []}
        client = Mock()
        client.post.side_effect = [unavailable, successful]
        provider = OverpassProvider(
            endpoint="https://primary.example/api/interpreter",
            fallback_endpoints=("https://fallback.example/api/interpreter",),
            http_client=client,
            max_attempts=2,
        )

        self.assertEqual(provider.search(category="cafe", location="Athens"), [])
        self.assertEqual(
            [call.args[0] for call in client.post.call_args_list],
            [
                "https://primary.example/api/interpreter",
                "https://fallback.example/api/interpreter",
            ],
        )

    def test_query_limits_output(self):
        query = OverpassProvider._query("Athens", "Greece", "amenity", "cafe", 25)
        self.assertIn("out center tags 25;", query)
