"""Ask the registry. This command does not switch a model."""

import argparse
import json
import sys

from model_manager.store import MAX_AGE_SECONDS, Refused, open_store


def main(argv=None):
    parser = argparse.ArgumentParser(prog="model-manager")
    parser.add_argument("--root", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask")
    ask.add_argument("use")
    ask.add_argument("--include-unknown", action="store_true")
    ask.add_argument("--max-age", type=int, default=MAX_AGE_SECONDS)
    advise = sub.add_parser("advise")
    advise.add_argument("placement")
    due = sub.add_parser("due")
    due.add_argument("--max-age", type=int, default=MAX_AGE_SECONDS)
    args = parser.parse_args(argv)
    try:
        store = open_store(args.root, create=False)
        if args.command == "ask":
            payload = store.ask(args.use, include_unknown=args.include_unknown, max_age_seconds=args.max_age)
        elif args.command == "advise":
            payload = store.advise(args.placement)
        else:
            payload = store.due(max_age_seconds=args.max_age)
    except (Refused, OSError, json.JSONDecodeError) as error:
        sys.stderr.write(f"model-manager: {error}\n")
        return 2
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
