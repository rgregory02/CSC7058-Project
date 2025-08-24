# llm_utils.py
import os
import re
import json
from typing import Tuple, List, Dict, Any, Optional

from dotenv import load_dotenv
from jsonschema import validate, ValidationError

# Local utilities
from utils import load_labels_from_folder

# Load .env as early as possible (but do NOT import from flask.cli)
load_dotenv(override=False)

# ---------- Config & tiny logger ----------

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

LLM_DEBUG = _env_bool("LLM_DEBUG", False)

def _log(msg: str):
    if LLM_DEBUG:
        print(f"[LLM] {msg}")

# ---------- JSON helpers ----------

def _extract_first_json(text: str) -> str:
    """
    Extract the first JSON object in a string.
    Handles ```json ... ``` fences or best-effort { ... } capture.
    Always returns a string (may be empty).
    """
    if not text:
        return ""
    # ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    if m:
        return m.group(1)
    # Best-effort object
    m = re.search(r"(\{.*\})", text, flags=re.S)
    return (m.group(1) if m else text.strip())


# ---------- Public call: send to OpenAI or stub ----------

from typing import Optional
import os, json
from jsonschema import validate, ValidationError

def call_llm_json(system: str, user: str, schema: str, model: Optional[str] = None) -> str:
    """
    Call the LLM and return a JSON *string* that the caller can json.loads().

    Strategy:
      1) If OPENAI_API_KEY missing -> return deterministic stub.
      2) Try Chat Completions with JSON mode (response_format={"type":"json_object"}).
      3) If that's unavailable (TypeError) -> fall back to Responses API with JSON mode.
      4) Extract/parse/validate JSON. On any error -> return stub.

    The returned value is a JSON string (never a Python dict).
    """
    def _log(msg: str):
        if (os.getenv("DEBUG_LLM") or "").lower() in ("1", "true", "yes"):
            print(f"[LLM] {msg}")

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    use_model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")

    if not api_key:
        _log("No OPENAI_API_KEY; using stub.")
        return llm_stub(system, user, schema)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        text = ""

        # --- Path A: Chat Completions (preferred & now supported by your SDK) ---
        try:
            _log(f"Calling chat.completions.create(model={use_model!r}) with JSON mode…")
            resp = client.chat.completions.create(
                model=use_model,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
            )
            text = (resp.choices[0].message.content or "").strip()

        except TypeError as te:
            # Older/alternate environments: fall back to Responses API.
            _log(f"chat.completions.create raised {te!r}; trying responses.create instead…")
            resp = client.responses.create(
                model=use_model,
                temperature=0.2,
                max_output_tokens=800,
                response_format={"type": "json_object"},
                input=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
            )
            # New SDK gives handy aggregate text:
            text = (getattr(resp, "output_text", None) or "").strip()

        _log(f"Raw content (first 200 chars): {text[:200]!r}")

        # Some models still wrap JSON — try to extract fenced/first object.
        raw_json = _extract_first_json(text)
        if not raw_json:
            _log(f"Empty/invalid JSON for schema={schema}. Using stub.")
            return llm_stub(system, user, schema)

        try:
            data = json.loads(raw_json)
        except Exception as e:
            _log(f"JSON parse error: {e}. Using stub.")
            return llm_stub(system, user, schema)

        sch = SCHEMAS.get(schema)
        if sch:
            try:
                validate(instance=data, schema=sch)
            except ValidationError as ve:
                _log(f"Schema '{schema}' validation failed: {ve.message}. Using stub.")
                return llm_stub(system, user, schema)

        return json.dumps(data, ensure_ascii=False)

    except Exception as e:
        _log(f"Call failed ({type(e).__name__}): {e}. Using stub.")
        return llm_stub(system, user, schema)


# ---------- Local stub (dev/offline) ----------

def llm_stub(system: str, user: str, schema: str) -> str:
    """
    Deterministic JSON outputs so the UI keeps working offline.
    """
    if schema == "group_suggestion_v1":
        return json.dumps(
            {
                "group_meta": {
                    "key": "example_group",
                    "name": "Example Group",
                    "description": "Demo group created by stub",
                },
                "examples": [
                    {
                        "file": "types/demo/labels/example_group/foo.json",
                        "json": {"id": "foo", "display": "Foo", "description": "Demo option"},
                    },
                    {
                        "file": "types/demo/labels/example_group/bar.json",
                        "json": {"id": "bar", "display": "Bar"},
                    },
                ],
            },
            ensure_ascii=False,
        )

    if schema == "values_suggestion_v1":
        # IMPORTANT: the server/UI expect `values: [...]`
        return json.dumps(
            {
                "values": [
                    {"id": "alpha", "display": "Alpha", "description": "Demo"},
                    {"id": "beta", "display": "Beta"},
                    {"id": "gamma", "display": "Gamma"},
                ]
            },
            ensure_ascii=False,
        )

    if schema == "label_enrichment_v1":
        return json.dumps(
            {
                "description": "Richer description generated by stub",
                "aliases": ["aka one", "aka two"],
                "confidence": 92,
                "image_url_candidates": [],
            },
            ensure_ascii=False,
        )

    return "{}"


# ---------- JSON Schemas for light validation ----------

SCHEMAS: Dict[str, Dict[str, Any]] = {
    "group_suggestion_v1": {
        "type": "object",
        "properties": {
            "group_meta": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["key", "name"],
            },
            "examples": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "json": {"type": "object"},
                    },
                    "required": ["file", "json"],
                },
            },
        },
        "required": ["group_meta", "examples"],
    },

    # Suggest option VALUES for an existing group
    "values_suggestion_v1": {
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "display": {"type": "string"},
                        "description": {"type": "string"},
                        "image_url": {"type": "string"},
                        "order": {"type": "number"},
                    },
                    "required": ["id", "display"],
                },
            }
        },
        "required": ["values"],
    },

    # Enrich a single label/option with more descriptive fields
    "label_enrichment_v1": {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "aliases": {"type": "array", "items": {"type": "string"}},
            "image_url_candidates": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
        "required": [],
    },
}


# ---------- Small helpers used by routes ----------

def collect_folder_options(type_name: str, group_key: str) -> List[str]:
    """
    Return existing option IDs for a group's folder, or [] if the folder
    doesn't exist yet.
    """
    parts = (group_key or "").strip("/").split("/") if group_key else []
    folder = os.path.join("types", type_name, "labels", *parts)

    if not os.path.isdir(folder):
        return []  # no folder yet, no options yet

    try:
        items = load_labels_from_folder(folder) or []
    except FileNotFoundError:
        return []
    except Exception:
        return []

    ids: List[str] = []
    for it in items:
        if isinstance(it, dict):
            _id = (it.get("id") or it.get("name") or "").strip()
            if _id:
                ids.append(_id)
    return sorted(set(ids))


def safe_parse_llm_json(text: str, schema: str):
    """
    1) Extract fenced JSON if present.
    2) Parse JSON.
    3) Validate against a local schema.
    Returns (ok: bool, data: Any | None, err: str | None)
    """
    if not text:
        return False, None, "empty response"

    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S | re.I)
    raw = m.group(1) if m else text.strip()

    try:
        data = json.loads(raw)
    except Exception as e:
        return False, None, f"json parse: {e}"

    sch = SCHEMAS.get(schema)
    if not sch:
        return True, data, None

    try:
        validate(instance=data, schema=sch)
        return True, data, None
    except ValidationError as e:
        return False, None, f"schema: {e.message}"


# ---------- Prompt builders (ensure they match the expected schema!) ----------

def build_group_prompts(type_name: str, group_key: str, hint: str) -> Tuple[str, str]:
    system = (
        "You return STRICT JSON only. No prose. "
        "Generate label-group metadata and a few example option files."
    )
    user = f"""
Return EXACTLY this shape (no extra keys):
{{
  "group_meta": {{ "key": "...", "name": "...", "description": "..." }},
  "examples": [ {{ "file": "example.json", "json": {{ "id":"...", "display":"...", "description":"..."? }} }} ]
}}

Context:
- type: {type_name}
- group_key: {group_key}
- hint: {hint or "none"}

Rules:
- ids are snake_case; display is human-friendly; 3–6 examples.
- No images, keep descriptions short.
Only JSON.
""".strip()
    return system, user


def build_values_prompts(type_name: str, group_key: str, n: int, existing: List[Dict[str, Any]]) -> Tuple[str, str]:
    system = "You return STRICT JSON only. No prose."
    existing_ids = [str(o.get("id")) for o in (existing or []) if isinstance(o, dict) and o.get("id")]
    user = f"""
Return EXACTLY:
{{ "values": [ {{"id":"...","display":"...","description":"..."?}}, ... ] }}

Goal: Suggest up to {n} new values for the label group.
Avoid duplicates (case-insensitive) from: {existing_ids}

Context:
- type: {type_name}
- group_key: {group_key}

Rules:
- ids: snake_case; display: human-friendly.
- Description <= 120 chars; omit if unsure.
Only JSON.
""".strip()
    return system, user


def build_enrichment_prompts(context: Dict[str, Any]) -> Tuple[str, str]:
    system = "You return STRICT JSON only. No prose."
    user = f"""
Return EXACTLY:
{{ "description": "...", "aliases": [], "image_url_candidates": [], "confidence": 0-100 }}

Context: {context}

Rules:
- Description 1–2 neutral sentences; aliases if truly common; image_url_candidates only if certain.
Only JSON.
""".strip()
    return system, user