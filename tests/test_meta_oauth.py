import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from flashwire.credentials import read_token, save_token
from flashwire.instagram import Instagram
from flashwire.meta_oauth import LOCAL, oauth_app


class MetaOAuthTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.callback = "https://artwork.example.org/auth/callback"
        self.credentials = Path("data/fixture.dpapi")
        self.factory = Mock()
        self.factory.return_value.preflight.return_value = "Verified. No post was sent."
        self.app = oauth_app("123", "456", "v27.0", self.callback, "fixture-secret", "789",
                             "flashwire", "https://artwork.example.org", self.credentials,
                             client_factory=self.factory, session_clock=lambda: self.now)
        self.client = self.app.test_client()
        self.origin = {"Origin": LOCAL}

    def start(self):
        home = self.client.get("/", base_url=LOCAL)
        token = re.search(rb"name=start_token value='([^']+)'", home.data)[1].decode()
        result = self.client.post("/meta/start", base_url=LOCAL, headers={"Origin": "null"},
                                  data={"start_token": token})
        self.assertEqual(result.status_code, 303)
        url = urlsplit(result.headers["Location"])
        self.assertEqual(url.hostname, "www.facebook.com")
        self.assertEqual(url.path, "/dialog/oauth")
        values = parse_qs(url.query)
        self.assertEqual(values["redirect_uri"], [self.callback])
        self.assertEqual(values["config_id"], ["456"])
        self.assertEqual(values["override_default_response_type"], ["true"])
        self.assertNotIn("fixture-secret", result.headers["Location"])
        return values["state"][0]

    @patch("flashwire.meta_oauth.save_token")
    @patch.object(Instagram, "exchange_code", return_value="fixture-token")
    def test_only_verified_token_is_saved(self, exchange, save):
        state = self.start()
        result = self.client.post("/meta/complete", data={"state": state, "code": "fixture-code"},
                                  base_url=LOCAL, headers=self.origin)
        self.assertEqual(result.status_code, 200)
        self.assertNotIn(b"fixture-token", result.data)
        self.assertEqual(result.headers["Cache-Control"], "no-store")
        exchange.assert_called_once_with("v27.0", "123", "fixture-secret", self.callback, "fixture-code")
        save.assert_called_once_with(self.credentials, "fixture-token")
        self.factory.return_value.preflight.assert_called_once_with("flashwire", None)
        replay = self.client.post("/meta/complete", data={"state": state, "code": "fixture-code"},
                                  base_url=LOCAL, headers=self.origin)
        self.assertEqual(replay.status_code, 400)

    @patch.object(Instagram, "exchange_code")
    def test_rejects_cross_origin_expired_and_wrong_state(self, exchange):
        self.assertEqual(self.client.post("/meta/start", base_url=LOCAL).status_code, 403)
        state = self.start()
        for origin, wrong_state, expected in [("https://example.com", state, 403), (LOCAL, "X" * 43, 400)]:
            result = self.client.post("/meta/complete", data={"state": wrong_state, "code": "fixture-code"},
                                      base_url=LOCAL, headers={"Origin": origin})
            self.assertEqual(result.status_code, expected)
        state = self.start()
        self.now += 601
        result = self.client.post("/meta/complete", data={"state": state, "code": "fixture-code"},
                                  base_url=LOCAL, headers=self.origin)
        self.assertEqual(result.status_code, 400)
        exchange.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_windows_credential_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.dpapi"
            save_token(path, "fixture-token")
            self.assertNotIn(b"fixture-token", path.read_bytes())
            self.assertEqual(read_token(path), "fixture-token")
