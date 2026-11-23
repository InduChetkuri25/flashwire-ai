import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from getpass import getpass
from pathlib import Path

from .desk import db_path, transaction
from .instagram import Instagram, publish_due, reconcile
from .news import Article, demo, ingest, update_queue

ROOT = Path(__file__).resolve().parent.parent


def scan(path, sample=False):
    now = datetime.now(UTC)
    articles, failures = (demo(now), []) if sample else ingest(json.loads((ROOT / "feeds.json").read_text()), now)
    with transaction(path) as state:
        added = update_queue(state, articles, now)
        state["last_run"] = {"at": now.isoformat(), "received": len(articles), "added": added,
                             "failures": failures, "sample": sample}
        return state["last_run"]


def main():
    parser = argparse.ArgumentParser(prog="python -m flashwire")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_command = commands.add_parser("scan")
    ingest_command.add_argument("--demo", action="store_true")
    snapshot = commands.add_parser("import-inbox")
    snapshot.add_argument("snapshot", type=Path)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--demo", action="store_true")
    publish = commands.add_parser("publish")
    publish.add_argument("--live", action="store_true")
    check = commands.add_parser("preflight")
    check.add_argument("--username", required=True)
    check.add_argument("--artwork", type=Path)
    check.add_argument("--prompt-token", action="store_true")
    export = commands.add_parser("export-artwork")
    export.add_argument("directory", type=Path)
    repair = commands.add_parser("reconcile")
    repair.add_argument("story_id")
    repair.add_argument("media_id")
    args = parser.parse_args()
    path = db_path()
    if getattr(args, "demo", False):
        path = path.parent / "demo.sqlite"
    try:
        if args.command == "scan":
            report = scan(path, args.demo)
            print(json.dumps(report))
            return int(not report["received"] and bool(report["failures"]))
        if args.command == "import-inbox":
            if not args.snapshot.is_file() or args.snapshot.resolve() == path.resolve():
                raise ValueError("Provide a separate, existing inbox snapshot.")
            with transaction(args.snapshot) as snapshot_state:
                now = datetime.now(UTC)
                articles = [Article(**source) for story in snapshot_state["stories"] for source in story["sources"]
                            if datetime.fromisoformat(source["seen_at"]) >= now - timedelta(hours=48)]
                last_run = snapshot_state["last_run"]
            with transaction(path) as state:
                added = update_queue(state, articles, now)
                if last_run and (not state["last_run"] or last_run["at"] > state["last_run"]["at"]):
                    state["last_run"] = last_run
            print(f"Imported {added} new drafts.")
        if args.command == "serve":
            from waitress import serve as serve_http
            from .web import app_for

            print(f"FLASHWIRE desk at http://127.0.0.1:{args.port}", flush=True)
            serve_http(app_for(path, args.demo), host="127.0.0.1", port=args.port)
        if args.command == "publish":
            print(publish_due(path, live=args.live))
        if args.command == "preflight":
            if args.artwork is not None and not args.artwork.is_file():
                raise ValueError("Choose an existing JPEG file for the hosting check.")
            token = None
            if args.prompt_token:
                if not sys.stdin.isatty():
                    raise ValueError("Run this check in an interactive terminal where input can be hidden.")
                token = getpass("Paste your Meta test token (hidden): ").strip()
                if not token:
                    raise ValueError("No token was entered.")
            print(Instagram.from_env(token=token).preflight(args.username, args.artwork))
        if args.command == "export-artwork":
            from .art import create_jpeg
            from .instagram import filename

            with transaction(path) as state:
                scheduled = [story for story in state["stories"] if story["status"] == "approved"
                             and not any(src["group"].startswith("demo-") for src in story["sources"])]
            args.directory.mkdir(parents=True, exist_ok=True)
            for story in scheduled:
                jpeg = create_jpeg(story)
                target = args.directory / filename(story, jpeg)
                if not target.exists():
                    target.write_bytes(jpeg)
            print(f"Artwork ready for {len(scheduled)} scheduled posts.")
        if args.command == "reconcile":
            reconcile(path, args.story_id, args.media_id)
            print("Publish attempt reconciled.")
    except (RuntimeError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
