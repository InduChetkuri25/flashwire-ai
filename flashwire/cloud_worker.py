"""Entrypoint for the persistent Linux cloud worker."""
import argparse
import logging
import os
from pathlib import Path

from .instagram import Instagram
from .standalone import cycle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    folder = Path.home() / ".local/share/flashwire"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ["FLASHWIRE_DB"] = str(folder / "desk.sqlite")
    os.environ["FLASHWIRE_ILLUSTRATIONS"] = str(folder / "illustrations")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.check:
        print(Instagram.from_env(live=True).preflight(os.environ["IG_USERNAME"]))
    else:
        cycle()


if __name__ == "__main__":
    main()
