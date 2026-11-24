import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import psycopg
from lavlah.public_api import app

class PublicDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("lavlah.public_api.search_directory")
    def test_query_and_projection(self, search):
        search.return_value = [dict(organization_id="id", name="Монгол",
            category_slug="services", description="public", source_url="https://example.test",
            verified_at="2026-01-01", expires_at="2027-01-01", authorization_reference="secret")]
        response = self.client.get("/v1/directory", params={"q":" Монгол ", "category":"services"})
        self.assertEqual(response.status_code, 200)
        search.assert_called_once_with("Монгол", "services", 20, 0)
        self.assertNotIn("authorization_reference", response.json()["items"][0])

    @patch("lavlah.public_api.search_directory")
    def test_invalid_limits(self, search):
        for params in ({"limit":101}, {"offset":-1}, {"category":"bad slug"}, {"q":"x"*121}):
            self.assertEqual(self.client.get("/v1/directory", params=params).status_code, 422)
        search.assert_not_called()

    @patch("lavlah.public_api.search_directory")
    def test_no_results(self, search):
        search.return_value = []
        self.assertEqual(self.client.get("/v1/directory").json()["items"], [])

    @patch("lavlah.public_api.search_directory")
    def test_database_failure(self, search):
        search.side_effect = psycopg.OperationalError("private credential")
        response = self.client.get("/v1/directory")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private credential", response.text)
