import hashlib
import os
import re
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import requests

from .art import create_jpeg
from .desk import caption_for, due_story, edit_text, find, transaction
from .news import read_bytes, source_groups


class PublishingError(RuntimeError):
    pass


def filename(story, jpeg=None):
    digest = hashlib.sha256(jpeg if jpeg is not None else create_jpeg(story)).hexdigest()
    return f'{story["id"]}-{digest[:20]}.jpg'


class Instagram:
    def __init__(self, account, version, token, image_base, session=None):
        if not (re.fullmatch(r"\d+", account) and re.fullmatch(r"v\d+\.\d+", version) and token):
            raise ValueError("Set IG_ACCOUNT_ID, IG_API_VERSION and IG_ACCESS_TOKEN.")
        url = urlsplit(image_base)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Set IMAGE_BASE_URL to the public HTTPS directory containing your artwork.")
        self.account = account
        self.endpoint = f"https://graph.instagram.com/{version}"
        self.token = token
        self.image_base = image_base.rstrip("/")
        self.session = session or requests.Session()

    @classmethod
    def from_env(cls):
        return cls(os.getenv("IG_ACCOUNT_ID", ""), os.getenv("IG_API_VERSION", ""),
                   os.getenv("IG_ACCESS_TOKEN", ""), os.getenv("IMAGE_BASE_URL", ""))

    def call(self, method, path, **values):
        try:
            payload = {"params" if method == "GET" else "data": values}
            response = self.session.request(method, f"{self.endpoint}/{path}", timeout=(5, 15),
                                            allow_redirects=False,
                                            headers={"Authorization": f"Bearer {self.token}"}, **payload)
            result = response.json()
            if not 200 <= response.status_code < 300 or "error" in result:
                code = result.get("error", {}).get("code", response.status_code)
                raise PublishingError(f"Meta rejected request (code {code}).")
            return result
        except (requests.RequestException, ValueError, AttributeError, TypeError):
            raise PublishingError("Could not confirm the response from Meta.") from None

    def prepare(self, story, jpeg, caption):
        url = f"{self.image_base}/{filename(story, jpeg)}"
        try:
            if read_bytes(self.session, url) != jpeg:
                raise PublishingError("Hosted JPEG differs from the approved artwork.")
        except (requests.RequestException, ValueError):
            raise PublishingError("The approved JPEG is unavailable at the configured public URL.") from None
        container = self.call("POST", f"{self.account}/media", image_url=url, caption=caption,
                              alt_text=story["headline"]).get("id", "")
        if not re.fullmatch(r"\d+", str(container)):
            raise PublishingError("Meta did not return a valid container ID.")
        for attempt in range(5):
            if attempt:
                time.sleep(5)
            status = self.call("GET", str(container), fields="status_code").get("status_code")
            if status == "FINISHED":
                return str(container)
            if status != "IN_PROGRESS":
                break
        raise PublishingError("Meta did not report that the container was ready.")

    def publish(self, container):
        media = self.call("POST", f"{self.account}/media_publish", creation_id=container).get("id", "")
        if not re.fullmatch(r"\d+", str(media)):
            raise PublishingError("No published media ID was returned.")
        return str(media)


def publish_due(path, now=None, client=None, live=False):
    now = now or datetime.now(UTC)
    if live:
        if os.getenv("FLASHWIRE_LIVE") != "yes":
            raise ValueError("Live publishing requires FLASHWIRE_LIVE=yes and the --live flag.")
        client = client or Instagram.from_env()
    with transaction(path) as state:
        story = due_story(state, now, daily_limit=2)
        if not story:
            return "No eligible scheduled post."
        edit_text(story["headline"], story["caption"])
        if len(source_groups(story)) < 2 or any(src["group"].startswith("demo-") for src in story["sources"]):
            raise ValueError("Publishing requires verified non-demo publisher groups.")
        caption = caption_for(story, find(state, story["parent"]) if story["parent"] else None)
        jpeg = create_jpeg(story)
        if not live:
            return f'Dry run ready: {story["id"]} / {filename(story, jpeg)}'
        date = now.date().isoformat()
        state["daily_attempts"] = {date: state.get("daily_attempts", {}).get(date, 0) + 1}
        story.update(status="publishing", attempted_at=now.isoformat(), note="Publish attempt recorded.")
    try:
        container = client.prepare(story, jpeg, caption)
    except PublishingError as error:
        with transaction(path) as state:
            find(state, story["id"]).update(status="review", note=str(error))
        raise
    with transaction(path) as state:
        find(state, story["id"]).update(container_id=container)
    try:
        media = client.publish(container)
    except PublishingError as error:
        with transaction(path) as state:
            find(state, story["id"]).update(status="uncertain", note="Check Instagram before retrying.")
        raise error
    with transaction(path) as state:
        find(state, story["id"]).update(status="published", media_id=media, note="Published to Instagram.")
    return f"Published Instagram media {media}."


def reconcile(path, story_id, media, now=None):
    now = now or datetime.now(UTC)
    with transaction(path) as state:
        story = find(state, story_id)
        if not story or story["status"] not in {"publishing", "uncertain"}:
            raise ValueError("This story has no unresolved publish attempt.")
        if now - datetime.fromisoformat(story["attempted_at"]) < timedelta(minutes=5):
            raise ValueError("Wait five minutes for the original request to finish.")
        if media != "absent" and not re.fullmatch(r"\d+", media):
            raise ValueError("Supply the observed Instagram media ID or use absent after checking Instagram.")
        story.update(status="review" if media == "absent" else "published",
                     media_id=None if media == "absent" else media, note="Manually reconciled with Instagram.")
