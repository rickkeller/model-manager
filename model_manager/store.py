"""Standalone model registry. A harness asks. This package does not switch a model."""

import fcntl
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

BILLING_ORDER = {"free": 0, "monthly": 1, "paid": 2}
SCHEMA = 1
MAX_AGE_SECONDS = 86400
_TRACKED = ("provider", "model_id", "billing", "rank", "uses")
_IMPORT_FIELDS = set(_TRACKED)
_STRIPPED = {
    "release", "health", "health_reason", "approved", "status", "checked_at", "schema",
    "seen_provider", "seen_model_id", "seen_billing", "seen_rank", "seen_uses",
}


class Refused(RuntimeError):
    pass


def open_store(root, *, create=True):
    path = _checked_root(root)
    file = path / "registry.json"
    if not create:
        if not file.is_file():
            raise Refused("registry.json is missing")
        return Store(file)
    path.mkdir(parents=True, exist_ok=True)
    if not file.exists():
        file.write_text(_empty(), encoding="utf-8")
    return Store(file)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self._reload()

    def save(self):
        self.data["schema"] = SCHEMA
        text = json.dumps(self.data, indent=2, sort_keys=True) + "\n"
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".registry-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
            dir_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            if os.path.exists(name):
                os.unlink(name)
            raise

    def import_snapshot(self, models):
        """Record this import. It does not approve, place, or set health."""
        if not isinstance(models, dict):
            raise Refused("snapshot must be an object")
        cleaned = {str(name): _import_row(row) for name, row in models.items()}

        def mutate():
            added = []
            present = set(cleaned)
            for name, row in cleaned.items():
                current = self.data["models"].get(name)
                if current is None or current.get("status") == "missing":
                    self.data["models"][name] = {**row, "status": "discovered", "health": "unknown"}
                    added.append(name)
                    continue
                for key in list(current):
                    if key.startswith("seen_"):
                        current.pop(key, None)
                changed = False
                for key in _TRACKED:
                    if row[key] != current.get(key):
                        current["seen_" + key] = row[key]
                        changed = True
                if row["model_id"] != current.get("model_id") or row["provider"] != current.get("provider"):
                    current["health"] = "unknown"
                    current.pop("checked_at", None)
                    current.pop("health_reason", None)
                if row["provider"] != current.get("provider"):
                    current["status"] = "discovered"
                if changed:
                    current["release"] = "changed"
                else:
                    current.pop("release", None)
            for name, row in self.data["models"].items():
                if name not in present:
                    row["status"] = "missing"
                    row.pop("release", None)
                    for key in list(row):
                        if key.startswith("seen_"):
                            row.pop(key, None)
            return added

        return self._change(mutate)

    def approve(self, name):
        def mutate():
            row = self._model(name)
            if row.get("status") == "missing":
                raise Refused("a missing model is not approvable")
            for key in _TRACKED:
                seen = "seen_" + key
                if seen in row:
                    row[key] = row.pop(seen)
            row["status"] = "approved"
            row.pop("release", None)

        self._change(mutate)

    def mark_health(self, name, health, reason=""):
        if health not in ("up", "down", "unknown"):
            raise Refused("health must be up, down, or unknown")
        if not isinstance(reason, str):
            raise Refused("health reason must be text")

        def mutate():
            row = self._model(name)
            row["health"] = health
            row["health_reason"] = reason
            row["checked_at"] = datetime.now(UTC).isoformat()

        self._change(mutate)

    def place(self, name, where, current, fallback, use):
        if current == fallback:
            raise Refused("fallback must not be the current model")
        if not isinstance(use, str) or not use:
            raise Refused("use must be text")

        def mutate():
            current_row = self._model(current)
            fallback_row = self._model(fallback)
            if fallback_row.get("status") == "missing" or current_row.get("status") == "missing":
                raise Refused("a missing model cannot be placed")
            uses = fallback_row.get("uses")
            if not isinstance(uses, list) or use not in uses:
                raise Refused("fallback does not allow that use")
            self.data["placements"][name] = {
                "where": where,
                "current": current,
                "fallback": fallback,
                "use": use,
            }

        self._change(mutate)

    def ask(self, use, *, include_unknown=False, max_age_seconds=MAX_AGE_SECONDS):
        self._read()
        now = datetime.now(UTC)
        ranked = []
        for name, row in self.data["models"].items():
            if row.get("status") != "approved" or row.get("release") == "changed":
                continue
            if row.get("health") == "down":
                continue
            if row.get("health") != "up" and not include_unknown:
                continue
            if row.get("health") == "up" and _stale(row, max_age_seconds, now):
                continue
            uses = row.get("uses")
            if not isinstance(uses, list) or use not in uses:
                continue
            ranked.append(name)
        ranked.sort(key=lambda item: (
            BILLING_ORDER[self.data["models"][item]["billing"]],
            self.data["models"][item]["rank"],
            item,
        ))
        return [self._detail(name) for name in ranked]

    def advise(self, placement):
        self._read()
        row = self.data["placements"].get(placement)
        if row is None:
            raise Refused(f"unknown placement {placement}")
        if row.get("current") == row.get("fallback"):
            raise Refused("fallback must not be the current model")
        current = self._model(row["current"])
        fallback = self._model(row["fallback"])
        use = row.get("use")
        now = datetime.now(UTC)
        fallback_ok = _fallback_ok(fallback, use, now)
        suggested = None
        reason = None
        if current.get("health") in ("down", "unknown", None) or current.get("status") == "missing":
            if fallback_ok:
                suggested = row["fallback"]
                reason = "current-down" if current.get("health") == "down" else "current-unknown"
            else:
                reason = "both-unavailable"
        elif current.get("release") == "changed":
            reason = "release-changed"
        elif _stale(current, MAX_AGE_SECONDS, now):
            reason = "check-stale"
            if fallback_ok:
                suggested = row["fallback"]
        else:
            better = self.ask(use)
            if better and better[0]["name"] != row["current"]:
                suggested = better[0]["name"]
                reason = "better-approved"
        return {
            "placement": placement,
            "where": row.get("where"),
            "current": row["current"],
            "suggested": suggested,
            "reason": reason,
        }

    def due(self, *, max_age_seconds=MAX_AGE_SECONDS):
        self._read()
        now = datetime.now(UTC)
        names = []
        for row in self.data["placements"].values():
            for key in ("current", "fallback"):
                name = row.get(key)
                model = self.data["models"].get(name) or {}
                if (
                    model.get("health") in (None, "unknown", "down")
                    or model.get("release") == "changed"
                    or model.get("status") == "missing"
                    or _stale(model, max_age_seconds, now)
                ):
                    names.append(name)
        return sorted({name for name in names if name})

    def _model(self, name):
        row = self.data["models"].get(name)
        if row is None:
            raise Refused(f"unknown model {name}")
        return row

    def _detail(self, name):
        row = self._model(name)
        return {
            "name": name,
            "provider": row.get("provider"),
            "model_id": row.get("model_id"),
            "billing": row.get("billing"),
            "health": row.get("health"),
        }

    def _change(self, mutate):
        return self._locked(True, mutate)

    def _read(self):
        self._locked(False, lambda: None)

    def _locked(self, exclusive, fn):
        lock_path = self.path.with_name(".registry.lock")
        with open(lock_path, "a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            try:
                self._reload()
                result = fn()
                if exclusive:
                    self.save()
                return result
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _reload(self):
        self.data = json.loads(self.path.read_text(encoding="utf-8"))
        _check_store(self.data)


def _empty():
    return json.dumps({"schema": SCHEMA, "models": {}, "placements": {}}, indent=2, sort_keys=True) + "\n"


def _checked_root(root):
    path = Path(root)
    resolved = path.resolve()
    parts = (*path.parts, *resolved.parts)
    if any(part.casefold() == ".hermes" for part in parts):
        raise Refused("a reserved path is not this store")
    return resolved


def _import_row(row):
    if not isinstance(row, dict):
        raise Refused("model row must be an object")
    cleaned = {key: value for key, value in row.items() if key not in _STRIPPED}
    unknown = set(cleaned) - _IMPORT_FIELDS
    if unknown:
        raise Refused(f"unknown field {sorted(unknown)[0]}")
    missing = _IMPORT_FIELDS - set(cleaned)
    if missing:
        raise Refused(f"missing field {sorted(missing)[0]}")
    provider = cleaned["provider"]
    model_id = cleaned["model_id"]
    if not isinstance(provider, str) or not provider or not isinstance(model_id, str) or not model_id:
        raise Refused("provider and model_id must be text")
    return {
        "provider": provider,
        "model_id": model_id,
        "billing": _billing(cleaned["billing"]),
        "rank": _rank(cleaned["rank"]),
        "uses": _uses(cleaned["uses"]),
    }


def _check_store(data):
    if not isinstance(data, dict) or not isinstance(data.get("models"), dict) or not isinstance(data.get("placements"), dict):
        raise Refused("registry is not a model store")
    schema = data.get("schema", SCHEMA)
    if schema != SCHEMA:
        raise Refused("unknown schema")
    for row in data["models"].values():
        if not isinstance(row, dict):
            raise Refused("model row must be an object")
        if "billing" in row:
            _billing(row["billing"])
        if "rank" in row:
            _rank(row["rank"])
        if "uses" in row:
            _uses(row["uses"])
        health = row.get("health")
        if health is not None and health not in ("up", "down", "unknown"):
            raise Refused("health must be up, down, or unknown")
        status = row.get("status")
        if status is not None and status not in ("discovered", "approved", "missing"):
            raise Refused("unknown status")


def _billing(value):
    if value not in BILLING_ORDER:
        raise Refused("billing must be free, monthly, or paid")
    return value


def _rank(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise Refused("rank must be an integer")
    return value


def _uses(value):
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise Refused("uses must be a list of text")
    return list(value)


def _stale(row, max_age_seconds, now):
    stamp = row.get("checked_at")
    if not isinstance(stamp, str):
        return True
    try:
        checked = datetime.fromisoformat(stamp)
    except ValueError:
        return True
    if checked.tzinfo is None:
        return True
    return (now - checked).total_seconds() > max_age_seconds


def _fallback_ok(row, use, now):
    uses = row.get("uses")
    return (
        row.get("status") == "approved"
        and row.get("health") == "up"
        and row.get("release") != "changed"
        and isinstance(uses, list)
        and use in uses
        and not _stale(row, MAX_AGE_SECONDS, now)
    )
