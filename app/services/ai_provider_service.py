"""
Claude-only AI provider service. Every AI call routes to Anthropic Claude.

Exported callables:
  call_ai(prompt, ...)                      → sync  → Dict (JSON)
  call_ai_text_async(prompt, ...)           → async → str  (plain text)
  call_ai_chat_async(history, msg, ...)     → async → str  (chat response)
  call_ai_with_tools_async(...)             → async → dict (tool-call response)
  send_tool_result_async(...)               → async → str  (final reply after tool)
  get_active_provider_sync()                → sync  → "claude"
  get_active_provider()                     → async → "claude"
  set_active_provider(...)                  → async → None  (no-op shim, kept for compat)
  init_active_provider()                    → async → None  (call at startup)
"""

import json
import time
import logging
import contextvars
from datetime import datetime
from typing import Dict, List, Optional

from app.services.mongo import mongo

logger = logging.getLogger(__name__)

# ── In-memory active provider (sync-safe) ────────────────────
# Claude is the only supported provider. The toggle is kept for back-compat
# of admin endpoints but every value is forced to "claude" here. Do NOT change.
_active_provider: Dict = {"value": "claude"}

_prov_cache: Dict = {}
_prov_cache_time: float = 0.0
_PROV_CACHE_TTL = 60  # seconds

# ── Per-request token accumulator ────────────────────────────
# call_claude() adds tokens here; controllers read and persist them onto the
# matching credits_log entry via CreditsService.commit_ai_tokens().
_request_tokens_var: "contextvars.ContextVar[Optional[Dict[str, int]]]" = (
    contextvars.ContextVar("ai_request_tokens", default=None)
)


def reset_request_tokens() -> None:
    _request_tokens_var.set({"input": 0, "output": 0})


def get_request_tokens() -> Dict[str, int]:
    val = _request_tokens_var.get()
    return dict(val) if val else {"input": 0, "output": 0}


def _accumulate_tokens(input_t: int, output_t: int) -> None:
    cur = _request_tokens_var.get()
    if cur is None:
        cur = {"input": 0, "output": 0}
        _request_tokens_var.set(cur)
    cur["input"] += int(input_t or 0)
    cur["output"] += int(output_t or 0)


# ─────────────────────────────────────────────────────────────
# Active provider management
# ─────────────────────────────────────────────────────────────

def get_active_provider_sync() -> str:
    """Sync accessor. Claude is the only provider — always returns 'claude'."""
    return "claude"


async def get_active_provider() -> str:
    """Async accessor. Claude is the only provider — always returns 'claude'."""
    return "claude"


async def set_active_provider(provider: str, admin_email: str) -> None:
    """No-op shim. Provider toggle is disabled (Claude-only).
    Kept for API compatibility with admin_routes.py callers."""
    if provider != "claude":
        logger.info(f"Ignored provider switch to '{provider}' from {admin_email}; system is Claude-only.")
    # do nothing — _active_provider stays "claude"


async def init_active_provider() -> None:
    """Claude-only startup hook."""
    _active_provider["value"] = "claude"
    logger.info("✅ AI provider locked to Claude")


# ─────────────────────────────────────────────────────────────
# Claude helpers (sync)
# ─────────────────────────────────────────────────────────────

def _clean_json(text: str) -> str:
    """Remove markdown fences — mirrors resume_processor.clean_json_response."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    if text.startswith("```"):
        text = text[3:].strip()
    return text


def call_claude(
    prompt: str,
    temperature: float = 1.0,
    max_tokens: int = 8192,
    model: Optional[str] = None,
) -> Dict:
    """
    Single-turn Claude call — returns parsed JSON Dict.
    """
    try:
        import anthropic as _anthropic
    except ImportError:
        return {"error": "claude_not_installed", "message": "anthropic package not installed. Run: pip install anthropic"}

    from app.services.claude_config_service import get_active_config_sync
    cfg = get_active_config_sync()

    if not cfg.get("api_key"):
        return {"error": "claude_no_key", "message": "Claude API key not set. Add it in Admin → Resources → Claude."}

    active_model = model or cfg["model"]

    for attempt in range(2):
        try:
            client = _anthropic.Anthropic(api_key=cfg["api_key"])
            response = client.messages.create(
                model=active_model,
                max_tokens=min(max_tokens, 8192),
                temperature=min(temperature, 1.0),  # Claude max temp is 1.0
                messages=[{"role": "user", "content": prompt}],
            )

            try:
                _accumulate_tokens(
                    getattr(response.usage, "input_tokens", 0) or 0,
                    getattr(response.usage, "output_tokens", 0) or 0,
                )
            except Exception:
                pass

            raw_text = response.content[0].text.strip()
            cleaned = _clean_json(raw_text)

            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as e:
                logger.warning(f"Claude JSON parse failed (attempt {attempt + 1})")
                if attempt == 1:
                    return {
                        "error": "invalid_json",
                        "message": "Claude output was not valid JSON",
                        "parse_error": str(e),
                        "raw_preview": cleaned[:2000],
                    }

        except Exception as e:
            err_msg = str(e)
            if "rate_limit" in err_msg.lower() or "429" in err_msg or "overloaded" in err_msg.lower():
                logger.error(f"Claude rate limit hit on model {active_model}.")
                return {"error": "claude_api_error", "message": err_msg}
            if attempt == 1:
                logger.exception("Claude API call failed")
                return {"error": "claude_api_error", "message": err_msg}

    return {"error": "unknown_error", "message": "Unexpected Claude failure"}


# ─────────────────────────────────────────────────────────────
# Unified sync JSON call
# ─────────────────────────────────────────────────────────────

def call_ai(
    prompt: str,
    temperature: float = 1.0,
    max_tokens: int = 8192,
    model: Optional[str] = None,
) -> Dict:
    """
    Unified sync JSON call. Routes to Claude.
    Returns a parsed JSON Dict or {"error": ..., "message": ...}.
    """
    return call_claude(prompt, temperature=temperature, max_tokens=max_tokens, model=model)


# ─────────────────────────────────────────────────────────────
# Unified async text call  (for intent classifier, etc.)
# ─────────────────────────────────────────────────────────────

async def call_ai_text_async(
    prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 200,
    model: Optional[str] = None,
) -> str:
    """
    Async text-only Claude call — returns raw string, not JSON.
    Used by intent_classifier and any other non-JSON text generation.
    """
    try:
        import anthropic as _anthropic
    except ImportError:
        return ""

    from app.services.claude_config_service import get_active_config_sync
    cfg = get_active_config_sync()
    if not cfg.get("api_key"):
        return ""

    active_model = model or cfg["model"]
    try:
        client = _anthropic.AsyncAnthropic(api_key=cfg["api_key"])
        response = await client.messages.create(
            model=active_model,
            max_tokens=max_tokens,
            temperature=min(temperature, 1.0),
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            _accumulate_tokens(
                getattr(response.usage, "input_tokens", 0) or 0,
                getattr(response.usage, "output_tokens", 0) or 0,
            )
        except Exception:
            pass
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Claude text async call failed: {e}")
        return ""


# ─────────────────────────────────────────────────────────────
# Unified async chat call  (for ai_chat_service)
# ─────────────────────────────────────────────────────────────

async def call_ai_chat_async(
    history: List[Dict],
    user_message: str,
    system_instruction: str,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    model: Optional[str] = None,
) -> str:
    """
    Async multi-turn Claude chat call.
    history format: [{"role": "user"|"model"|"assistant", "parts": ["text"]}]
    (the legacy "model" role is mapped to "assistant" for Claude.)
    Returns the assistant's response as a plain string.
    """
    try:
        import anthropic as _anthropic
    except ImportError:
        return "Claude package not installed."

    from app.services.claude_config_service import get_active_config_sync
    cfg = get_active_config_sync()
    if not cfg.get("api_key"):
        return "Claude API key not set. Please add it in Admin → Resources → Claude."

    active_model = model or cfg["model"]

    # Normalise history → Claude messages format
    messages = []
    for msg in history:
        role = "user" if msg.get("role") == "user" else "assistant"
        content = msg.get("parts", [""])[0] if msg.get("parts") else ""
        if content:
            messages.append({"role": role, "content": content})

    # Claude requires history to start with a user message
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    messages.append({"role": "user", "content": user_message})

    try:
        client = _anthropic.AsyncAnthropic(api_key=cfg["api_key"])
        response = await client.messages.create(
            model=active_model,
            max_tokens=min(max_tokens, 8192),
            temperature=min(temperature, 1.0),
            system=system_instruction,
            messages=messages,
        )
        try:
            _accumulate_tokens(
                getattr(response.usage, "input_tokens", 0) or 0,
                getattr(response.usage, "output_tokens", 0) or 0,
            )
        except Exception:
            pass
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Claude chat async call failed: {e}")
        return "I'm having trouble generating a response right now. Please try again."


# ─────────────────────────────────────────────────────────────
# Tool conversion helpers
# ─────────────────────────────────────────────────────────────

def _convert_tools_for_claude(tools: list) -> list:
    """Convert provider-agnostic tool defs → Claude input_schema format."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": {
                "type": "object",
                "properties": {
                    k: {"type": v["type"], "description": v.get("description", "")}
                    for k, v in t["parameters"].items()
                },
                "required": t.get("required", []),
            },
        }
        for t in tools
    ]


# ─────────────────────────────────────────────────────────────
# Claude tool-calling implementation
# ─────────────────────────────────────────────────────────────

async def _call_claude_with_tools_async(
    system_prompt: str,
    history: list,
    message: str,
    tools: list,
) -> dict:
    try:
        import anthropic as _anthropic
    except ImportError:
        return {"type": "text", "text": "Claude not installed.", "input_tokens": 0, "output_tokens": 0, "provider_state": {}}

    from app.services.claude_config_service import get_active_config_sync
    cfg = get_active_config_sync()
    if not cfg.get("api_key"):
        return {"type": "text", "text": "Claude API key not configured.", "input_tokens": 0, "output_tokens": 0, "provider_state": {}}

    claude_tools = _convert_tools_for_claude(tools)

    messages = []
    for m in history:
        role = "user" if m["role"] == "user" else "assistant"
        messages.append({"role": role, "content": m["content"]})
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    messages.append({"role": "user", "content": message})

    try:
        client = _anthropic.AsyncAnthropic(api_key=cfg["api_key"])
        response = await client.messages.create(
            model=cfg["model"],
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
            tools=claude_tools,
        )

        input_tokens  = getattr(response.usage, "input_tokens",  0) or 0
        output_tokens = getattr(response.usage, "output_tokens", 0) or 0
        try:
            _accumulate_tokens(input_tokens, output_tokens)
        except Exception:
            pass

        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                return {
                    "type":       "tool_call",
                    "tool_name":  block.name,
                    "tool_args":  block.input,
                    "raw_response": response,
                    "input_tokens":  input_tokens,
                    "output_tokens": output_tokens,
                    "provider_state": {
                        "provider":    "claude",
                        "messages":    messages,
                        "claude_tools": claude_tools,
                        "tool_use_id": block.id,
                    },
                }

        text = next(
            (b.text for b in response.content if hasattr(b, "text")),
            "I couldn't generate a response.",
        )
        return {
            "type": "text",
            "text": text.strip(),
            "raw_response": response,
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "provider_state": {"provider": "claude"},
        }

    except Exception as e:
        logger.warning(f"Claude tool call failed: {e}")
        return {"type": "text", "text": "I'm having trouble right now. Please try again.", "input_tokens": 0, "output_tokens": 0, "provider_state": {"provider": "claude"}}


# ─────────────────────────────────────────────────────────────
# Public tool-calling entry point (Claude-only)
# ─────────────────────────────────────────────────────────────

async def call_ai_with_tools_async(
    system_prompt: str,
    history: list,
    message: str,
    tools: list,
) -> dict:
    """
    Run a function-calling request through Claude.

    Returns dict with keys:
      type          → "text" | "tool_call"
      text          → str  (when type == "text")
      tool_name     → str  (when type == "tool_call")
      tool_args     → dict (when type == "tool_call")
      raw_response  → provider's raw response object
      input_tokens  → int
      output_tokens → int
      provider_state → dict  (needed by send_tool_result_async)
    """
    return await _call_claude_with_tools_async(system_prompt, history, message, tools)


async def send_tool_result_async(
    system_prompt: str,
    history: list,
    message: str,
    first_response_raw,
    tool_name: str,
    tool_result_summary: str,
    provider_state: dict,
    tools: list = None,
) -> str:
    """
    Send a tool result back to Claude and get the final natural-language response.
    Falls back to returning the summary directly if the round-trip fails.
    """
    try:
        import anthropic as _anthropic
        from app.services.claude_config_service import get_active_config_sync
        cfg = get_active_config_sync()

        messages = list(provider_state.get("messages", []))
        messages.append({"role": "assistant", "content": first_response_raw.content})
        messages.append({
            "role": "user",
            "content": [
                {
                    "type":        "tool_result",
                    "tool_use_id": provider_state.get("tool_use_id", ""),
                    "content":     tool_result_summary,
                }
            ],
        })

        claude_tools = provider_state.get("claude_tools", [])
        client   = _anthropic.AsyncAnthropic(api_key=cfg["api_key"])
        response = await client.messages.create(
            model=cfg["model"],
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
            tools=claude_tools,
        )
        text = next(
            (b.text for b in response.content if hasattr(b, "text")),
            tool_result_summary,
        )
        return text.strip()

    except Exception as e:
        logger.warning(f"Claude tool result round-trip failed: {e}")
        return tool_result_summary
