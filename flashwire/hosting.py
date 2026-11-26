import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit


class HostingError(RuntimeError):
    pass


CALLBACK_ASSETS = Path(__file__).with_name("oauth_public")


class PagesUpload:
    def __init__(self, image_base, entrypoint, account, token):
        url = urlsplit(image_base)
        match = re.fullmatch(r"([a-z0-9]+(?:-[a-z0-9]+)*)\.pages\.dev", url.netloc)
        if not match or url.scheme != "https" or url.path not in ("", "/"):
            raise ValueError("Automatic upload needs a dedicated https://PROJECT.pages.dev host.")
        self.project = match[1]
        self.entrypoint = Path(entrypoint).resolve()
        if not self.entrypoint.is_file() or self.entrypoint.suffix != ".js":
            raise ValueError("Set FLASHWIRE_WRANGLER_JS to the installed Wrangler JavaScript entry point.")
        if not re.fullmatch(r"[0-9a-f]{32}", account) or not token:
            raise ValueError("Set CLOUDFLARE_ACCOUNT_ID and a scoped CLOUDFLARE_API_TOKEN for Pages.")
        allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
                   "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
        self.env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        self.env.update(CLOUDFLARE_ACCOUNT_ID=account, CLOUDFLARE_API_TOKEN=token,
                        WRANGLER_SEND_METRICS="false", CI="true")

    @classmethod
    def from_env(cls, image_base):
        return cls(image_base, os.getenv("FLASHWIRE_WRANGLER_JS", ""),
                   os.getenv("CLOUDFLARE_ACCOUNT_ID", ""), os.getenv("CLOUDFLARE_API_TOKEN", ""))

    def __call__(self, name, jpeg):
        if not re.fullmatch(r"[0-9a-f]{16}-[0-9a-f]{20}\.jpg", name):
            raise HostingError("Only generated story artwork can be deployed automatically.")
        with TemporaryDirectory(prefix="flashwire-pages-") as folder:
            root = Path(folder)
            assets = root / "artwork"
            shutil.copytree(CALLBACK_ASSETS, assets)
            (assets / name).write_bytes(jpeg)
            try:
                subprocess.run(["node", str(self.entrypoint), "pages", "deploy", str(assets),
                                "--project-name", self.project, "--branch", "main"],
                               cwd=root, env=self.env, timeout=90, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                raise HostingError("Cloudflare Pages did not complete the artwork deployment.") from None


class GitHubArtworkUpload:
    def __init__(self, image_base, executable):
        url = urlsplit(image_base)
        match = re.fullmatch(r"/([\w.-]+/[\w.-]+)/main/artwork/?", url.path, re.ASCII)
        if (url.scheme != "https" or url.netloc != "raw.githubusercontent.com"
                or url.query or url.fragment or not match):
            raise ValueError("Use https://raw.githubusercontent.com/OWNER/REPO/main/artwork for GitHub uploads.")
        self.repository = match[1]
        self.executable = executable or "gh"

    def __call__(self, name, jpeg):
        if not re.fullmatch(r"[0-9a-f]{16}-[0-9a-f]{20}\.jpg", name):
            raise HostingError("Only generated story JPEGs can be uploaded.")
        payload = json.dumps({"message": f"Host approved artwork {name}", "branch": "main",
                              "content": base64.b64encode(jpeg).decode("ascii")})
        public_endpoint = f"repos/{self.repository}"
        artwork_endpoint = f"{public_endpoint}/contents/artwork/{name}"
        allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
                   "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "GH_CONFIG_DIR", "GH_TOKEN"}
        environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        environment.update(GH_PROMPT_DISABLED="1", GH_HOST="github.com")
        try:
            check = subprocess.run([self.executable, "api", public_endpoint, "--jq", ".visibility"],
                                   env=environment, capture_output=True, text=True, timeout=20, check=True)
            if check.stdout.strip() != "public":
                raise HostingError("The GitHub artwork repository must already be public.")
            subprocess.run([self.executable, "api", "--method", "PUT", artwork_endpoint, "--input", "-"],
                           env=environment, input=payload, text=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=35, check=True)
        except (OSError, subprocess.SubprocessError):
            raise HostingError("GitHub could not upload the approved artwork.") from None
