"""Storage interface and local JSON backend for Pie backtester."""

from __future__ import annotations

import json
import math
import os
import uuid
from typing import Any, Protocol

LOCAL_STORAGE_FILE = "saved_pies.json"


def validate_pie(data: dict[str, Any]) -> tuple[bool, str]:
    """Validate a pie schema.

    Expected format:
    {
        "version": 1,
        "name": str (optional, default "Untitled Pie"),
        "currency": str,
        "assets": [{"ticker": str, "weight": float, "name": optional[str]}],
        ...
    }
    Or legacy format:
    {
        "pie": [{"Ticker": str, "Name": str, "Weight %": float}],
        "currency": str
    }
    """
    if not isinstance(data, dict):
        return False, "Pie data must be a JSON object"

    # Normalize or extract assets
    assets = data.get("assets")
    if assets is None and "pie" in data:
        # legacy format support
        legacy_assets = data.get("pie")
        if isinstance(legacy_assets, list):
            assets = [
                {"ticker": item.get("Ticker", ""), "weight": item.get("Weight %", 0.0), "name": item.get("Name", "")}
                if isinstance(item, dict) else item
                for item in legacy_assets
            ]

    if not isinstance(assets, list) or len(assets) == 0:
        return False, "Pie must contain at least one asset"

    total_weight = 0.0
    for idx, asset in enumerate(assets):
        if not isinstance(asset, dict):
            return False, f"Asset at index {idx} must be an object"
        ticker = asset.get("ticker") or asset.get("Ticker")
        if not ticker or not isinstance(ticker, str) or not ticker.strip():
            return False, f"Asset at index {idx} is missing a valid ticker"

        try:
            w = float(asset.get("weight", asset.get("Weight %", 0.0)))
        except (ValueError, TypeError):
            return False, f"Asset '{ticker}' has an invalid weight"

        if not math.isfinite(w):
            return False, f"Asset '{ticker}' has an invalid weight"
        if w < 0:
            return False, f"Asset '{ticker}' weight cannot be negative"
        total_weight += w

    if abs(total_weight - 100.0) > 0.01:
        return False, f"Weights must sum to 100% (got {total_weight:.2f}%)"

    return True, ""


def normalize_pie(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure pie data is in standard version 1 schema."""
    is_valid, err = validate_pie(data)
    if not is_valid:
        raise ValueError(f"Invalid pie data: {err}")

    assets_raw = data.get("assets")
    if assets_raw is None and "pie" in data:
        assets_raw = [
            {
                "ticker": item.get("Ticker", "").strip().upper(),
                "weight": float(item.get("Weight %", 0.0)),
                "name": str(item.get("Name") or "").strip() or item.get("Ticker", "").strip().upper()
            }
            for item in data["pie"]
        ]
    else:
        assets_raw = [
            {
                "ticker": str(item.get("ticker", item.get("Ticker", ""))).strip().upper(),
                "weight": float(item.get("weight", item.get("Weight %", 0.0))),
                "name": str(item.get("name") or item.get("Name") or "").strip() or str(item.get("ticker", item.get("Ticker", ""))).strip().upper()
            }
            for item in assets_raw
        ]

    normalized = {
        "version": 1,
        "id": str(data.get("id") or uuid.uuid4()),
        "name": str(data.get("name", "Untitled Pie")).strip() or "Untitled Pie",
        "currency": str(data.get("currency", "EUR")).upper(),
        "assets": assets_raw,
        "start": data.get("start"),
        "end": data.get("end"),
        "initial": float(data.get("initial")) if data.get("initial") is not None else 1000.0,
        "monthly": float(data.get("monthly")) if data.get("monthly") is not None else 0.0,
        "rebalance": str(data.get("rebalance", "Never")),
        "before_listing": str(data.get("before_listing", "wait")),
        "is_public": bool(data.get("is_public", False)),
        "is_example": bool(data.get("is_example", False)),
    }
    return normalized


class StorageBackend(Protocol):
    def list_pies(self, user_id: str | None = None) -> list[dict[str, Any]]:
        ...

    def get_pie(self, pie_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        ...

    def save_pie(self, pie_data: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
        ...

    def delete_pie(self, pie_id: str, user_id: str | None = None) -> bool:
        ...

    def update_pie(self, pie_id: str, user_id: str | None = None, name: str | None = None,
                   is_public: bool | None = None) -> bool:
        ...


class LocalStorageBackend:
    def __init__(self, filepath: str = LOCAL_STORAGE_FILE):
        self.filepath = filepath

    def _read_all(self) -> dict[str, dict[str, Any]]:
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_all(self, data: dict[str, dict[str, Any]]) -> None:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def list_pies(self, user_id: str | None = None) -> list[dict[str, Any]]:
        pies = self._read_all()
        return list(pies.values())

    def get_pie(self, pie_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        pies = self._read_all()
        return pies.get(pie_id)

    def save_pie(self, pie_data: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
        normalized = normalize_pie(pie_data)
        pie_id = normalized["id"]
        pies = self._read_all()
        pies[pie_id] = normalized
        self._write_all(pies)
        return normalized

    def delete_pie(self, pie_id: str, user_id: str | None = None) -> bool:
        pies = self._read_all()
        if pie_id in pies:
            del pies[pie_id]
            self._write_all(pies)
            return True
        return False

    def update_pie(self, pie_id: str, user_id: str | None = None, name: str | None = None,
                   is_public: bool | None = None) -> bool:
        """Rename and/or publish a saved pie. An empty name is refused."""
        pies = self._read_all()
        if pie_id not in pies or (name is not None and not name.strip()):
            return False
        if name is not None:
            pies[pie_id]["name"] = name.strip()
        if is_public is not None:
            pies[pie_id]["is_public"] = bool(is_public)
        self._write_all(pies)
        return True


EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "examples")


def list_examples() -> list[dict[str, Any]]:
    """Load and return all valid example pies from the examples directory."""
    examples = []
    if not os.path.exists(EXAMPLES_DIR):
        return examples

    for filename in sorted(os.listdir(EXAMPLES_DIR)):
        if filename.endswith(".json"):
            filepath = os.path.join(EXAMPLES_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                is_valid, _ = validate_pie(data)
                if is_valid:
                    norm = normalize_pie(data)
                    norm["file"] = filename
                    examples.append(norm)
            except Exception:
                continue
    return examples


import requests

MAX_PIES_PER_USER = 20
MAX_ASSETS_PER_PIE = 30


def _quote(value: str) -> str:
    """Quote a value for a PostgREST or=(...) list, where , . : ( ) are syntax."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class SupabaseStorageBackend:
    """Supabase used as a plain database from the Streamlit server.

    Requests use the service key, which bypasses row-level security, so this class
    is what keeps users apart: every read, write and delete is filtered by owner.
    Owners are app user ids (e.g. "google:<sub>"), not Supabase Auth users.
    """

    # what usually causes each answer, for the warning in the sidebar
    ERROR_HINTS = {
        401: "the key isn't the secret/service_role key",
        403: "the key isn't the secret/service_role key",
        404: "the pies table doesn't exist yet: deploy or run the migration in supabase/migrations/",
    }

    def __init__(self, url: str, key: str):
        self.table = f"{url.rstrip('/')}/rest/v1/pies"
        self.key = key
        self.last_error: str | None = None  # why the last read failed; None after a successful one

    def _headers(self) -> dict[str, str]:
        headers = {"apikey": self.key, "Content-Type": "application/json", "Prefer": "return=representation"}
        if not self.key.startswith("sb_"):  # legacy service_role JWT; new sb_secret_ keys aren't JWTs
            headers["Authorization"] = f"Bearer {self.key}"
        return headers

    @staticmethod
    def _from_row(row: dict[str, Any]) -> dict[str, Any]:
        config = dict(row.get("config") or {})
        config.update(id=row.get("id"), name=row.get("name", config.get("name")),
                      is_public=row.get("is_public", False))
        pie = normalize_pie(config)
        pie["owner_id"] = row.get("owner_id")
        return pie

    def _select(self, params: dict[str, str]) -> list[dict[str, Any]]:
        # A failed read returns no pies, so the app keeps working; last_error says why,
        # so a missing table or a wrong key doesn't look like "no pies saved yet".
        try:
            resp = requests.get(self.table, params={"select": "*", **params}, headers=self._headers(), timeout=5)
        except Exception as e:
            self.last_error = f"couldn't reach Supabase ({e})"
            return []
        if resp.status_code != 200:
            hint = self.ERROR_HINTS.get(resp.status_code)
            self.last_error = f"HTTP {resp.status_code}" + (f": {hint}" if hint else f" ({resp.text[:200]})")
            return []
        self.last_error = None
        return [self._from_row(r) for r in resp.json()]

    @staticmethod
    def _visible_to(user_id: str | None) -> dict[str, str]:
        if not user_id:
            return {"is_public": "eq.true"}
        return {"or": f"(is_public.eq.true,owner_id.eq.{_quote(user_id)})"}

    def list_pies(self, user_id: str | None = None) -> list[dict[str, Any]]:
        return self._select(self._visible_to(user_id))

    def get_pie(self, pie_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        rows = self._select({"id": f"eq.{pie_id}", **self._visible_to(user_id)})
        return rows[0] if rows else None

    def save_pie(self, pie_data: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
        if not user_id:
            raise ValueError("Sign in to save pies.")
        normalized = normalize_pie(pie_data)
        if len(normalized["assets"]) > MAX_ASSETS_PER_PIE:
            raise ValueError(f"Pie exceeds maximum allowed assets ({MAX_ASSETS_PER_PIE}).")
        if len(self._select({"owner_id": f"eq.{user_id}"})) >= MAX_PIES_PER_USER:
            raise ValueError(f"Maximum pie limit ({MAX_PIES_PER_USER}) reached. Delete a pie to save a new one.")

        payload = {
            "id": normalized["id"],
            "owner_id": user_id,
            "name": normalized["name"],
            "is_public": normalized["is_public"],
            "is_example": normalized["is_example"],
            "config": normalized,
        }
        try:
            resp = requests.post(self.table, json=payload, headers=self._headers(), timeout=5)
        except Exception as e:
            raise RuntimeError(f"Failed to save pie to Supabase: {e}")
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Failed to save pie to Supabase: HTTP {resp.status_code} {resp.text[:200]}")
        rows = resp.json()
        return self._from_row(rows[0]) if rows else normalized

    def delete_pie(self, pie_id: str, user_id: str | None = None) -> bool:
        if not user_id:
            return False
        try:
            resp = requests.delete(self.table, params={"id": f"eq.{pie_id}", "owner_id": f"eq.{user_id}"},
                                   headers=self._headers(), timeout=5)
        except Exception:
            return False
        # PostgREST answers 200 even when the filter matched nothing (someone else's pie)
        return resp.status_code == 200 and bool(resp.json())

    def update_pie(self, pie_id: str, user_id: str | None = None, name: str | None = None,
                   is_public: bool | None = None) -> bool:
        """Rename and/or publish a saved pie; only its owner can. An empty name is refused."""
        if not user_id or (name is not None and not name.strip()):
            return False
        rows = self._select({"id": f"eq.{pie_id}", "owner_id": f"eq.{user_id}"})
        if not rows:  # not found, or someone else's pie
            return False
        # name and is_public live in their columns and inside config, so both change
        changes = {}
        if name is not None:
            changes["name"] = name.strip()
        if is_public is not None:
            changes["is_public"] = bool(is_public)
        config = {k: v for k, v in rows[0].items() if k != "owner_id"} | changes
        try:
            resp = requests.patch(self.table, params={"id": f"eq.{pie_id}", "owner_id": f"eq.{user_id}"},
                                  json={**changes, "config": config}, headers=self._headers(), timeout=5)
        except Exception:
            return False
        return resp.status_code == 200 and bool(resp.json())


def get_storage(backend_type: str | None = None, **kwargs) -> StorageBackend:
    if backend_type == "supabase" or (backend_type is None and kwargs.get("url") and kwargs.get("key")):
        return SupabaseStorageBackend(url=kwargs["url"], key=kwargs["key"])
    return LocalStorageBackend(filepath=kwargs.get("filepath", LOCAL_STORAGE_FILE))
