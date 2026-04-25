"""
DB-backed Claude configuration with a 60-second in-memory cache.

Allows the admin UI to update the active API key / model at runtime
without restarting the server. Falls back to .env values if no DB override is set.
"""

import time
import logging
from datetime import datetime
from typing import Dict

from app.config import settings
from app.services.mongo import mongo

logger = logging.getLogger(__name__)

# ── Available Claude models ───────────────────────────────────
AVAILABLE_MODELS = [
    {
        "id": "claude-opus-4-6",
        "name": "Claude Opus 4.6",
        "context_window": 200_000,
        "recommended": False,
    },
    {
        "id": "claude-sonnet-4-6",
        "name": "Claude Sonnet 4.6",
        "context_window": 200_000,
        "recommended": True,
    },
    {
        "id": "claude-haiku-4-5-20251001",
        "name": "Claude Haiku 4.5",
        "context_window": 200_000,
        "recommended": False,
    },
    {
        "id": "claude-3-5-sonnet-20241022",
        "name": "Claude 3.5 Sonnet",
        "context_window": 200_000,
        "recommended": False,
    },
    {
        "id": "claude-3-haiku-20240307",
        "name": "Claude 3 Haiku",
        "context_window": 200_000,
        "recommended": False,
    },
]

# ── In-memory active config (sync-safe, populated at startup) ─
# This is the single source of truth for call_claude() — no async needed.
_active_config: Dict = {}

# ── Async cache (used only for /admin/resources/claude reads) ─
_cache: Dict = {}
_cache_time: float = 0.0
_CACHE_TTL = 60  # seconds


def _default_config() -> Dict:
    return {
        "api_key":     settings.claude_api_key,
        "model":       settings.claude_model,
        "temperature": 0.2,
        "max_tokens":  4096,
        "updated_at":  None,
        "updated_by":  None,
    }


def get_active_config_sync() -> Dict:
    """
    Synchronous accessor for the active Claude config.
    Called by call_claude() on every request — no async, no DB hit.
    Populated at startup and updated immediately on admin save.
    """
    return _active_config if _active_config else _default_config()


async def get_claude_config() -> Dict:
    """Async version — reads DB, populates/refreshes both caches."""
    global _cache, _cache_time, _active_config

    now = time.monotonic()
    if _cache and (now - _cache_time) < _CACHE_TTL:
        return _cache

    try:
        doc = await mongo.admin_settings.find_one({"_id": "claude_config"})
    except Exception as e:
        logger.warning(f"Could not read claude_config from DB: {e}")
        doc = None

    cfg = {
        "api_key":     (doc.get("api_key")   if doc and doc.get("api_key")  else None) or settings.claude_api_key,
        "model":       (doc.get("model")     if doc and doc.get("model")    else None) or settings.claude_model,
        "temperature":  doc.get("temperature", 0.2) if doc else 0.2,
        "max_tokens":   doc.get("max_tokens",  4096) if doc else 4096,
        "updated_at":   doc.get("updated_at") if doc else None,
        "updated_by":   doc.get("updated_by") if doc else None,
    }

    _cache = cfg
    _cache_time = now
    _active_config = cfg  # keep sync dict in sync
    return cfg


async def init_claude_config() -> None:
    """
    Called once at startup (main.py → startup_event).
    Loads config from DB so all features use the correct key/model
    from the very first request. Claude uses per-call client instantiation.
    """
    global _active_config
    cfg = await get_claude_config()
    _active_config = cfg
    logger.info(f"✅ Claude config loaded: model={cfg['model']}, key_set={bool(cfg['api_key'])}")


async def save_claude_config(data: Dict, admin_email: str) -> None:
    global _active_config, _cache_time

    allowed_keys = {"api_key", "model", "temperature", "max_tokens"}
    update = {k: v for k, v in data.items() if k in allowed_keys}
    update["updated_at"] = datetime.utcnow()
    update["updated_by"] = admin_email

    await mongo.admin_settings.update_one(
        {"_id": "claude_config"},
        {"$set": update},
        upsert=True,
    )

    # Apply immediately — no 60-second wait
    _active_config = {**_active_config, **update}
    _cache_time = 0.0  # invalidate async cache too

    logger.info(f"Claude config saved by {admin_email}: {list(update.keys())}, active immediately")
