"""Luna RPG v6 - JSON Repair Pipeline.

Multi-step repair for malformed LLM JSON output.
This is the core solution to the v5 JSON failure problem.

Pipeline:
1. Strip markdown fences
2. Extract JSON object boundaries
3. Fix common syntax errors
4. Escape unescaped newlines in strings
5. Normalize field types
6. Pydantic validation
7. Fallback extraction via regex
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Error types
# =============================================================================

class RepairErrorType(str, Enum):
    OK         = "ok"
    PARSE      = "parse"       # JSON malformed — retry with hint
    VALIDATION = "validation"  # JSON valid but schema wrong
    EMPTY      = "empty"       # No text field in response


@dataclass
class RepairResult:
    data:           Optional[Dict[str, Any]]
    error_type:     RepairErrorType = RepairErrorType.OK
    error_message:  str = ""
    correction_hint: str = ""
    was_repaired:   bool = False


# =============================================================================
# Step 1-4: String-level repairs
# =============================================================================

def _strip_markdown(text: str) -> str:
    """Remove markdown code fences."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json_object(text: str) -> Optional[str]:
    """Extract first balanced JSON object from text."""
    start = text.find("{")
    if start < 0:
        return None

    depth    = 0
    in_str   = False
    escaped  = False

    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    # Unbalanced — close with missing braces
    if depth > 0:
        return text[start:] + ("}" * depth)
    return text[start:]


def _fix_syntax(text: str) -> str:
    """Fix common LLM JSON syntax errors."""
    # Trailing commas before } or ]
    text = re.sub(r",(\s*[}\]])", r"\1", text)

    # Python literals → JSON
    text = text.replace(": True",  ": true")
    text = text.replace(": False", ": false")
    text = text.replace(": None",  ": null")
    text = text.replace(":True",   ": true")
    text = text.replace(":False",  ": false")

    # Remove JS/Python comments
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    # Unquoted keys: { key: "value" } → { "key": "value" }
    text = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)', r'\1"\2"\3', text)

    return text


def _escape_newlines_in_strings(text: str) -> str:
    """Escape literal newlines inside JSON strings."""
    out: list[str] = []
    in_str  = False
    escaped = False
    for ch in text:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            elif ch == "\n":
                out.append("\\n")
                continue
        else:
            if ch == '"':
                in_str = True
        out.append(ch)
    return "".join(out)


# =============================================================================
# Step 5: Field normalization
# =============================================================================

def _normalize_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """Fix common field-level type errors before Pydantic validation."""

    # text must be a string
    if "text" not in data:
        data["text"] = ""
    elif not isinstance(data["text"], str):
        data["text"] = str(data["text"])

    # visual_en must be a string
    if "visual_en" in data and not isinstance(data["visual_en"], str):
        data["visual_en"] = str(data["visual_en"])

    # tags_en must be a list of strings
    if "tags_en" in data:
        raw = data["tags_en"]
        if isinstance(raw, str):
            data["tags_en"] = [t.strip() for t in raw.split(",") if t.strip()]
        elif isinstance(raw, list):
            data["tags_en"] = [str(t) for t in raw if t]
        else:
            data["tags_en"] = []

    # aspect_ratio must be one of the valid values
    valid_ratios = {"portrait", "landscape", "square"}
    if data.get("aspect_ratio") not in valid_ratios:
        data["aspect_ratio"] = "portrait"

    # updates normalization
    updates = data.get("updates", {})
    if isinstance(updates, dict):
        # affinity_change must be dict of str→int
        ac = updates.get("affinity_change", {})
        if isinstance(ac, int):
            updates["affinity_change"] = {}
        elif isinstance(ac, dict):
            updates["affinity_change"] = {
                k: max(-5, min(5, int(v)))
                for k, v in ac.items()
                if isinstance(v, (int, float))
            }
        else:
            updates["affinity_change"] = {}

        # outfit_update: if string, wrap in dict
        ou = updates.get("outfit_update")
        if isinstance(ou, str):
            updates["outfit_update"] = {"description": ou}

        data["updates"] = updates
    else:
        data["updates"] = {}

    return data


# =============================================================================
# Step 7: Regex emergency extraction
# =============================================================================

def _regex_extract(text: str) -> Dict[str, Any]:
    """Last resort: extract key fields via regex."""
    data: Dict[str, Any] = {
        "text":         "",
        "visual_en":    "",
        "tags_en":      [],
        "aspect_ratio": "portrait",
        "composition":  None,
        "updates":      {},
    }

    # Extract text field
    m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    if m:
        data["text"] = m.group(1).replace('\\"', '"').replace("\\n", "\n").strip()

    # Extract visual_en
    m = re.search(r'"visual_en"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    if m:
        data["visual_en"] = m.group(1).replace('\\"', '"').strip()

    # Extract aspect_ratio
    m = re.search(r'"aspect_ratio"\s*:\s*"(portrait|landscape|square)"', text)
    if m:
        data["aspect_ratio"] = m.group(1)

    # Extract composition
    m = re.search(r'"composition"\s*:\s*"([^"]+)"', text)
    if m:
        data["composition"] = m.group(1).strip()

    # Extract tags_en array
    m = re.search(r'"tags_en"\s*:\s*\[([^\]]*)\]', text, re.DOTALL)
    if m:
        data["tags_en"] = [t for t in re.findall(r'"([^"]+)"', m.group(1)) if t.strip()]

    logger.debug("[JSONRepair] Regex extraction: text=%r", data["text"][:60])
    return data


# =============================================================================
# Main repair function
# =============================================================================

def repair_json(raw: str) -> RepairResult:
    """Full repair pipeline for malformed LLM JSON.

    Returns RepairResult with data=dict on success,
    or data=None with error details on failure.
    """
    if not raw or not raw.strip():
        return RepairResult(
            data=None,
            error_type=RepairErrorType.EMPTY,
            error_message="Empty response",
            correction_hint=_parse_hint(),
        )

    # ── Step 1: Strip markdown ──────────────────────────────────────────────
    text = _strip_markdown(raw)

    # ── Step 2: Try direct parse ────────────────────────────────────────────
    try:
        data = json.loads(text)
        if isinstance(data, list) and data:
            data = data[0] if isinstance(data[0], dict) else {}
        if isinstance(data, dict):
            data = _normalize_fields(data)
            return RepairResult(data=data, was_repaired=False)
    except json.JSONDecodeError:
        pass

    # ── Step 3: Extract JSON object ─────────────────────────────────────────
    extracted = _extract_json_object(text)
    if extracted:
        text = extracted

    # ── Step 4: Fix syntax ──────────────────────────────────────────────────
    text = _fix_syntax(text)

    # ── Step 5: Escape newlines ─────────────────────────────────────────────
    text = _escape_newlines_in_strings(text)

    # ── Step 6: Try parse after repair ──────────────────────────────────────
    try:
        data = json.loads(text)
        if isinstance(data, list) and data:
            data = data[0] if isinstance(data[0], dict) else {}
        if isinstance(data, dict):
            data = _normalize_fields(data)
            logger.debug("[JSONRepair] Repaired successfully")
            return RepairResult(data=data, was_repaired=True)
    except json.JSONDecodeError as e:
        logger.warning("[JSONRepair] All repair steps failed: %s", e)

    # ── Step 7: Regex emergency extraction ──────────────────────────────────
    data = _regex_extract(raw)
    if data.get("text"):
        logger.warning("[JSONRepair] Using regex extraction fallback")
        return RepairResult(
            data=data,
            error_type=RepairErrorType.PARSE,
            error_message="Regex extraction used",
            correction_hint=_parse_hint(),
            was_repaired=True,
        )

    # ── Complete failure ─────────────────────────────────────────────────────
    return RepairResult(
        data=None,
        error_type=RepairErrorType.PARSE,
        error_message=f"JSON parse failed after all repair steps",
        correction_hint=_parse_hint(),
    )


# =============================================================================
# Correction hints (injected into retry prompt)
# =============================================================================

def _parse_hint() -> str:
    return (
        "\n\n[SYSTEM: Previous response was not valid JSON. "
        "You MUST respond with a single JSON object only. "
        "No markdown, no code blocks, no text before or after. "
        'Start with { and end with }. '
        'Required fields: "text" (string), "visual_en" (string), '
        '"tags_en" (array), "aspect_ratio" (portrait|landscape|square), '
        '"updates" (object). Example: '
        '{"text": "Luna ti sorride.", "visual_en": "Luna smiling", '
        '"tags_en": ["1girl"], "aspect_ratio": "portrait", "updates": {}}]'
    )


def _validation_hint(error: str) -> str:
    return (
        f"\n\n[SYSTEM: JSON had schema errors: {error[:200]}. "
        "Ensure: 'text' is a non-empty string in Italian, "
        "'tags_en' is a list of strings, "
        "'updates.affinity_change' is a dict like {\"Luna\": 2}, "
        "'aspect_ratio' is exactly one of: portrait, landscape, square.]"
    )
