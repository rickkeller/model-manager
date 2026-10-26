"""Standalone model registry. A harness asks. This package does not switch a model."""

import json
import os
import tempfile
from pathlib import Path

BILLING_ORDER = {"free": 0, "monthly": 1, "paid": 2}


class Refused(RuntimeError):
    pass


def open_store(root):
    path = Path(root)
    if ".hermes" in path.parts:
        raise Refused("a Hermes path is not this store")
    path.mkdir(parents=True, exist_ok=True)
    file = path / "registry.json"
    if not file.exists():
        file.write_text(json.dumps({"models": {}, "placements": {}}), encoding="utf-8")
    return Store(file)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self):
        text = json.dumps(self.data, indent=2, sort_keys=True) + "\n"
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".registry-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
        except Exception:
            if os.path.exists(name):
                os.unlink(name)
            raise

    def import_snapshot(self, models):
        """A new release is recorded. It is not approved and it is not placed."""
        added = []
        for name, row in models.items():
            current = self.data["models"].get(name)
            if current is None:
                self.data["models"][name] = {**row, "status": "discovered", "health": "unknown"}
                added.append(name)
                continue
            if row.get("model_id") and row.get("model_id") != current.get("model_id"):
                current["seen_model_id"] = row["model_id"]
                current["health"] = "unknown"
                current.pop("health_reason", None)
                current["release"] = "changed"
            for key in ("billing", "rank", "uses"):
                if key in row and row.get(key) != current.get(key):
                    current["seen_" + key] = row[key]
                    current["release"] = "changed"
        self.save()
        return added

    def approve(self, name):
        row = self._model(name)
        if row.get("release") == "changed" and row.get("seen_model_id"):
            row["model_id"] = row["seen_model_id"]
        for key in ("billing", "rank", "uses"):
            seen = "seen_" + key
            if seen in row:
                row[key] = row.pop(seen)
        row.pop("seen_model_id", None)
        row["status"] = "approved"
        row.pop("release", None)
        self.save()

    def mark_health(self, name, health, reason=""):
        if health not in ("up", "down", "unknown"):
            raise Refused("health must be up, down, or unknown")
        row = self._model(name)
        row["health"] = health
        row["health_reason"] = reason
        self.save()

    def place(self, name, where, current, fallback, use):
        self._model(current)
        self._model(fallback)
        self.data["placements"][name] = {
            "where": where,
            "current": current,
            "fallback": fallback,
            "use": use,
        }
        self.save()

    def ask(self, use):
        ranked = []
        for name, row in self.data["models"].items():
            if row.get("status") != "approved" or row.get("health") == "down" or row.get("release") == "changed":
                continue
            if use not in (row.get("uses") or []):
                continue
            ranked.append(name)
        ranked.sort(key=lambda name: (BILLING_ORDER.get(self.data["models"][name].get("billing"), 9), self.data["models"][name].get("rank", 100), name))
        return [self._detail(name) for name in ranked]

    def advise(self, placement):
        row = self.data["placements"].get(placement)
        if row is None:
            raise KeyError(placement)
        current = self._model(row["current"])
        better = self.ask(row["use"])
        suggested = None
        reason = None
        if current.get("health") == "down":
            fallback = self._model(row["fallback"])
            if fallback.get("status") == "approved" and fallback.get("health") != "down" and fallback.get("release") != "changed":
                suggested = row["fallback"]
                reason = current.get("health_reason") or "down"
        elif current.get("release") == "changed":
            reason = "release changed"
        elif better and better[0]["name"] != row["current"]:
            suggested = better[0]["name"]
            reason = "better approved model"
        return {
            "placement": placement,
            "where": row["where"],
            "current": row["current"],
            "suggested": suggested,
            "reason": reason,
        }

    def due(self):
        names = []
        for row in self.data["placements"].values():
            current = self.data["models"].get(row["current"]) or {}
            if current.get("health") in (None, "unknown", "down") or current.get("release") == "changed":
                names.append(row["current"])
        return sorted(set(names))

    def _model(self, name):
        row = self.data["models"].get(name)
        if row is None:
            raise KeyError(name)
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
