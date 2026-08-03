from django.test import SimpleTestCase

from leads.models import normalize_domain


class DomainTests(SimpleTestCase):
    def test_normalization_examples(self):
        cases = {
            "https://www.example.com/services/": "example.com",
            "http://example.com": "example.com",
            "https://example.com/?ref=maps": "example.com",
            "EXAMPLE.COM/path": "example.com",
            "https://example.com.": "example.com",
            "": "", "not a valid url": "",
        }
        for value, expected in cases.items():
            with self.subTest(value=value): self.assertEqual(normalize_domain(value), expected)

    def test_international_domain_uses_idna(self):
        self.assertEqual(normalize_domain("https://www.παράδειγμα.gr/path"), "xn--hxajbheg2az3al.gr")
