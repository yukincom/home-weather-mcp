"""Persist location settings only; never weather responses."""

import copy
import fcntl
import json
import math
import os
import tempfile
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo


def clean_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    if not value or len(value) > 120 or any(ord(c) < 32 for c in value):
        raise ValueError("Names must contain 1 to 120 characters.")
    return value


def validate_location(item: dict) -> dict:
    result = dict(item)
    for field in ("alias", "place_name"):
        result[field] = clean_name(result[field])
    result["additional_aliases"] = [clean_name(name) for name in result.get("additional_aliases", [])]
    names = [result["alias"], *result["additional_aliases"]]
    if len(names) > 10 or len({name.casefold() for name in names}) != len(names):
        raise ValueError("Use at most 10 unique names per location.")
    if not isinstance(result.get("is_default", False), bool):
        raise ValueError("is_default must be a boolean.")
    for field, limit in (("latitude", 90), ("longitude", 180)):
        value = result[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > limit:
            raise ValueError(f"{field} is out of range.")
    ZoneInfo(result["timezone"])
    return result


DEFAULT_LOCATIONS = [{
    "alias": "Tokyo", "additional_aliases": ["東京"], "place_name": "Tokyo, Japan",
    "latitude": 35.6895, "longitude": 139.69171,
    "timezone": "Asia/Tokyo", "is_default": True,
}]


class LocationStore:
    def __init__(self, path: Path):
        self.path = path

    def list(self) -> list[dict]:
        if not self.path.exists():
            return copy.deepcopy(DEFAULT_LOCATIONS)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("locations"), list):
            raise ValueError("Invalid location configuration format.")
        rows = [validate_location(row) for row in data["locations"]]
        self._validate_rows(rows)
        return rows

    @staticmethod
    def _validate_rows(rows):
        aliases = [name.casefold() for row in rows for name in [row["alias"], *row["additional_aliases"]]]
        if len(rows) > 3 or len(set(aliases)) != len(aliases):
            raise ValueError("Use at most 3 locations with unique names.")
        if rows and sum(row.get("is_default", False) for row in rows) != 1:
            raise ValueError("Exactly one default location is required.")

    def get(self, alias: str | None = None) -> dict:
        if alias is None:
            for row in self.list():
                if row.get("is_default"):
                    return row
            raise ValueError("No locations registered. Use weather_set_location to add one.")
        alias = clean_name(alias)
        for row in self.list():
            if alias.casefold() in [name.casefold() for name in [row["alias"], *row["additional_aliases"]]]:
                return row
        raise ValueError(f"Unknown location: {alias}. Use weather_list_locations to check names.")

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(self.path.suffix + ".lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _write(self, rows):
        self._validate_rows(rows)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".locations-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "locations": rows}, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def set(self, item: dict) -> dict:
        item = validate_location(item)
        with self._lock():
            rows = self.list()
            index = next((i for i, row in enumerate(rows) if row["alias"].casefold() == item["alias"].casefold()), None)
            if index is not None:
                raise ValueError("Name already registered. Use weather_update_location to change it.")
            elif len(rows) >= 3:
                raise ValueError("At most 3 locations are allowed. Update or remove an existing location.")
            else:
                item["is_default"] = item.get("is_default", False) or not rows
                rows.append(item)
            if item.get("is_default"):
                for row in rows:
                    row["is_default"] = row["alias"] == item["alias"]
            self._write(rows)
        return item

    def update(self, alias: str, updates: dict) -> dict:
        with self._lock():
            old = self.get(alias)
            rows = self.list()
            item = validate_location({**old, **updates})
            rows = [item if row["alias"] == old["alias"] else row for row in rows]
            if updates.get("is_default"):
                for row in rows:
                    row["is_default"] = row is item
            self._write(rows)
        return item

    def remove(self, alias: str) -> dict:
        with self._lock():
            old = self.get(alias)
            rows = [row for row in self.list() if row["alias"] != old["alias"]]
            if rows and old.get("is_default"):
                rows[0]["is_default"] = True
            self._write(rows)
        return old
