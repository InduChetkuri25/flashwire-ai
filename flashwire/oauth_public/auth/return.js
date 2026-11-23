"use strict";

const parameters = new URLSearchParams(location.search);
const state = parameters.get("state");
const code = parameters.get("code");
history.replaceState(null, "", location.pathname);
if (state && /^[a-zA-Z0-9_-]{43}$/.test(state) && code && code.length <= 4096) {
    location.replace("http://127.0.0.1:8767/meta/callback#" + new URLSearchParams({state, code}));
} else if (parameters.has("error")) {
    document.getElementById("status").textContent = "Meta did not authorize this connection. Return to FLASHWIRE AI and try again.";
}
