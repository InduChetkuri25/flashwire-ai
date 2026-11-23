import hmac
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit

from flask import Flask, Response, redirect, request, session

from .credentials import save_token
from .instagram import Instagram, PublishingError

LOCAL = "http://127.0.0.1:8767"
RETURN_SCRIPT = """
const params = new URLSearchParams(location.hash.slice(1));
history.replaceState(null, "", location.pathname);
if (params.has("code") && params.has("state")) {
    fetch("/meta/complete", {method: "POST", body: params, credentials: "same-origin"})
        .then(response => response.text()).then(result => { document.querySelector("p").textContent = result; })
        .catch(() => { document.querySelector("p").textContent = "Connection could not be verified."; });
}
"""


def oauth_app(app_id, config_id, version, callback, app_secret, account, username, image_base, token_file,
              artwork=None, client_factory=Instagram, session_clock=time.time):
    callback_url = urlsplit(callback)
    if (not re.fullmatch(r"\d+", app_id) or not re.fullmatch(r"\d+", config_id)
            or not re.fullmatch(r"v\d+\.\d+", version) or not app_secret
            or callback_url.scheme != "https" or not callback_url.hostname
            or callback_url.username or callback_url.password or callback_url.query or callback_url.fragment):
        raise ValueError("Set a valid Meta app ID, configuration ID, version, app secret and HTTPS callback.")
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_hex(32), TRUSTED_HOSTS=["127.0.0.1"],
                      MAX_CONTENT_LENGTH=8192, SESSION_COOKIE_SAMESITE="Lax")

    @app.after_request
    def private(response):
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                 "X-Content-Type-Options": "nosniff", "X-Robots-Tag": "noindex",
                                 "Content-Security-Policy":
                                     "default-src 'none'; script-src 'self'; connect-src 'self'; "
                                     "form-action 'self' https://www.facebook.com; frame-ancestors 'none'; base-uri 'none'"})
        return response

    @app.get("/")
    def home():
        return Response("<!doctype html><html lang=en><meta charset=utf-8><title>Connect FLASHWIRE AI</title>"
                        "<h1>Connect FLASHWIRE AI to Meta</h1><p>This verifies access without posting.</p>"
                        "<form method=post action=/meta/start><button>Continue to Meta</button></form>", mimetype="text/html")

    @app.post("/meta/start")
    def start():
        if request.headers.get("Origin") != LOCAL:
            return "Start from the local FLASHWIRE connection page.", 403
        state = secrets.token_urlsafe(32)
        session.update(state=state, started=int(session_clock()))
        options = urlencode({"client_id": app_id, "config_id": config_id, "redirect_uri": callback,
                             "display": "popup", "override_default_response_type": "true",
                             "response_type": "code", "state": state, "prompt": "login"})
        return redirect(f"https://www.facebook.com/dialog/oauth?{options}", code=303)

    @app.get("/meta/callback")
    def callback_page():
        return Response("<!doctype html><html lang=en><meta charset=utf-8><title>FLASHWIRE AI setup</title>"
                        "<h1>Instagram connection</h1><p>Waiting for Meta authorization.</p>"
                        "<script src=/meta/return.js defer></script>", mimetype="text/html")

    @app.get("/meta/return.js")
    def return_script():
        return Response(RETURN_SCRIPT, mimetype="application/javascript")

    @app.post("/meta/complete")
    def complete():
        if request.headers.get("Origin") != LOCAL:
            return "Invalid connection origin.", 403
        expected = session.pop("state", "")
        issued = session.pop("started", 0)
        state, code = request.form.get("state", ""), request.form.get("code", "")
        if (not re.fullmatch(r"[a-zA-Z0-9_-]{43}", state) or not hmac.compare_digest(state, expected)
                or not 0 <= session_clock() - issued <= 600 or not 1 <= len(code) <= 4096):
            return "This connection has expired or is invalid. Start again from FLASHWIRE AI.", 400
        try:
            token = Instagram.exchange_code(version, app_id, app_secret, callback, code)
            client = client_factory(account, version, token, image_base, login="unified")
            message = client.preflight(username, artwork)
            save_token(token_file, token)
        except (OSError, PublishingError, ValueError):
            return "Connection verification failed. Check the app permissions, selected account and Meta review status.", 502
        return f"{message} The verified credential is saved for this Windows user.", 200

    return app
