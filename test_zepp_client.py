import unittest
from unittest.mock import Mock, patch

from zepp_client import ZeppClient, ZeppError, build_data_json


def response(status_code, body):
    result = Mock()
    result.status_code = status_code
    result.headers = {}
    result.json.return_value = body
    return result


class ZeppClientTests(unittest.TestCase):
    def test_login_uses_structured_form_data(self):
        session = Mock()
        session.headers = {}
        session.post.side_effect = [
            response(200, {"access": "access-code"}),
            response(
                200,
                {"token_info": {"login_token": "login-token", "user_id": "42"}},
            ),
        ]
        client = ZeppClient(session=session)

        token, user_id = client.login("user@example.com", "a&b+c")

        self.assertEqual((token, user_id), ("login-token", "42"))
        first_data = session.post.call_args_list[0].kwargs["data"]
        self.assertEqual(first_data["password"], "a&b+c")
        self.assertEqual(first_data["name"], "user@example.com")

    def test_phone_login_adds_country_prefix(self):
        session = Mock()
        session.headers = {}
        session.post.side_effect = [
            response(200, {"access": "code"}),
            response(
                200,
                {"token_info": {"login_token": "token", "user_id": 123}},
            ),
        ]

        ZeppClient(session=session).login("13800138000", "password")

        first_data = session.post.call_args_list[0].kwargs["data"]
        second_data = session.post.call_args_list[1].kwargs["data"]
        self.assertEqual(first_data["name"], "+8613800138000")
        self.assertEqual(second_data["third_name"], "huami_phone")

    def test_login_exposes_rate_limit_delay(self):
        session = Mock()
        session.headers = {}
        limited = response(429, {})
        limited.headers = {"Retry-After": "90"}
        session.post.return_value = limited

        with self.assertRaises(ZeppError) as caught:
            ZeppClient(session=session).login("user@example.com", "password")

        self.assertEqual(caught.exception.retry_after, 90)

    @patch("zepp_client.get_timestamp", return_value=123456)
    def test_submit_uses_structured_data_and_returns_result(self, _timestamp):
        session = Mock()
        session.headers = {}
        session.post.return_value = response(200, {"message": "success"})

        result = ZeppClient(session=session).submit_steps("42", "app-token", 25000)

        request_data = session.post.call_args.kwargs["data"]
        self.assertIn("userid=42", request_data)
        self.assertIn("last_sync_data_time=123456", request_data)
        self.assertIn("data_json=%5b", request_data)
        self.assertNotIn("data_json=%255b", request_data)
        self.assertEqual(result["steps"], 25000)

    @patch("zepp_client.get_timestamp", return_value=123456)
    def test_submit_marks_expired_token(self, _timestamp):
        session = Mock()
        session.headers = {}
        session.post.return_value = response(401, {"code": 401})

        with self.assertRaises(ZeppError) as caught:
            ZeppClient(session=session).submit_steps("42", "expired", 25000)

        self.assertTrue(caught.exception.auth_expired)

    def test_payload_contains_requested_steps(self):
        payload = build_data_json("2026-06-13", "device", 32869)
        self.assertIn("2026-06-13", payload)
        self.assertIn("32869", payload)
        self.assertIn("device", payload)


if __name__ == "__main__":
    unittest.main()
