import unittest
from fastapi.testclient import TestClient
from lavlah.public_api import app

class MobileUITests(unittest.TestCase):
    def test_home_and_assets(self):
        client = TestClient(app)
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('lang="mn"', page.text)
        self.assertIn('name="viewport"', page.text)
        self.assertIn("Хайх хэрэггүй", page.text)
        for path in ("/ui/style.css", "/ui/app.js"):
            self.assertEqual(client.get(path).status_code, 200)
        self.assertIn("/v1/directory?", client.get("/ui/app.js").text)
