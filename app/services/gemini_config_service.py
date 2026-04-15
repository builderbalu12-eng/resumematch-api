"""
DB-backed Gemini configuration with a 60-second in-memory cache.

Allows the admin UI to update the active API key / model at runtime
without restarting the server. Falls back to .env values if no DB
override is set.
"""

import time
import logging
from datetime import datetime
from typing import Dict

import google.generativeai as genai

from app.config import settings
from app.services.mongo import mongo

logger = logging.getLogger(__name__)

# ── Available models with free-tier limits (from Google docs) ─
AVAILABLE_MODELS = [
    {"id": "gemini-2.5-flash",      "name": "Gemini 2.5 Flash",      "rpd": 500,  "rpm":  5, "tpm": 250_000},
    {"id": "gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash-Lite", "rpd": 1500, "rpm": 30, "tpm": 1_000_000},
    {"id": "gemini-2.0-flash",      "name": "Gemini 2.0 Flash",      "rpd": 1500, "rpm": 15, "tpm": 1_000_000},
    {"id": "gemini-2.0-flash-lite", "name": "Gemini 2.0 Flash-Lite", "rpd": 1500, "rpm": 30, "tpm": 1_000_000},
    {"id": "gemini-1.5-flash",      "name": "Gemini 1.5 Flash",      "rpd": 1500, "rpm": 15, "tpm": 1_000_000},
    {"id": "gemini-1.5-pro",        "name": "Gemini 1.5 Pro",        "rpd":   50, "rpm":  2, "tpm":    32_000},
]

# ── In-memory active config (sync-safe, populated at startup) ─
# This is the single source of truth for call_gemini() — no async needed.
_active_config: Dict = {}

# ── Async cache (used only for /admin/resources/gemini reads) ─
_cache: Dict = {}
_cache_time: float = 0.0
_CACHE_TTL = 60  # seconds


def _default_config() -> Dict:
    return {
        "api_key":     settings.gemini_api_key,
        "model":       settings.gemini_model,
        "temperature": 0.2,
        "max_tokens":  4096,
        "updated_at":  None,
        "updated_by":  None,
    }


def get_active_config_sync() -> Dict:
    """
    Synchronous accessor for the active Gemini config.
    Called by call_gemini() on every request — no async, no DB hit.
    Populated at startup and updated immediately on admin save.
    """
    return _active_config if _active_config else _default_config()


async def get_gemini_config() -> Dict:
    """Async version — reads DB, populates/refreshes both caches."""
    global _cache, _cache_time, _active_config

    now = time.monotonic()
    if _cache and (now - _cache_time) < _CACHE_TTL:
        return _cache

    try:
        doc = await mongo.admin_settings.find_one({"_id": "gemini_config"})
    except Exception as e:
        logger.warning(f"Could not read admin_settings from DB: {e}")
        doc = None

    cfg = {
        "api_key":     (doc.get("api_key")   if doc and doc.get("api_key")  else None) or settings.gemini_api_key,
        "model":       (doc.get("model")     if doc and doc.get("model")    else None) or settings.gemini_model,
        "temperature":  doc.get("temperature", 0.2) if doc else 0.2,
        "max_tokens":   doc.get("max_tokens",  4096) if doc else 4096,
        "updated_at":   doc.get("updated_at") if doc else None,
        "updated_by":   doc.get("updated_by") if doc else None,
    }

    _cache = cfg
    _cache_time = now
    _active_config = cfg  # keep sync dict in sync
    return cfg


async def init_gemini_config() -> None:
    """
    Called once at startup (main.py → startup_event).
    Loads config from DB, applies to genai immediately so all products
    use the correct key/model from the very first request.
    """
    global _active_config
    cfg = await get_gemini_config()
    _active_config = cfg
    genai.configure(api_key=cfg["api_key"])
    logger.info(f"✅ Gemini config loaded from DB: model={cfg['model']}")


async def save_gemini_config(data: Dict, admin_email: str) -> None:
    global _active_config, _cache_time

    allowed_keys = {"api_key", "model", "temperature", "max_tokens"}
    update = {k: v for k, v in data.items() if k in allowed_keys}
    update["updated_at"] = datetime.utcnow()
    update["updated_by"] = admin_email

    await mongo.admin_settings.update_one(
        {"_id": "gemini_config"},
        {"$set": update},
        upsert=True,
    )

    # Apply immediately — no 60-second wait
    _active_config = {**_active_config, **update}
    genai.configure(api_key=_active_config["api_key"])
    _cache_time = 0.0  # invalidate async cache too

    logger.info(f"Gemini config saved by {admin_email}: {list(update.keys())}, active immediately")
