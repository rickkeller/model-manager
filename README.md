# Model Manager

A standalone registry a harness can install. Jig can call it. Another harness can call it. It does not live in either one.

It is not Otto Model Manager. It is not the Hermes `model_manager.py` script. Those can switch a live config. This package cannot.

## What it does

- Keeps a registry the caller imports. A new release is recorded as discovered. It is not approved and it is not placed.
- Answers `ask(use)` with a ranked list. Free and monthly come before paid. A down model is skipped. The caller launches the thread.
- Records health the caller observed. `due()` names models that need a check. This package does not install a cron and does not call a provider.
- Records where a model is configured, including the current model and the fallback. `advise(placement)` names the place to change. It does not write that place.

## Install

```text
pip install -e .
```

The store is a directory the caller chooses. A Hermes path is refused.
