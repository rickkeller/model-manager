"""Ask the registry. This command does not switch a model."""

import argparse
import json
import sys

from model_manager.store import open_store


def main(argv=None):
    parser = argparse.ArgumentParser(prog="model-manager")
    parser.add_argument("--root", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask")
    ask.add_argument("use")
    advise = sub.add_parser("advise")
    advise.add_argument("placement")
    sub.add_parser("due")
    args = parser.parse_args(argv)
    store = open_store(args.root)
    if args.command == "ask":
        payload = store.ask(args.use)
    elif args.command == "advise":
        payload = store.advise(args.placement)
    else:
        payload = store.due()
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
