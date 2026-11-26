import hashlib
import os
import re
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import requests

from .art import create_jpeg
from .credentials import read_token
from .desk import caption_for, due_story, edit_text, find, transaction
from .hosting import GitHubArtworkUpload, HostingError, PagesUpload
from .news import read_bytes, source_groups


class PublishingError(RuntimeError):
    pass


class ArtworkUnavailable(PublishingError):
    pass


def filename(story, jpeg=None):
    digest = hashlib.sha256(jpeg if jpeg is not None else create_jpeg(story)).hexdigest()
    return f'{story["id"]}-{digest[:20]}.jpg'


def normalize_username(username):
    expected = username.lstrip("@").casefold()
    if not re.fullmatch(r"[a-z0-9._]{1,30}", expected):
        raise ValueError("Enter the expected Instagram username.")
    return expected


class Instagram:
    def __init__(self, account, version, token, image_base, session=None, *,
                 login="instagram", username=None, upload=None):
        if not (re.fullmatch(r"\d+", account) and re.fullmatch(r"v\d+\.\d+", version) and token):
            raise ValueError("Set IG_ACCOUNT_ID, IG_API_VERSION and IG_ACCESS_TOKEN.")
        url = urlsplit(image_base)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Set IMAGE_BASE_URL to the public HTTPS directory containing your artwork.")
        hosts = {"instagram": "graph.instagram.com", "unified": "graph.facebook.com"}
        if login not in hosts:
            raise ValueError("Set IG_LOGIN_MODE to instagram or unified.")
        self.account = account
        self.endpoint = f"https://{hosts[login]}/{version}"
        self.token = token
        self.image_base = image_base.rstrip("/")
        self.session = session or requests.Session()
        self.username = normalize_username(username) if username else None
        self.upload = upload

    @classmethod
    def from_env(cls, live=False, token=None):
        image_base = os.getenv("IMAGE_BASE_URL", "")
        username = os.getenv("IG_USERNAME", "")
        if live and not username:
            raise ValueError("Set IG_USERNAME to the intended Instagram account before publishing.")
        credential = token if token is not None else os.getenv("IG_ACCESS_TOKEN", "")
        if not credential and os.getenv("FLASHWIRE_TOKEN_FILE"):
            credential = read_token(os.environ["FLASHWIRE_TOKEN_FILE"])
        client = cls(os.getenv("IG_ACCOUNT_ID", ""), os.getenv("IG_API_VERSION", ""),
                     credential, image_base,
                     login=os.getenv("IG_LOGIN_MODE", "instagram"), username=username)
        if live and os.getenv("FLASHWIRE_PAGES_UPLOAD") == "yes":
            client.upload = PagesUpload.from_env(image_base)
        if live and os.getenv("FLASHWIRE_GITHUB_UPLOAD") == "yes":
            if client.upload:
                raise ValueError("Select just one automatic artwork host.")
            client.upload = GitHubArtworkUpload(image_base, os.getenv("FLASHWIRE_GH_EXE"))
        return client

    @staticmethod
    def exchange_code(version, app_id, app_secret, callback, code):
        try:
            response = requests.get(f"https://graph.facebook.com/{version}/oauth/access_token",
                                    params={"client_id": app_id, "client_secret": app_secret,
                                            "redirect_uri": callback, "code": code},
                                    timeout=(5, 15), allow_redirects=False)
            if response.status_code != 200:
                raise PublishingError("Meta did not authorize the connection.")
            token = response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise PublishingError("Meta did not return a usable credential.")
            return token
        except (requests.RequestException, ValueError, AttributeError):
            raise PublishingError("Could not confirm the Meta sign-in.") from None

    def call(self, method, path, **values):
        try:
            payload = {"params" if method == "GET" else "data": values}
            response = self.session.request(method, f"{self.endpoint}/{path}", timeout=(5, 15),
                                            allow_redirects=False,
                                            headers={"Authorization": f"Bearer {self.token}"}, **payload)
            result = response.json()
            if not isinstance(result, dict):
                raise PublishingError("Meta returned an unexpected response.")
            if not 200 <= response.status_code < 300 or "error" in result:
                code = result.get("error", {}).get("code", response.status_code)
                if not isinstance(code, int):
                    code = response.status_code
                raise PublishingError(f"Meta rejected request (code {code}).")
            return result
        except (requests.RequestException, ValueError, AttributeError, TypeError):
            raise PublishingError("Could not confirm the response from Meta.") from None

    def check_artwork(self, name, jpeg):
        if not re.fullmatch(r"[a-zA-Z0-9_-]+\.jpe?g", name):
            raise ValueError("Use a JPEG filename containing letters, numbers, dashes or underscores.")
        url = f"{self.image_base}/{name}"
        try:
            if read_bytes(self.session, url) != jpeg:
                raise PublishingError("Hosted JPEG differs from the approved artwork.")
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 404:
                raise ArtworkUnavailable("The approved JPEG has not been uploaded.") from None
            raise PublishingError("The image host returned an error.") from None
        except (requests.RequestException, ValueError):
            raise PublishingError("The approved JPEG is unavailable at the configured public URL.") from None
        return url

    def verify_account(self, username):
        expected = normalize_username(username)
        account = self.call("GET", self.account, fields="id,username")
        actual = account.get("username")
        if str(account.get("id")) != self.account or not isinstance(actual, str) or actual.casefold() != expected:
            raise PublishingError("The token and account ID do not resolve to the expected Instagram username.")
        quota = self.call("GET", f"{self.account}/content_publishing_limit", fields="quota_usage")
        if not isinstance(quota.get("data"), list) or not quota["data"]:
            raise PublishingError("Meta did not report the account's publishing quota.")
        return actual

    def preflight(self, username, artwork=None):
        actual = self.verify_account(username)
        if artwork is None:
            return f"Verified Meta account @{actual} and publishing quota access. No post was sent."
        self.check_artwork(artwork.name, artwork.read_bytes())
        return f"Verified Meta account @{actual}, publishing quota access and the public JPEG. No post was sent."

    def prepare(self, story, jpeg, caption):
        if self.username:
            self.verify_account(self.username)
        name = filename(story, jpeg)
        try:
            url = self.check_artwork(name, jpeg)
        except ArtworkUnavailable:
            if not self.upload:
                raise
            try:
                self.upload(name, jpeg)
            except HostingError as error:
                raise PublishingError(str(error)) from None
            for attempt in range(8):
                if attempt:
                    time.sleep(4)
                try:
                    url = self.check_artwork(name, jpeg)
                    break
                except ArtworkUnavailable:
                    if attempt == 7:
                        raise
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
        client = client or Instagram.from_env(live=True)
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
