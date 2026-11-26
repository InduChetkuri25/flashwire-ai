"""Run FLASHWIRE commands with this Windows installation's saved connection."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
work = root.parent.parent / "work" / "flashwire-state"
os.chdir(root)
sys.path.insert(0, str(root))
os.environ.update(FLASHWIRE_DB=str(work / "desk.sqlite"),
                  FLASHWIRE_ILLUSTRATIONS=str(work / "illustrations"),
                  FLASHWIRE_TOKEN_FILE=str(root / "data/meta-credential.dpapi"),
                  FLASHWIRE_GITHUB_UPLOAD="yes", FLASHWIRE_LIVE="yes",
                  FLASHWIRE_GH_EXE=r"C:\Program Files\GitHub CLI\gh.exe",
                  IG_USERNAME="gk._insta", IG_ACCOUNT_ID="17841449961192703",
                  IG_API_VERSION="v27.0", IG_LOGIN_MODE="unified",
                  IMAGE_BASE_URL="https://raw.githubusercontent.com/InduChetkuri25/flashwire-ai/main/artwork")

from flashwire.__main__ import main
from flashwire.desk import approve, find, transaction, db_path
from flashwire.news import source_groups
from datetime import datetime, UTC, timedelta
import json

if sys.argv[1:] == ["cycle"]:
    import logging
    from logging.handlers import RotatingFileHandler
    from flashwire.standalone import cycle
    work.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[RotatingFileHandler(work / "worker.log", maxBytes=500000, backupCount=3)])
    try:
        cycle()
    except Exception as error:
        logging.error("Cycle failed (%s)", type(error).__name__)
        raise SystemExit(1)
elif sys.argv[1:] == ["candidates"]:
    with transaction(db_path()) as state:
        cutoff = datetime.now(UTC) - timedelta(hours=4)
        for story in state["stories"]:
            fresh = [s for s in story["sources"] if not s["discovered"] and datetime.fromisoformat(s["seen_at"]) >= cutoff]
            if story["status"] == "review" and not story.get("attempted_at") and len({s["group"] for s in fresh}) >= 2:
                print(json.dumps({"id": story["id"], "sources": fresh}))
elif sys.argv[1:] == ["schedule"]:
    item = json.load(sys.stdin)
    now = datetime.now(UTC)
    with transaction(db_path()) as state:
        story = find(state, item["id"])
        if not story or story.get("attempted_at") or story["status"] != "review":
            raise ValueError("Ineligible story")
        approve(story, item["headline"], item["caption"], now, now, True)
else:
    raise SystemExit(main())

