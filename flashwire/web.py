import secrets
from datetime import UTC, datetime
from io import BytesIO

from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for

from .art import create_jpeg
from .desk import approve, find, new_revision, transaction
from .instagram import filename
from .news import canonical, source_groups


def app_for(path, sample=False):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_hex(32), MAX_CONTENT_LENGTH=16_384,
                      SESSION_COOKIE_SAMESITE="Strict", TRUSTED_HOSTS=["127.0.0.1", "localhost"])

    @app.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.get("/")
    def index():
        token = session.setdefault("csrf", secrets.token_hex(24))
        with transaction(path) as state:
            stories = state["stories"]
            selected = find(state, request.args.get("story")) or next(iter(stories), None)
            current = request.args.get("status", "all")
            visible = [story for story in stories if current == "all" or story["status"] == current]
            if selected not in visible:
                selected = next(iter(visible), None)
            counts = {status: sum(story["status"] == status for story in stories)
                      for status in ("review", "approved", "published", "uncertain")}
            return render_template("desk.html", selected=selected, stories=visible[:100], total=len(stories),
                                   counts=counts, groups=source_groups(selected) if selected else set(),
                                   last=state["last_run"], sample=sample, token=token, current=current,
                                   now=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M"))

    @app.get("/art/<story_id>.jpg")
    def art(story_id):
        with transaction(path) as state:
            story = find(state, story_id)
        if not story:
            abort(404)
        jpeg = create_jpeg(story)
        return send_file(BytesIO(jpeg), mimetype="image/jpeg", download_name=filename(story, jpeg),
                         as_attachment=request.args.get("download") == "1")

    @app.post("/story/<story_id>")
    def change(story_id):
        if not session.get("csrf") or not secrets.compare_digest(session["csrf"], request.form.get("csrf", "")):
            abort(403)
        now = datetime.now(UTC)
        action = request.form.get("action")
        try:
            with transaction(path) as state:
                story = find(state, story_id)
                if not story:
                    abort(404)
                if action == "approve":
                    due = datetime.strptime(request.form.get("due", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)
                    approve(story, request.form.get("headline", ""), request.form.get("caption", ""),
                            due, now, request.form.get("confirmed") == "yes")
                elif action == "hold" and story["status"] == "approved":
                    story.update(status="review", due=None, note="Schedule paused by editor.")
                elif action in {"Correction", "Update"}:
                    story_id = new_revision(state, story, action, now)["id"]
                elif action == "evidence" and story["status"] == "review":
                    url = canonical(request.form.get("source_url", ""))
                    evidence = next((item for entry in state["stories"] for item in entry["sources"]
                                     if item["url"] == url and not item["discovered"]), None)
                    if not evidence or any(item["url"] == url for item in story["sources"]) or len(story["sources"]) >= 12:
                        raise ValueError("Choose a new source URL already collected by a configured RSS feed.")
                    story["sources"].append(evidence)
                else:
                    raise ValueError("That action is unavailable for this story.")
            flash("Editorial queue updated.", "ok")
        except ValueError as error:
            flash(str(error), "error")
        return redirect(url_for("index", story=story_id), code=303)

    return app
