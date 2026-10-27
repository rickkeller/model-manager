# Model Manager

A small, standalone **model registry** that an agent harness can ask "which model should I use for this job?" It keeps a JSON registry of models: billing tier, rank, uses, approval status and observed health. It also records where each model is configured ("placements"). From that it answers three questions:

- **`ask <use>`:** a ranked list of approved, healthy models for that use. Free comes first, then monthly, then paid, then by rank.
- **`advise <placement>`:** whether a configured slot should change, and to which model.
- **`due`:** which placed models need a health check.

It **never switches a model**. It doesn't write the caller's config, call a provider, run a cron job or install anything. The caller reads the answer and acts on it. Jig can use it, and so can any other harness. It doesn't live inside either one.

It is not Otto Model Manager, and it is not the Hermes `model_manager.py` script. Those can switch a live config. This package can't.

## Requirements

- Python 3.11 or newer. There are no third-party dependencies.

## Install

```sh
git clone https://github.com/rickkeller/model-manager
cd model-manager
python3 -m venv .venv && .venv/bin/pip install -e .
```

## Quickstart

> **The CLI can only read.** It can't add, approve or place models, or record health. Do those from Python (step 1). The CLI then answers questions from the registry (step 2).

1. **Fill the registry from Python.** It lives in `registry.json` inside a directory you choose:

   ```python
   from model_manager.store import open_store

   s = open_store("/path/to/registry-dir")          # created if missing
   s.import_snapshot({
       "fast-free": {"provider": "example", "model_id": "example/fast-1",
                     "billing": "free", "uses": ["fast", "coding"], "rank": 1},
       "big-paid":  {"provider": "example", "model_id": "example/big-2",
                     "billing": "paid", "uses": ["coding"], "rank": 1},
   })
   for name in ("fast-free", "big-paid"):
       s.approve(name)                  # new models start as "discovered" and are never returned until approved
       s.mark_health(name, "up")        # "up", "down" or "unknown", as observed by you
   s.place("my-app-coding", "my-app config: coding_model",
           current="big-paid", fallback="fast-free", use="coding")
   ```

2. **Ask it from the CLI.** The output is JSON on stdout:

   ```sh
   model-manager --root /path/to/registry-dir ask coding           # [fast-free, big-paid]
   model-manager --root /path/to/registry-dir advise my-app-coding # suggested: fast-free, reason: better approved model
   model-manager --root /path/to/registry-dir due                  # placed models whose health is unknown/down or whose release changed
   ```

## Registry rules

- **A new model is not used yet.** `import_snapshot` records it as `discovered` with health `unknown`. Only `approve(name)` makes it eligible.
- **A changed release drops out until it's re-approved.** If a later snapshot changes a model's `model_id`, `billing`, `rank` or `uses`, the new values are held as `seen_*`. The model leaves `ask` results and shows up in `due` until you approve it again and record its health.
- **Down models are skipped.** For a placement whose current model is down, `advise` suggests the fallback, but only if the fallback is approved and healthy.
- **Writes are atomic.** The registry is written to a temp file and then renamed into place.
- **Hermes paths are refused.** A `--root` path containing a `.hermes` directory is rejected.

### Python API

`open_store(root)` returns a `Store` with these methods: `import_snapshot(models)`, `approve(name)`, `mark_health(name, health, reason="")`, `place(name, where, current, fallback, use)`, `ask(use)`, `advise(placement)` and `due()`.

## Configuration

The only setting is `--root DIR`, which is required for every command. There are no environment variables or config files.

## Troubleshooting

- **`ask` returns `[]`.** No model is both approved and not down for that use. Check that you called `approve()`, and that the use string exactly matches one in the model's `uses`.
- **`KeyError: '<name>'`.** `advise` got a placement that doesn't exist, or `place()` named a model that isn't in the registry.
- **`Refused: a Hermes path is not this store`.** Choose a `--root` outside any `.hermes` directory.
- **`error: the following arguments are required: --root`.** Pass `--root` **before** the subcommand: `model-manager --root DIR ask coding`.
- **A model vanished from `ask` after an import.** Its release changed (see [Registry rules](#registry-rules)). Approve it again once you've checked it.

## Development

```sh
python3 -m unittest discover -s tests
```

See [AGENTS.md](AGENTS.md).

## License

MIT. See [LICENSE](LICENSE).
