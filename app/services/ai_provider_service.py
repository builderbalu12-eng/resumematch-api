"""
Unified AI provider service — routes every AI call to either Gemini or Claude
based on the active provider setting stored in MongoDB.

Exported callables:
  call_ai(prompt, ...)                      → sync  → Dict (JSON)
  call_ai_text_async(prompt, ...)           → async → str  (plain text)
  call_ai_chat_async(history, msg, ...)     → async → str  (chat response)
  get_active_provider_sync()                → sync  → "gemini" | "claude"
  get_active_provider()                     → async → "gemini" | "claude"
  set_active_provider(provider, email)      → async → None
  init_active_provider()                    → async → None  (call at startup)
"""

import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional

from app.services.mongo import mongo

logger = logging.getLogger(__name__)

# ── In-memory active provider (sync-safe) ────────────────────
_active_provider: Dict = {"value": "gemini"}

_prov_cache: Dict = {}
_prov_cache_time: float = 0.0
_PROV_CACHE_TTL = 60  # seconds


# ─────────────────────────────────────────────────────────────
# Active provider management
# ─────────────────────────────────────────────────────────────

def get_active_provider_sync() -> str:
    """Sync accessor — no DB hit. Used by call_ai() on every request."""
    return _active_provider.get("value", "gemini")


async def get_active_provider() -> str:
    """Async — reads DB with 60s cache. Used by admin endpoints."""
    global _prov_cache, _prov_cache_time

    now = time.monotonic()
    if _prov_cache and (now - _prov_cache_time) < _PROV_CACHE_TTL:
        return _prov_cache.get("value", "gemini")

    try:
        doc = await mongo.admin_settings.find_one({"_id": "active_ai_provider"})
        provider = doc.get("provider", "gemini") if doc else "gemini"
    except Exception as e:
        logger.warning(f"Could not read active_ai_provider from DB: {e}")
        provider = "gemini"

    _prov_cache = {"value": provider}
    _prov_cache_time = now
    _active_provider["value"] = provider
    return provider


async def set_active_provider(provider: str, admin_email: str) -> None:
    """Persist the active provider to DB and update sync cache immediately."""
    global _prov_cache_time

    if provider not in ("gemini", "claude"):
        raise ValueError(f"Invalid provider: {provider!r}. Must be 'gemini' or 'claude'.")

    await mongo.admin_settings.update_one(
        {"_id": "active_ai_provider"},
        {"$set": {
            "provider":   provider,
            "updated_at": datetime.utcnow(),
            "updated_by": admin_email,
        }},
        upsert=True,
    )
    _active_provider["value"] = provider
    _prov_cache_time = 0.0  # invalidate async cache
    logger.info(f"Active AI provider switched to '{provider}' by {admin_email}")


async def init_active_provider() -> None:
    """Called once at startup to load active provider from DB."""
    provider = await get_active_provider()
    _active_provider["value"] = provider
    logger.info(f"✅ Active AI provider loaded: {provider}")


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
    Mirrors call_gemini() signature and error format exactly.
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
# Unified sync JSON call  (replaces call_gemini everywhere)
# ─────────────────────────────────────────────────────────────

def call_ai(
    prompt: str,
    temperature: float = 1.0,
    max_tokens: int = 8192,
    model: Optional[str] = None,
) -> Dict:
    """
    Drop-in replacement for call_gemini().
    Routes to Gemini or Claude based on the active provider.
    Returns a parsed JSON Dict or {"error": ..., "message": ...}.
    """
    provider = get_active_provider_sync()
    if provider == "claude":
        return call_claude(prompt, temperature=temperature, max_tokens=max_tokens, model=model)

    # Gemini path — import here to avoid circular imports
    from app.services.resume_processor import call_gemini
    return call_gemini(prompt, temperature=temperature, max_tokens=max_tokens, model=model)


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
    Async text-only call — returns raw string, not JSON.
    Used by intent_classifier and any other non-JSON text generation.
    """
    import asyncio

    provider = get_active_provider_sync()

    if provider == "claude":
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
            return response.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Claude text async call failed: {e}")
            return ""

    else:
        # Gemini path
        import google.generativeai as genai
        from app.services.gemini_config_service import get_active_config_sync as gcfg_sync
        cfg = gcfg_sync()
        try:
            gmodel = genai.GenerativeModel(
                model_name=model or cfg["model"],
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                    "top_p": 0.8,
                    "top_k": 40,
                },
            )
            response = await gmodel.generate_content_async(prompt)
            return response.text.strip()
        except Exception as e:
            logger.warning(f"Gemini text async call failed: {e}")
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
    Async multi-turn chat call.
    history format: [{"role": "user"|"model", "parts": ["text"]}]  (Gemini native format)
    Returns the assistant's response as a plain string.
    """
    provider = get_active_provider_sync()

    if provider == "claude":
        try:
            import anthropic as _anthropic
        except ImportError:
            return "Claude package not installed."

        from app.services.claude_config_service import get_active_config_sync
        cfg = get_active_config_sync()
        if not cfg.get("api_key"):
            return "Claude API key not set. Please add it in Admin → Resources → Claude."

        active_model = model or cfg["model"]

        # Convert Gemini history format → Claude messages format
        messages = []
        for msg in history:
            role = "user" if msg.get("role") == "user" else "assistant"
            content = msg.get("parts", [""])[0] if msg.get("parts") else ""
            if content:
                messages.append({"role": role, "content": content})

        # Ensure history starts with a user message (Claude requirement)
        while messages and messages[0]["role"] != "user":
            messages.pop(0)

        # Add the current user message
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
            return response.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Claude chat async call failed: {e}")
            return "I'm having trouble generating a response right now. Please try again."

    else:
        # Gemini path — preserve existing chat session behaviour
        import google.generativeai as genai
        from app.services.gemini_config_service import get_active_config_sync as gcfg_sync
        cfg = gcfg_sync()
        try:
            gmodel = genai.GenerativeModel(
                model_name=model or cfg["model"],
                system_instruction=system_instruction,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                    "top_p": 0.8,
                    "top_k": 40,
                },
            )
            # Ensure history starts with user (Gemini requirement)
            h = list(history)
            while h and h[0]["role"] != "user":
                h.pop(0)
            chat = gmodel.start_chat(history=h)
            resp = await chat.send_message_async(user_message)
            return resp.text.strip()
        except Exception as e:
            logger.warning(f"Gemini chat async call failed: {e}")
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


def _convert_tools_for_gemini(tools: list) -> list:
    """Convert provider-agnostic tool defs → Gemini FunctionDeclaration list."""
    import google.generativeai as genai

    type_map = {
        "string":  genai.protos.Type.STRING,
        "integer": genai.protos.Type.INTEGER,
        "number":  genai.protos.Type.NUMBER,
        "boolean": genai.protos.Type.BOOLEAN,
        "array":   genai.protos.Type.ARRAY,
        "object":  genai.protos.Type.OBJECT,
    }

    declarations = []
    for t in tools:
        properties = {
            k: genai.protos.Schema(
                type=type_map.get(v["type"], genai.protos.Type.STRING),
                description=v.get("description", ""),
            )
            for k, v in t["parameters"].items()
        }
        declarations.append(
            genai.protos.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties=properties,
                    required=t.get("required", []),
                ),
            )
        )
    return declarations


# ─────────────────────────────────────────────────────────────
# Provider-specific tool-calling implementations
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


async def _call_gemini_with_tools_async(
    system_prompt: str,
    history: list,
    message: str,
    tools: list,
) -> dict:
    import google.generativeai as genai
    from app.services.gemini_config_service import get_active_config_sync as gcfg_sync
    cfg = gcfg_sync()

    try:
        function_declarations = _convert_tools_for_gemini(tools)
        gemini_tools = [genai.protos.Tool(function_declarations=function_declarations)]

        gmodel = genai.GenerativeModel(
            model_name=cfg["model"],
            system_instruction=system_prompt,
            tools=gemini_tools,
        )

        h = []
        for m in history:
            h.append({
                "role":  "user" if m["role"] == "user" else "model",
                "parts": [m["content"]],
            })
        while h and h[0]["role"] != "user":
            h.pop(0)

        chat     = gmodel.start_chat(history=h)
        response = await chat.send_message_async(message)

        usage    = getattr(response, "usage_metadata", None)
        input_tokens  = getattr(usage, "prompt_token_count",     0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0

        for part in response.parts:
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", None):
                return {
                    "type":      "tool_call",
                    "tool_name": fc.name,
                    "tool_args": dict(fc.args),
                    "raw_response":  response,
                    "input_tokens":  input_tokens,
                    "output_tokens": output_tokens,
                    "provider_state": {"provider": "gemini", "chat": chat},
                }

        return {
            "type": "text",
            "text": response.text.strip(),
            "raw_response":  response,
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "provider_state": {"provider": "gemini"},
        }

    except Exception as e:
        logger.warning(f"Gemini tool call failed: {e}")
        return {"type": "text", "text": "I'm having trouble right now. Please try again.", "input_tokens": 0, "output_tokens": 0, "provider_state": {"provider": "gemini"}}


# ─────────────────────────────────────────────────────────────
# Public unified tool-calling entry point
# ─────────────────────────────────────────────────────────────

async def call_ai_with_tools_async(
    system_prompt: str,
    history: list,
    message: str,
    tools: list,
) -> dict:
    """
    Route a function-calling request to the active provider (Claude or Gemini).

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
    provider = get_active_provider_sync()
    if provider == "claude":
        return await _call_claude_with_tools_async(system_prompt, history, message, tools)
    return await _call_gemini_with_tools_async(system_prompt, history, message, tools)


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
    Send a tool result back to the AI and get the final natural-language response.
    Falls back to returning the summary directly if the round-trip fails.
    """
    provider = (provider_state or {}).get("provider", get_active_provider_sync())

    if provider == "claude":
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

    else:  # gemini
        try:
            import google.generativeai as genai
            chat = provider_state.get("chat")
            if not chat:
                return tool_result_summary

            tool_response_content = genai.protos.Content(
                parts=[genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=tool_name,
                        response={"result": tool_result_summary},
                    )
                )],
                role="user",
            )
            response = await chat.send_message_async(tool_response_content)
            return response.text.strip()

        except Exception as e:
            logger.warning(f"Gemini tool result round-trip failed: {e}")
            return tool_result_summary
