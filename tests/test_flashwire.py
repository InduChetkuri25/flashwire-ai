import os
import re
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from PIL import Image

from flashwire.art import create_jpeg
from flashwire.desk import approve, new_revision, transaction
from flashwire.instagram import Instagram, PublishingError, publish_due, reconcile
from flashwire.hosting import HostingError, PagesUpload
from flashwire.news import Article, canonical, demo, ingest, update_queue
from flashwire.web import app_for


class DeskTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "state.sqlite"
        self.now = datetime.now(UTC).replace(second=0, microsecond=0)
        title = "Council approves expanded public transport services"
        self.articles = [Article(title, f"https://example{index}.org/story", f"Desk {index}",
                                 f"publisher-{index}", "India", self.now.isoformat())
                         for index in (1, 2)]
        self.copy = ("The city will add more bus routes",
                     "The council backed a plan to expand bus service. The start date is still pending.")
        self.client = Mock()
        self.client.prepare.return_value = "10"
        self.client.publish.return_value = "20"

    def schedule(self, when=None):
        with transaction(self.path) as state:
            update_queue(state, self.articles, self.now)
            story = state["stories"][0]
            approve(story, *self.copy, when or self.now, self.now, confirmed=True)
            return story["id"]

    def test_canonical_duplicate_and_publisher_groups(self):
        self.assertEqual(canonical("https://EXAMPLE.org/story/?utm_source=rss#s"), "https://example.org/story")
        with transaction(self.path) as state:
            self.assertEqual(update_queue(state, self.articles, self.now), 1)
            self.assertEqual(update_queue(state, self.articles, self.now), 0)
            self.assertEqual(len(state["stories"][0]["sources"]), 2)
        with transaction(self.path) as state:
            self.assertEqual(len(state["stories"]), 1)

    def test_single_source_and_discovery_cannot_approve(self):
        with transaction(self.path) as state:
            discovery = Article(**{**vars(self.articles[1]), "discovered": True})
            update_queue(state, [self.articles[0], discovery], self.now)
            with self.assertRaisesRegex(ValueError, "Two separately"):
                approve(state["stories"][0], *self.copy, self.now, self.now, confirmed=True)

    def test_schedule_dry_run_does_not_contact_meta_or_change_status(self):
        self.schedule(self.now + timedelta(minutes=10))
        self.assertEqual(publish_due(self.path, now=self.now), "No eligible scheduled post.")
        self.assertIn("Dry run ready:", publish_due(self.path, now=self.now + timedelta(minutes=10),
                                                   client=self.client))
        self.client.prepare.assert_not_called()
        with transaction(self.path) as state:
            self.assertEqual(state["stories"][0]["status"], "approved")

    def test_stale_approval_returns_to_review(self):
        self.schedule()
        self.assertEqual(publish_due(self.path, now=self.now + timedelta(hours=26)), "No eligible scheduled post.")
        with transaction(self.path) as state:
            self.assertEqual(state["stories"][0]["status"], "review")

    @patch.dict(os.environ, {"FLASHWIRE_LIVE": ""})
    def test_live_requires_authorization(self):
        self.schedule()
        with self.assertRaisesRegex(ValueError, "requires"):
            publish_due(self.path, now=self.now, client=self.client, live=True)
        self.client.prepare.assert_not_called()

    @patch.dict(os.environ, {"FLASHWIRE_LIVE": "yes"})
    def test_persistence_and_correction(self):
        story_id = self.schedule()
        self.assertIn("media 20", publish_due(self.path, now=self.now, client=self.client, live=True))
        self.assertIn("No eligible", publish_due(self.path, now=self.now, client=self.client, live=True))
        self.client.publish.assert_called_once_with("10")
        with transaction(self.path) as state:
            parent = state["stories"][0]
            revision = new_revision(state, parent, "Correction", self.now)
            self.assertEqual(revision["parent"], story_id)
            self.assertEqual(revision["status"], "review")

    @patch.dict(os.environ, {"FLASHWIRE_LIVE": "yes"})
    def test_host_failure_and_uncertain_publish_block_retry(self):
        story_id = self.schedule()
        self.client.prepare.side_effect = PublishingError("JPEG unavailable")
        with self.assertRaisesRegex(PublishingError, "JPEG unavailable"):
            publish_due(self.path, now=self.now, client=self.client, live=True)
        self.client.publish.assert_not_called()
        self.schedule()
        self.client.prepare.side_effect = None
        self.client.publish.side_effect = PublishingError("No response")
        with self.assertRaises(PublishingError):
            publish_due(self.path, now=self.now, client=self.client, live=True)
        self.assertIn("No eligible", publish_due(self.path, now=self.now, client=self.client, live=True))
        with transaction(self.path) as state:
            self.assertEqual(state["stories"][0]["status"], "uncertain")
        reconcile(self.path, story_id, "20", self.now + timedelta(minutes=6))
        self.client.publish.assert_called_once()

    def test_instagram_contract(self):
        story_id = self.schedule()
        with transaction(self.path) as state:
            story = state["stories"][0]
        jpeg = create_jpeg(story)
        session = Mock()
        session.request.side_effect = [Mock(status_code=200, json=Mock(return_value=payload))
                                       for payload in ({"id": "40"}, {"status_code": "FINISHED"}, {"id": "50"})]
        graph = Instagram("123", "v27.0", "fixture-token", "https://images.example.org", session)
        with patch("flashwire.instagram.read_bytes", return_value=jpeg):
            self.assertEqual(graph.publish(graph.prepare(story, jpeg, "Caption")), "50")
        create, status, publish = session.request.call_args_list
        self.assertTrue(create.args[1].endswith("/123/media"))
        self.assertIn(story_id, create.kwargs["data"]["image_url"])
        self.assertEqual(status.kwargs["params"], {"fields": "status_code"})
        self.assertTrue(publish.args[1].endswith("/123/media_publish"))
        self.assertEqual(publish.kwargs["data"], {"creation_id": "40"})

    def test_feeds_fail_independently(self):
        rss = f'<rss version="2.0"><channel><title>Fixture</title><item><title>Local briefing</title><link>https://example.org/news</link><pubDate>{self.now:%a, %d %b %Y %H:%M:%S} GMT</pubDate></item></channel></rss>'
        settings = {"rss": [{"name": "One", "group": "one", "region": "India", "url": "https://example.org/feed"},
                            {"name": "Two", "group": "two", "region": "World", "url": "https://example.com/feed"}],
                    "gdelt": "science"}
        gdelt = ('{"articles":[{"url":"https://example.net/report","title":"Research update","seendate":"'
                 + self.now.strftime("%Y%m%dT%H%M%SZ") + '"}]}').encode()
        with patch("flashwire.news.read_bytes", side_effect=[rss.encode(), requests.Timeout(), gdelt]):
            articles, errors = ingest(settings, self.now)
        self.assertEqual(len(articles), 2)
        self.assertTrue(articles[-1].discovered)
        self.assertEqual(errors, ["Two: Timeout"])

    def test_preflight_is_read_only_and_rejects_wrong_profile_or_image(self):
        artwork = self.path.parent / "sample.jpg"
        artwork.write_bytes(b"fixture")
        graph = Instagram("123", "v27.0", "fixture-token", "https://images.example.org")
        responses = [{"id": "123", "username": "flashwire"}, {"data": [{"quota_usage": 0}]}]
        with patch.object(graph, "call", side_effect=responses) as call:
            with patch("flashwire.instagram.read_bytes", return_value=b"fixture") as get:
                self.assertIn("Verified Meta account @flashwire", graph.preflight("@flashwire", artwork))
            self.assertEqual([item.args[0] for item in call.call_args_list], ["GET", "GET"])
            self.assertEqual(get.call_args.args[-1], "https://images.example.org/sample.jpg")
        with patch.object(graph, "call", return_value=responses[0]):
            with self.assertRaisesRegex(PublishingError, "expected Instagram username"):
                graph.preflight("different", artwork)
        with patch.object(graph, "call", side_effect=responses):
            with patch("flashwire.instagram.read_bytes", return_value=b"different"):
                with self.assertRaisesRegex(PublishingError, "differs"):
                    graph.preflight("flashwire", artwork)

    def test_unified_uses_official_host_and_approved_artwork_upload(self):
        self.schedule()
        with transaction(self.path) as state:
            story = state["stories"][0]
        jpeg = create_jpeg(story)
        session, upload = Mock(), Mock()
        session.request.side_effect = [
            Mock(status_code=200, json=Mock(return_value=payload))
            for payload in ({"id": "123", "username": "flashwire"}, {"data": [{"quota_usage": 0}]},
                            {"id": "40"}, {"status_code": "FINISHED"}, {"id": "50"})
        ]
        graph = Instagram("123", "v27.0", "fixture-token", "https://example.pages.dev",
                          session, login="unified", username="flashwire", upload=upload)
        missing = requests.HTTPError(response=Mock(status_code=404))
        with patch("flashwire.instagram.read_bytes", side_effect=[missing, jpeg]):
            self.assertEqual(graph.publish(graph.prepare(story, jpeg, "Caption")), "50")
        upload.assert_called_once()
        self.assertEqual(upload.call_args.args[1], jpeg)
        self.assertTrue(all(call.args[1].startswith("https://graph.facebook.com/v27.0/")
                            for call in session.request.call_args_list))
        self.assertEqual(session.request.call_args_list[0].args[0], "GET")

    @patch.dict(os.environ, {"IG_ACCESS_TOKEN": "do-not-pass-to-wrangler"})
    def test_pages_upload_isolates_files_and_secrets(self):
        entrypoint = self.path.parent / "wrangler.js"
        entrypoint.touch()
        publisher = PagesUpload("https://flashwire.pages.dev", entrypoint, "a" * 32, "fixture")
        valid_name = "a" * 16 + "-" + "a" * 20 + ".jpg"

        def inspect(command, **settings):
            assets = Path(command[4])
            self.assertEqual([item.name for item in assets.iterdir()], [valid_name])
            self.assertEqual((assets / valid_name).read_bytes(), b"fixture bytes")
            self.assertEqual(command[-4:], ["--project-name", "flashwire", "--branch", "main"])
            self.assertNotIn("IG_ACCESS_TOKEN", settings["env"])

        with patch("flashwire.hosting.subprocess.run", side_effect=inspect) as runner:
            publisher(valid_name, b"fixture bytes")
        runner.assert_called_once()
        with self.assertRaises(HostingError):
            publisher("credential.json", b"fixture")

    def test_web_preview_and_csrf(self):
        story_id = self.schedule()
        browser = app_for(self.path).test_client()
        page = browser.get("/")
        self.assertIn(b"The city will add more bus routes", page.data)
        self.assertEqual(browser.post(f"/story/{story_id}", data={"action": "hold"}).status_code, 403)
        token = re.search(rb'name="csrf" value="([^"]+)"', page.data)[1].decode()
        self.assertEqual(browser.post(f"/story/{story_id}", data={"csrf": token, "action": "hold"}).status_code, 303)
        response = browser.get(f"/art/{story_id}.jpg?download=1")
        with Image.open(BytesIO(response.data)) as image:
            self.assertEqual((image.format, image.size), ("JPEG", (1080, 1350)))
        self.assertIn("attachment", response.headers["Content-Disposition"])

    def test_demo_cannot_publish(self):
        with transaction(self.path) as state:
            update_queue(state, demo(self.now), self.now)
            story = next(item for item in state["stories"] if len(item["sources"]) == 2)
            approve(story, *self.copy, self.now, self.now, confirmed=True)
        with self.assertRaisesRegex(ValueError, "non-demo"):
            publish_due(self.path, now=self.now)


if __name__ == "__main__":
    unittest.main()
