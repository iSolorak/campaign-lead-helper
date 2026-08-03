from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings

from leads.services.places import (
    GooglePlacesClient,
    PlacesAPIError,
    PlacesConfigurationError,
)
from leads.providers.google_places import GooglePlacesProvider
from leads.services.places import TextSearchResult


class GooglePlacesClientTests(SimpleTestCase):
    @patch("leads.services.places.requests.post")
    def test_text_search_returns_typed_results(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "places": [
                {
                    "id": "ChIJ-example",
                    "displayName": {"text": "Example Coffee", "languageCode": "en"},
                    "formattedAddress": "1 Main Street, Athens",
                    "location": {"latitude": 37.98, "longitude": 23.72},
                    "types": ["cafe", "food"],
                    "websiteUri": "https://example.test",
                    "rating": 4.6,
                    "userRatingCount": 123,
                }
            ],
            "nextPageToken": "next-page",
        }
        post.return_value = response

        result = GooglePlacesClient(api_key="test-key").text_search(
            "coffee in Athens", page_size=10, language_code="en"
        )

        self.assertEqual(result.next_page_token, "next-page")
        self.assertEqual(len(result.places), 1)
        self.assertEqual(result.places[0].place_id, "ChIJ-example")
        self.assertEqual(result.places[0].display_name, "Example Coffee")
        self.assertEqual(result.places[0].types, ("cafe", "food"))
        post.assert_called_once()
        request = post.call_args
        self.assertEqual(request.kwargs["json"]["textQuery"], "coffee in Athens")
        self.assertEqual(request.kwargs["json"]["pageSize"], 10)
        self.assertEqual(request.kwargs["timeout"], (3.05, 10.0))
        self.assertEqual(request.kwargs["headers"]["X-Goog-Api-Key"], "test-key")

    @patch("leads.services.places.requests.post")
    def test_field_mask_and_timeout_are_configurable(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"places": []}
        post.return_value = response
        client = GooglePlacesClient(
            api_key="test-key",
            field_mask=("places.id", "places.displayName"),
            timeout=2.5,
        )

        client.text_search("bakery", field_mask="places.id, places.websiteUri")

        request = post.call_args
        self.assertEqual(
            request.kwargs["headers"]["X-Goog-FieldMask"],
            "places.id,places.websiteUri",
        )
        self.assertEqual(request.kwargs["timeout"], 2.5)

    @patch("leads.services.places.requests.post")
    def test_http_errors_are_wrapped(self, post):
        response = Mock()
        response.status_code = 403
        response.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
        response.json.return_value = {
            "error": {
                "status": "PERMISSION_DENIED",
                "message": "Places API (New) is blocked for this key",
            }
        }
        post.return_value = response

        with self.assertRaisesRegex(
            PlacesAPIError, r"Places API \(New\) is blocked for this key"
        ):
            GooglePlacesClient(api_key="test-key").text_search("restaurant")

    @patch("leads.services.places.requests.post")
    def test_invalid_json_is_wrapped(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("invalid JSON")
        post.return_value = response

        with self.assertRaisesRegex(PlacesAPIError, "invalid JSON"):
            GooglePlacesClient(api_key="test-key").text_search("restaurant")

    @override_settings(GOOGLE_PLACES_API_KEY="")
    @patch("leads.services.places.requests.post")
    def test_missing_api_key_fails_without_an_http_call(self, post):
        with self.assertRaises(PlacesConfigurationError):
            GooglePlacesClient()

        post.assert_not_called()

    def test_provider_uses_free_text_query_and_appends_country(self):
        provider = GooglePlacesProvider.__new__(GooglePlacesProvider)
        provider.client = Mock()
        provider.client.text_search.return_value = TextSearchResult(places=())

        provider.search(
            category="bar",
            location="Athens",
            country="Greece",
            query="Bar near Athens",
            limit=10,
        )

        self.assertEqual(
            provider.client.text_search.call_args.args[0],
            "Bar near Athens, Greece",
        )

    @patch("leads.services.places.requests.post")
    def test_empty_query_fails_without_an_http_call(self, post):
        client = GooglePlacesClient(api_key="test-key")

        with self.assertRaises(ValueError):
            client.text_search("  ")

        post.assert_not_called()
