# FLASHWIRE AI

A private editorial desk for an India and world news Instagram page. Collect RSS and GDELT coverage, check related reporting, edit a short original post, and schedule a branded image through Instagram's official publishing API.

## Run the desk

Use Python 3.12. From the project directory, run:

```powershell
python -m pip install -r requirements.txt
python -m flashwire scan --demo
python -m flashwire serve --demo
```

Open [the editorial desk](http://127.0.0.1:8765). Demo articles are fictional and the publishing command rejects them. For real sources, run `python -m flashwire scan` and `python -m flashwire serve` in a separate terminal. The desk listens only on the local computer. It uses the SQLite database at `data/desk.sqlite`, or the path in `FLASHWIRE_DB`. Use the same database for scans, edits, artwork exports and publishing.

## Editorial workflow

1. Open the source links and check the report itself, the date and the origin of the information. Two publisher groups are required for approval. Shared wire copy or matching titles do not independently verify a claim. GDELT is discovery only unless the same link later appears in a configured RSS feed.
2. Replace the placeholder with a short factual headline and caption in your own words. If a claim is disputed or unclear, keep it in review. The automatic self-edit normalizes spacing and checks length, links, hype, overlapping wording and attribution. Fact verification and final factual writing are editorial tasks. The pipeline does not use a paid or remote language model.
3. Attest to the checks, set the publishing time in UTC and approve. The artwork is generated from your headline. Every image uses original Pillow-drawn graphics, and the system ignores publisher images and GDELT thumbnails. The Instagram caption includes named source URLs and an artwork credit.
4. Run `python -m flashwire publish` for a credential-free dry run. This checks the next due draft without sending a network request. Live publishing checks the exact public JPEG before proceeding.
5. Open a published story to queue an update or correction. Each one goes through review and links back to the original record in the desk. Its Instagram caption identifies the original media ID.

Feed settings are in `feeds.json`. The scan takes up to 20 recent articles per RSS feed and 25 GDELT discoveries. It creates up to 12 drafts per scan, removes URL tracking parameters, and clusters nearby coverage using headline token overlap. This can split paraphrases or group related-but-different reports. Attach the URL of another collected RSS article in the desk when coverage belongs together.

Reference: [GDELT DOC API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/).

## GitHub Actions

The private repository runs tests for pushes to `main` and pull requests. **News inbox** scans four times a day at 05:47, 11:47, 17:47 and 23:47 India time, subject to GitHub scheduling delays. It saves an isolated discovery snapshot to the private `flashwire-inbox` branch. The workflow never receives an Instagram token. Each run is capped at five minutes, or up to 620 scheduled runner minutes in a 31-day month, excluding manual runs and CI. Keep spending disabled for Actions if you need a hard zero-cost ceiling. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) · [Schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

To import the cloud inbox into the local desk without replacing editorial decisions, download `inbox.sqlite` from the private `flashwire-inbox` branch and run `python -m flashwire import-inbox /path/to/inbox.sqlite`. Alternatively run a local scan directly. Keep the repository private because the branch contains pre-publication queue data.

## Enable official Instagram publishing

New Meta apps may offer **Unified Login**. Set `IG_LOGIN_MODE=unified` for that flow. Configure it on a Meta app owned by the business portfolio you choose, and invite the professional account as an Instagram Tester for the development check. Accept the invitation from Instagram and generate the token in Meta. For production, follow Meta's portfolio and app requirements and use a Business Integration System User access token with the Instagram account assigned. Select only the assets and permissions needed for the chosen configuration. The publisher uses `instagram_basic` and `instagram_content_publish` with Unified Login. Meta may require additional scopes for its login configuration. [Meta Unified Login setup](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/get-started)

For this single-operator Windows setup, deploy the files from `flashwire/oauth_public` on the dedicated artwork site and register its HTTPS `/auth/callback` in Meta. Run `python -m flashwire connect-meta --app-id APP_ID --config-id CONFIG_ID --callback HTTPS_CALLBACK --token-file data/meta-credential.dpapi`. The prompt accepts the Meta **app secret** locally. Open `http://127.0.0.1:8767` on the same computer, select the intended Instagram account and complete Meta's consent. The public page returns the authorization code to the local setup window. The app secret and resulting access token stay on the computer. The runner exchanges and verifies the credential without publishing, then encrypts it using Windows DPAPI. Close the connection window after success. Set `FLASHWIRE_TOKEN_FILE=data/meta-credential.dpapi` in the live runner and run it under the same Windows user. Renew before the configuration's 60-day expiry. For other platforms, inject the token from the platform's secret store.

1. Use an Instagram Business or Creator account and configure **Instagram API with Instagram Login** in your Meta app. Authorize `instagram_business_basic` and `instagram_business_content_publish`. Give the account the required role in development or request the relevant access in Meta if the account requires it. Obtain the professional account ID and an Instagram user access token. Choose the API version supported by your app. [Meta content publishing](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing/)
2. Choose a public HTTPS location that serves the original JPEG unchanged and without a login or expiring URL. Keep the desk and its database private. Use **Download JPEG** after approval, or run `python -m flashwire export-artwork path/to/staging-folder` to export all approved images. Upload those exact files to your host. The image filename includes a hash and changes when the artwork changes.
3. Store the token in your runner's secret store and inject it as `IG_ACCESS_TOKEN`. Set `IG_ACCOUNT_ID` to the professional account ID, `IG_USERNAME` to the expected handle, `IG_API_VERSION`, `IMAGE_BASE_URL` and, only once live posts are authorized, `FLASHWIRE_LIVE=yes`. Use `IG_LOGIN_MODE=instagram` for Instagram Login. Never paste the token into chat or commit it. Renew it before expiration.
4. Before enabling live mode, run `python -m flashwire preflight --username YOUR_HANDLE --artwork path/to/uploaded.jpg`. This checks the account ID, expected username, publishing quota access and exact bytes of an already-hosted image. Omit `--artwork` to test Meta independently. Add `--prompt-token` for a one-time test with hidden input in your terminal. The check does not send a post.
5. Run `python -m flashwire publish --live` for an approved and due story, or run that command every 15 minutes from your own scheduler on the machine holding the desk database. Use one persistent database. A run sends at most one post and the desk records at most two live attempts per UTC day. Late approvals expire after 25 hours.

When Meta can't confirm the final publish request, the desk pauses publishing to avoid duplicate posts. Check the account and use `python -m flashwire reconcile STORY_ID MEDIA_ID` to record the observed media ID. If you confirm the post is absent, use `absent` for the media ID, then review and reapprove it. A JPEG or container preparation failure returns the item to review.

### Optional automatic artwork upload

Use a dedicated Cloudflare Pages Direct Upload project with production branch `main`. First deploy a sample JPEG and check that the public project URL serves it. Set `IMAGE_BASE_URL=https://PROJECT.pages.dev`, and supply `CLOUDFLARE_ACCOUNT_ID` and a secret `CLOUDFLARE_API_TOKEN` with **Cloudflare Pages: Edit** for that account. Install the official Wrangler package, set `FLASHWIRE_WRANGLER_JS` to its `bin/wrangler.js` entry point, and enable `FLASHWIRE_PAGES_UPLOAD=yes`. Each deployment replaces the site's current files with the approved JPEG and the public OAuth callback files. The publishing job checks the JPEG bytes on the public URL before creating the Instagram container. [Cloudflare Pages Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/)

## Verify locally

```text
python -m unittest discover -s tests -v
```

Tests use simulated sources and Meta responses. They cover duplicate handling, feed failures, approval rules, scheduled time, dry runs, official API request shapes, artwork, queue persistence, corrections and uncertain publish recovery.

### Standalone Windows installation

The local installation runs under Windows Task Scheduler as **FLASHWIRE News Desk** every 30 minutes. The entry point is `flashwire/local_runner.py cycle`. It uses the installed local Ollama model `qwen2.5:3b` for drafting and checking fresh corroborated reports, Chrome for optional Gemini illustrations, and Meta for publishing. Install the worker dependencies from `requirements-worker.txt`. The local runner contains the non-secret account and artwork host settings for this installation.

Open **Open FLASHWIRE Gemini.cmd**, sign into Gemini once, then close that Chrome window to release its profile for scheduled runs. The browser profile, protected Meta credential, local database and log stay on this PC. Runs fall back to a white text card on image-generation errors. The PC must be awake, signed in and online. Check `work/flashwire-state/worker.log` alongside the project output for scan and publish results. An uncertain publishing response pauses further posts until reconciled.
### Persistent cloud worker

For a cloud deployment that keeps its own Gemini browser login, use a persistent Linux desktop VM. The worker runs under the same unprivileged account used for the browser. Its disk holds the SQLite publish journal, Gemini profile and artwork. Windows can be switched off after cutover.

1. Clone the repo at ~/flashwire-ai. Create .venv there and install requirements-worker.txt. Install Chrome, GitHub CLI and Ollama on the VM. Run Ollama on loopback with qwen2.5:3b installed. Sign gh into an account with write access to the artwork repository.
2. In the VM desktop launch Chrome with --user-data-dir="$HOME/.local/share/flashwire/gemini-profile", sign in at https://gemini.google.com/app and close the window.
3. Create ~/.config/flashwire/worker.env with permissions 0600. Set IG_LOGIN_MODE=unified, IG_API_VERSION=v27.0, IG_USERNAME=gk._insta, IG_ACCOUNT_ID=17841449961192703, FLASHWIRE_GITHUB_UPLOAD=yes, FLASHWIRE_LIVE=yes and IMAGE_BASE_URL=https://raw.githubusercontent.com/InduChetkuri25/flashwire-ai/main/artwork. Set IG_ACCESS_TOKEN securely on the VM. Never commit this file.
4. Stop the Windows task after its active run finishes, and transfer its desk.sqlite to ~/.local/share/flashwire/desk.sqlite over SSH. If the journal contains an uncertain post, reconcile it before enabling publishing.
5. From the clone, load the environment file into the shell with export enabled and run .venv/bin/python -m flashwire.cloud_worker --check. Install both deploy/flashwire units under ~/.config/systemd/user/, reload the user manager, enable lingering for the service account, and enable --now flashwire.timer with systemctl --user. Inspect journalctl --user -u flashwire.service after a run. Keep only one live publisher.

For an Oracle Always Free Arm installation, select the Always Free eligible A1.Flex shape in the home region, within the current tenancy allowances. One suggested configuration is 2 OCPUs, 12 GB RAM and a 50 GB boot disk. Use an Arm64 Ubuntu image supported by Playwright. Install the matching Chromium build with .venv/bin/playwright install --with-deps chromium and set FLASHWIRE_BROWSER_CHANNEL=chromium in worker.env. For interactive Gemini sign-in, launch the installed Chromium executable from the same VM desktop and use the worker profile directory specified above. Confirm image generation there before cutover. Free capacity and continuous uptime depend on the provider.

### Active hosted configuration

The public repository workflow in .github/workflows/news.yml checks twice an hour on a standard GitHub runner. It uses original white headline cards and loads Qwen on the runner only for corroborated candidates. The flashwire-inbox branch holds public feed metadata and the publish journal. FLASHWIRE_META is an encrypted Actions secret. Setting FLASHWIRE_CLOUD_LIVE to yes enables the Meta account check and live publishing. The journal is pushed before the final publish request so an interrupted run cannot silently repeat a post.
