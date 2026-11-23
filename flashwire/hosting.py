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
