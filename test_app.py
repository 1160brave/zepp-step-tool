import unittest
from unittest.mock import patch

from app import app


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_rejects_invalid_json(self):
        response = self.client.post(
            "/api/submit",
            data="{bad json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_validates_step_range(self):
        response = self.client.post(
            "/api/submit",
            json={"account": "user@example.com", "password": "pw", "steps": 0},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("1~98800", response.get_json()["error"])

    @patch("app.zepp_submit")
    def test_submits_valid_request(self, submit):
        submit.return_value = {"ok": True, "steps": 25000}

        response = self.client.post(
            "/api/submit",
            json={
                "account": " user@example.com ",
                "password": "a&b+c",
                "steps": 25000,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        submit.assert_called_once_with("user@example.com", "a&b+c", 25000)


if __name__ == "__main__":
    unittest.main()
