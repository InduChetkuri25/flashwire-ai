import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .news import similar, source_groups


@contextmanager
def transaction(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=20)
    try:
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS desk (id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT state FROM desk WHERE id = 1").fetchone()
            state = json.loads(row[0]) if row else {"stories": [], "last_run": None}
            yield state
            encoded = json.dumps(state, ensure_ascii=False)
            if row is None or encoded != row[0]:
                connection.execute("INSERT OR REPLACE INTO desk VALUES (1, ?)", (encoded,))
    finally:
        connection.close()


def find(state, story_id):
    return next((story for story in state["stories"] if story["id"] == story_id), None)


def new_revision(state, parent, kind, now):
    if parent["status"] != "published" or kind not in {"Update", "Correction"}:
        raise ValueError("Updates and corrections require a published parent.")
    story = {**parent, "id": uuid4().hex[:16], "parent": parent["id"], "type": kind,
             "headline": "", "caption": "", "status": "review", "due": None,
             "created": now.isoformat(), "media_id": None, "note": f"Explain what changed in this {kind.lower()}."}
    state["stories"].insert(0, story)
    return story


def edit_text(headline, caption):
    headline = " ".join(headline.split())
    caption = " ".join(caption.split())
    if not 12 <= len(headline) <= 92 or max((len(word) for word in headline.split()), default=0) > 24:
        raise ValueError("Use 12–92 characters in the headline and keep words short.")
    if not 30 <= len(caption) <= 400:
        raise ValueError("Write a caption of 30–400 characters.")
    if any(re.search(pattern, headline + " " + caption, re.I) for pattern in [
        r"https?://", r"<[^>]+>", r"\b(?:you won.t believe|shocking|100% confirmed|unconfirmed|allegedly|rumou?r)\b",
    ]):
        raise ValueError("Remove embedded links, markup, hype or unverified claims.")
    return headline, caption


def approve(story, headline, caption, due, now, confirmed):
    if story["status"] not in {"review", "approved"}:
        raise ValueError("This story cannot be edited in its current state.")
    headline, caption = edit_text(headline, caption)
    if not confirmed:
        raise ValueError("Confirm you checked the facts and editorial wording.")
    if len(source_groups(story)) < 2:
        raise ValueError("Two separately configured publisher groups are required.")
    if headline.endswith(" briefing") or caption.startswith("A ") and "coverage. Check the linked reporting" in caption:
        raise ValueError("Replace the placeholder with the specific facts you verified.")
    if any(similar(headline, item["title"]) or similar(caption, item["title"]) for item in story["sources"]):
        raise ValueError("Rewrite the text in your own words.")
    if not now - timedelta(minutes=5) <= due <= now + timedelta(hours=24):
        raise ValueError("Schedule within the next 24 hours, using UTC.")
    story.update(headline=headline, caption=caption, status="approved", due=due.isoformat(),
                 approved_at=now.isoformat(), note="Editorial review complete.")


def caption_for(story, parent=None):
    lead = f'{story["type"]} · ' if story["type"] != "Story" else ""
    sources = [item for item in story["sources"] if not item["discovered"]]
    ordered = list({item["group"]: item for item in reversed(sources)}.values())
    links = "\n".join(f'{item["source"]}: {item["url"]}' for item in ordered[:4])
    original = f'\nOriginal Instagram post ID: {parent["media_id"]}' if parent else ""
    caption = f'{lead}{story["caption"]}{original}\n\nSources\n{links}\n\nArtwork: FLASHWIRE AI (original graphic)'
    if len(caption) > 2100:
        raise ValueError("Source attribution exceeds the Instagram caption allowance.")
    return caption


def due_story(state, now, daily_limit):
    date = now.date().isoformat()
    sent = state.get("daily_attempts", {}).get(date, 0)
    if sent >= daily_limit or any(story["status"] in {"publishing", "uncertain"} for story in state["stories"]):
        return None
    candidates = []
    for story in state["stories"]:
        if story["status"] != "approved" or datetime.fromisoformat(story["due"]) > now:
            continue
        if now - datetime.fromisoformat(story["approved_at"]) > timedelta(hours=25):
            story.update(status="review", note="Approval expired. Check for newer reporting before rescheduling.")
            continue
        candidates.append(story)
    return min(candidates, key=lambda story: story["due"], default=None)


def db_path():
    return Path(os.environ.get("FLASHWIRE_DB", "data/desk.sqlite"))
