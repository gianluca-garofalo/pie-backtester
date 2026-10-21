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


class SupabaseStorageBackend:
    def __init__(self, url: str, key: str, access_token: str | None = None):
        self.url = url.rstrip("/")
        self.key = key
        self.access_token = access_token or key

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def list_pies(self, user_id: str | None = None) -> list[dict[str, Any]]:
        try:
            url = f"{self.url}/rest/v1/pies?select=*"
            if user_id:
                url += f"&or=(is_public.eq.true,owner_id.eq.{user_id})"
            resp = requests.get(
                url,
                headers=self._headers(),
                timeout=5
            )
            if resp.status_code == 200:
                rows = resp.json()
                out = []
                for row in rows:
                    config = row.get("config", {})
                    config["id"] = row.get("id")
                    config["name"] = row.get("name", config.get("name"))
                    config["is_public"] = row.get("is_public", False)
                    config["owner_id"] = row.get("owner_id")
                    out.append(normalize_pie(config))
                return out
        except Exception:
            pass
        return []

    def get_pie(self, pie_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        try:
            resp = requests.get(
                f"{self.url}/rest/v1/pies?id=eq.{pie_id}&select=*",
                headers=self._headers(),
                timeout=5
            )
            if resp.status_code == 200:
                rows = resp.json()
                if rows:
                    row = rows[0]
                    config = row.get("config", {})
                    config["id"] = row.get("id")
                    config["name"] = row.get("name", config.get("name"))
                    config["is_public"] = row.get("is_public", False)
                    config["owner_id"] = row.get("owner_id")
                    return normalize_pie(config)
        except Exception:
            pass
        return None

    def save_pie(self, pie_data: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
        normalized = normalize_pie(pie_data)
        if len(normalized["assets"]) > MAX_ASSETS_PER_PIE:
            raise ValueError(f"Pie exceeds maximum allowed assets ({MAX_ASSETS_PER_PIE}).")

        if user_id:
            existing_user_pies = [p for p in self.list_pies(user_id) if p.get("owner_id") == user_id]
            if len(existing_user_pies) >= MAX_PIES_PER_USER and not any(p["id"] == normalized["id"] for p in existing_user_pies):
                raise ValueError(f"Maximum pie limit ({MAX_PIES_PER_USER}) reached for user.")

        payload = {
            "id": normalized["id"],
            "name": normalized["name"],
            "is_public": normalized["is_public"],
            "is_example": normalized["is_example"],
            "config": normalized,
        }
        if user_id:
            payload["owner_id"] = user_id

        try:
            resp = requests.post(
                f"{self.url}/rest/v1/pies",
                headers=self._headers(),
                json=payload,
                timeout=5
            )
        except Exception as e:
            raise RuntimeError(f"Failed to save pie to Supabase: {e}")
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Failed to save pie to Supabase: HTTP {resp.status_code} {resp.text[:200]}")
        rows = resp.json()
        if rows:
            cfg = rows[0].get("config", {})
            cfg["id"] = rows[0].get("id")
            return normalize_pie(cfg)
        return normalized

    def delete_pie(self, pie_id: str, user_id: str | None = None) -> bool:
        try:
            resp = requests.delete(
                f"{self.url}/rest/v1/pies?id=eq.{pie_id}",
                headers=self._headers(),
                timeout=5
            )
            return resp.status_code in (200, 204)
        except Exception:
            return False


def get_storage(backend_type: str | None = None, **kwargs) -> StorageBackend:
    if backend_type == "supabase" or (backend_type is None and kwargs.get("url") and kwargs.get("key")):
        return SupabaseStorageBackend(
            url=kwargs["url"],
            key=kwargs["key"],
            access_token=kwargs.get("access_token")
        )
    return LocalStorageBackend(filepath=kwargs.get("filepath", LOCAL_STORAGE_FILE))
