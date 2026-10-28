# Model Manager

A small, standalone **model registry** that an agent harness can ask "which model should I use for this job?" It keeps a JSON registry of models: billing tier, rank, uses, approval status and observed health. It also records where each model is configured ("placements"). From that it answers three questions:

- **`ask <use>`:** a ranked list of approved models for that use whose health is `up` and whose check is still fresh. Free comes first, then monthly, then paid, then by rank. `unknown` is excluded unless you pass `--include-unknown`.
- **`advise <placement>`:** whether a configured slot should change, and to which model.
- **`due`:** which placed models need a health check, including the fallback. A missing or stale `checked_at` is due. The default max age is 86400 seconds.

It never switches a model. It doesn't write the caller's config, call a provider, run a cron job or install anything. The caller reads the answer and acts on it. Jig can use it, and so can any other harness. It doesn't live inside either one.

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
   model-manager --root /path/to/registry-dir due                  # current and fallback models that are down, unknown, missing, or stale
   ```

## Registry rules

- **A new model is not used yet.** `import_snapshot` records it as `discovered` with health `unknown`. Only `approve(name)` makes it eligible. An import is the whole snapshot: a model left out is `missing` and cannot be approved until it is imported again. A provider change drops approval. Pending fields are replaced by this import, not kept from an older one.
- **A changed release drops out until it's re-approved.** If a later snapshot changes a model's `model_id`, `billing`, `rank` or `uses`, the new values are held as `seen_*`. The model leaves `ask` results and shows up in `due` until you approve it again and record its health. An id change sets health back to `unknown`, and `ask` skips `unknown` unless `include_unknown` is set.
- **Down models are skipped.** If the current model is down and the fallback is approved, up, fresh, and allows that use, `advise` suggests the fallback with reason `current-down`. If both are down or unknown, `suggested` is null and the reason is `both-unavailable`. The fallback cannot be the current model.
- **Writes are atomic.** The registry is written to a temp file, fsynced, renamed, and the directory is fsynced. A save reloads under a lock before it changes the file.
- **A reserved path is refused.** The check uses the real path, so a different case or a symlink does not bypass it.
- **A read does not create the registry.** `ask`, `advise`, and `due` exit 2 if `registry.json` is missing. `open_store(root)` still creates it for a writer.

### Python API

`open_store(root)` returns a `Store`. `open_store(root, create=False)` reads an existing registry and does not create one. Methods: `import_snapshot(models)`, `approve(name)`, `mark_health(name, health, reason="")`, `place(name, where, current, fallback, use)`, `ask(use, include_unknown=False, max_age_seconds=86400)`, `advise(placement)` and `due(max_age_seconds=86400)`.

## Configuration

The only setting is `--root DIR`, which is required for every command. There are no environment variables or config files.

## Troubleshooting

- **`ask` returns `[]`.** No model is approved, up, fresh, and matching that use. `unknown` is excluded unless you pass `--include-unknown`.
- **`model-manager: unknown placement ...`.** `advise` got a placement that doesn't exist. A missing model raises `model-manager: unknown model ...`.
- **`model-manager: a reserved path is not this store`.** Choose another directory. A symlink does not bypass the check.
- **`model-manager: registry.json is missing`.** The CLI does not create a registry. Create it from Python with `open_store`.
- **`error: the following arguments are required: --root`.** Pass `--root` **before** the subcommand: `model-manager --root DIR ask coding`.
- **A model vanished from `ask` after an import.** Its release changed (see [Registry rules](#registry-rules)). Approve it again once you've checked it.

## Development

```sh
python3 -m unittest discover -s tests
```

See [AGENTS.md](AGENTS.md).

## License

MIT. See [LICENSE](LICENSE).
