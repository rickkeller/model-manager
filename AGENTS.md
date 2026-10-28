# Model Manager

This package answers a harness. It does not switch a live model. Do not write a consumer config, a router, a cron job, or a trading runner from this repository. Do not add secrets or a provider key.

## Layout

```
model_manager/store.py     open_store() and Store: registry.json, import/approve/health/place, ask/advise/due
model_manager/__main__.py  read-only CLI: `model-manager --root DIR {ask USE | advise PLACEMENT | due}`
tests/test_store.py        unittest tests against a temp registry
```

## Run and test

```sh
python3 -m venv .venv && .venv/bin/pip install -e .
python3 -m unittest discover -s tests
# a missing registry exits 2 and does not create registry.json
python3 -m model_manager --root "$(mktemp -d)" ask coding
```

Always use a temp `--root` in tests and manual runs. Never point one at a live registry.

## Conventions

- Standard library only.
- The CLI only reads. Registry changes go through the `Store` methods. If you add a CLI write command, document it in the README and test it.
- A new or changed release never enters `ask` results without `approve()`.
- Registry writes stay atomic: a temp file, then fsync, then `os.replace`.
- The package never calls a provider, and never reads or writes a caller's config.
- Every behaviour change needs a test.

## Secrets: never commit them

- No provider API keys, tokens or `.env` files, anywhere.
- Don't commit a real `registry.json`, or real host paths, in code, tests or docs.
