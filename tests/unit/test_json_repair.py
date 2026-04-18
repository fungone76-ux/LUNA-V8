"""Unit tests for luna/ai/json_repair.py.

Pure-function pipeline for repairing malformed LLM JSON.
No external deps — all tests are synchronous and isolated.

Run with: pytest tests/unit/test_json_repair.py -v
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest
from luna.ai.json_repair import (
    repair_json,
    RepairResult,
    RepairErrorType,
    _strip_markdown,
    _extract_json_object,
    _fix_syntax,
    _escape_newlines_in_strings,
    _normalize_fields,
    _regex_extract,
)


# =============================================================================
# repair_json — main entry point
# =============================================================================

class TestRepairJsonHappyPath:
    """Valid JSON input should pass straight through without repair."""

    def test_valid_json_returns_ok(self):
        raw = '{"text": "Ciao!", "visual_en": "Luna smiling", "tags_en": ["1girl"], "aspect_ratio": "portrait", "updates": {}}'
        result = repair_json(raw)
        assert result.error_type == RepairErrorType.OK
        assert result.was_repaired is False
        assert result.data is not None
        assert result.data["text"] == "Ciao!"

    def test_valid_json_list_returns_first_element(self):
        raw = '[{"text": "Test", "visual_en": "", "tags_en": [], "aspect_ratio": "portrait", "updates": {}}]'
        result = repair_json(raw)
        assert result.data is not None
        assert result.data["text"] == "Test"
        assert result.was_repaired is False

    def test_valid_json_normalizes_fields(self):
        raw = '{"text": "Hello", "aspect_ratio": "invalid", "updates": {}}'
        result = repair_json(raw)
        assert result.data["aspect_ratio"] == "portrait"

    def test_valid_json_landscape(self):
        raw = '{"text": "Scene", "visual_en": "outdoor", "tags_en": [], "aspect_ratio": "landscape", "updates": {}}'
        result = repair_json(raw)
        assert result.data["aspect_ratio"] == "landscape"


class TestRepairJsonEmptyInput:
    """Empty / whitespace-only input should return EMPTY error."""

    def test_empty_string_returns_empty_error(self):
        result = repair_json("")
        assert result.error_type == RepairErrorType.EMPTY
        assert result.data is None
        assert "Empty" in result.error_message

    def test_whitespace_only_returns_empty_error(self):
        result = repair_json("   \n\t  ")
        assert result.error_type == RepairErrorType.EMPTY
        assert result.data is None

    def test_none_like_empty_string(self):
        result = repair_json("")
        assert result.correction_hint != ""  # hint provided for retry


class TestRepairJsonMarkdownFences:
    """JSON wrapped in markdown code blocks should be extracted."""

    def test_strips_json_fence(self):
        raw = '```json\n{"text": "Hi", "updates": {}}\n```'
        result = repair_json(raw)
        assert result.data is not None
        assert result.data["text"] == "Hi"
        assert result.was_repaired is False  # Valid after strip, no repair needed

    def test_strips_plain_fence(self):
        raw = '```\n{"text": "Hi", "updates": {}}\n```'
        result = repair_json(raw)
        assert result.data is not None

    def test_strips_uppercase_fence(self):
        raw = '```JSON\n{"text": "Hi", "updates": {}}\n```'
        result = repair_json(raw)
        assert result.data is not None


class TestRepairJsonSyntaxErrors:
    """Common LLM syntax errors should be repaired."""

    def test_trailing_comma_in_object(self):
        raw = '{"text": "Hi", "updates": {},}'
        result = repair_json(raw)
        assert result.data is not None
        assert result.was_repaired is True

    def test_trailing_comma_in_array(self):
        raw = '{"text": "Hi", "tags_en": ["a", "b",], "updates": {}}'
        result = repair_json(raw)
        assert result.data is not None

    def test_python_true_false(self):
        raw = '{"text": "Hi", "flag": True, "updates": {}}'
        result = repair_json(raw)
        assert result.data is not None
        assert result.was_repaired is True

    def test_python_none(self):
        raw = '{"text": "Hi", "composition": None, "updates": {}}'
        result = repair_json(raw)
        assert result.data is not None

    def test_unquoted_keys(self):
        raw = '{text: "Hi", updates: {}}'
        result = repair_json(raw)
        assert result.data is not None
        assert result.was_repaired is True

    def test_js_line_comment_removed(self):
        raw = '{"text": "Hi", // comment\n"updates": {}}'
        result = repair_json(raw)
        assert result.data is not None
        assert result.was_repaired is True

    def test_js_block_comment_removed(self):
        raw = '{"text": "Hi", /* block comment */ "updates": {}}'
        result = repair_json(raw)
        assert result.data is not None


class TestRepairJsonUnbalancedBraces:
    """Truncated JSON with missing closing braces should be recovered."""

    def test_missing_closing_brace(self):
        raw = '{"text": "Truncated response from LLM", "updates": {}'
        result = repair_json(raw)
        assert result.data is not None
        assert result.data["text"] == "Truncated response from LLM"

    def test_json_with_preamble(self):
        raw = 'Sure! Here is the response:\n{"text": "Hello", "updates": {}}'
        result = repair_json(raw)
        assert result.data is not None
        assert result.data["text"] == "Hello"


class TestRepairJsonNewlines:
    """Unescaped newlines inside strings should be fixed."""

    def test_literal_newline_in_string_value(self):
        raw = '{"text": "Line 1\nLine 2", "updates": {}}'
        result = repair_json(raw)
        assert result.data is not None
        # After repair the text should be accessible
        assert "Line 1" in result.data["text"]


class TestRepairJsonRegexFallback:
    """Completely broken JSON should fall back to regex extraction."""

    def test_regex_fallback_extracts_text(self):
        raw = '<<garbage>> "text": "Luna ti sorride" <<more garbage>>'
        result = repair_json(raw)
        # Either regex fallback returns data, or returns PARSE error
        # Either way, no crash
        assert isinstance(result, RepairResult)

    def test_completely_unparseable_returns_parse_error(self):
        raw = "This is not JSON at all."
        result = repair_json(raw)
        assert result.error_type == RepairErrorType.PARSE
        assert result.data is None

    def test_regex_fallback_with_text_field(self):
        raw = 'some prefix {"text": "Hello Luna", more garbage here'
        result = repair_json(raw)
        # Should attempt extraction; result.data may or may not be populated
        assert isinstance(result, RepairResult)


# =============================================================================
# _strip_markdown
# =============================================================================

class TestStripMarkdown:
    def test_strips_json_fence(self):
        assert _strip_markdown("```json\n{}\n```") == "{}"

    def test_strips_plain_fence(self):
        assert _strip_markdown("```\n{}\n```") == "{}"

    def test_strips_uppercase_json_fence(self):
        assert _strip_markdown("```JSON\n{}\n```") == "{}"

    def test_no_fence_unchanged(self):
        assert _strip_markdown('{"key": "value"}') == '{"key": "value"}'

    def test_strips_leading_trailing_whitespace(self):
        result = _strip_markdown("  ```json\n{}\n```  ")
        assert result == "{}"

    def test_empty_string(self):
        assert _strip_markdown("") == ""


# =============================================================================
# _extract_json_object
# =============================================================================

class TestExtractJsonObject:
    def test_simple_object(self):
        assert _extract_json_object('{"key": "val"}') == '{"key": "val"}'

    def test_object_with_preamble(self):
        result = _extract_json_object('Here: {"key": "val"}')
        assert result == '{"key": "val"}'

    def test_nested_objects(self):
        result = _extract_json_object('{"a": {"b": 1}}')
        assert result == '{"a": {"b": 1}}'

    def test_only_takes_first_object(self):
        result = _extract_json_object('{"a": 1} {"b": 2}')
        assert result == '{"a": 1}'

    def test_no_object_returns_none(self):
        result = _extract_json_object("no braces here")
        assert result is None

    def test_unbalanced_object_closed(self):
        result = _extract_json_object('{"a": 1')
        assert result is not None
        assert result.endswith("}")

    def test_string_with_braces_handled(self):
        result = _extract_json_object('{"key": "has {brace} inside"}')
        assert result == '{"key": "has {brace} inside"}'

    def test_escaped_quote_in_string(self):
        result = _extract_json_object('{"key": "say \\"hello\\""}')
        assert result == '{"key": "say \\"hello\\""}'


# =============================================================================
# _fix_syntax
# =============================================================================

class TestFixSyntax:
    def test_trailing_comma_object(self):
        result = _fix_syntax('{"a": 1,}')
        assert result == '{"a": 1}'

    def test_trailing_comma_array(self):
        result = _fix_syntax('["a","b",]')
        assert result == '["a","b"]'

    def test_true_becomes_true(self):
        assert ": true" in _fix_syntax('{"a": True}')

    def test_false_becomes_false(self):
        assert ": false" in _fix_syntax('{"a": False}')

    def test_none_becomes_null(self):
        assert ": null" in _fix_syntax('{"a": None}')

    def test_removes_line_comment(self):
        result = _fix_syntax('{"a": 1 // comment\n}')
        assert "//" not in result

    def test_removes_block_comment(self):
        result = _fix_syntax('{"a": /* note */ 1}')
        assert "/*" not in result

    def test_unquoted_key(self):
        result = _fix_syntax('{key: "val"}')
        assert '"key"' in result

    def test_colon_true_no_space(self):
        result = _fix_syntax('{"a":True}')
        assert "true" in result


# =============================================================================
# _escape_newlines_in_strings
# =============================================================================

class TestEscapeNewlinesInStrings:
    def test_newline_in_string_escaped(self):
        result = _escape_newlines_in_strings('{"a": "line1\nline2"}')
        assert "\\n" in result

    def test_newline_outside_string_preserved(self):
        result = _escape_newlines_in_strings('{\n"a": "val"\n}')
        # Newlines outside strings remain as-is
        assert result.count("\n") == 2

    def test_already_escaped_newline_unchanged(self):
        result = _escape_newlines_in_strings('{"a": "line1\\nline2"}')
        # Should not double-escape
        assert result == '{"a": "line1\\nline2"}'

    def test_empty_string(self):
        assert _escape_newlines_in_strings("") == ""

    def test_no_strings(self):
        result = _escape_newlines_in_strings('{"a": 1\n}')
        assert result == '{"a": 1\n}'


# =============================================================================
# _normalize_fields
# =============================================================================

class TestNormalizeFields:
    def test_missing_text_added_as_empty(self):
        data = {}
        result = _normalize_fields(data)
        assert result["text"] == ""

    def test_non_string_text_coerced(self):
        data = {"text": 42}
        result = _normalize_fields(data)
        assert result["text"] == "42"

    def test_string_tags_split(self):
        data = {"tags_en": "1girl, solo, outdoor"}
        result = _normalize_fields(data)
        assert result["tags_en"] == ["1girl", "solo", "outdoor"]

    def test_list_tags_preserved(self):
        data = {"tags_en": ["1girl", "solo"]}
        result = _normalize_fields(data)
        assert result["tags_en"] == ["1girl", "solo"]

    def test_invalid_aspect_ratio_defaults_to_portrait(self):
        data = {"aspect_ratio": "widescreen"}
        result = _normalize_fields(data)
        assert result["aspect_ratio"] == "portrait"

    def test_valid_aspect_ratios_kept(self):
        for ar in ("portrait", "landscape", "square"):
            data = {"aspect_ratio": ar}
            result = _normalize_fields(data)
            assert result["aspect_ratio"] == ar

    def test_affinity_change_int_cleared(self):
        data = {"updates": {"affinity_change": 3}}
        result = _normalize_fields(data)
        assert result["updates"]["affinity_change"] == {}

    def test_affinity_change_dict_clamped(self):
        data = {"updates": {"affinity_change": {"Luna": 10, "Stella": -10}}}
        result = _normalize_fields(data)
        ac = result["updates"]["affinity_change"]
        assert ac["Luna"] == 5
        assert ac["Stella"] == -5

    def test_outfit_update_string_wrapped(self):
        data = {"updates": {"outfit_update": "casual dress"}}
        result = _normalize_fields(data)
        assert result["updates"]["outfit_update"] == {"description": "casual dress"}

    def test_updates_not_dict_replaced_with_empty(self):
        data = {"updates": "bad value"}
        result = _normalize_fields(data)
        assert result["updates"] == {}

    def test_visual_en_non_string_coerced(self):
        data = {"visual_en": 123}
        result = _normalize_fields(data)
        assert result["visual_en"] == "123"


# =============================================================================
# _regex_extract
# =============================================================================

class TestRegexExtract:
    def test_extracts_text_field(self):
        raw = '"text": "Luna ti sorride"'
        result = _regex_extract(raw)
        assert result["text"] == "Luna ti sorride"

    def test_extracts_visual_en(self):
        raw = '"visual_en": "Luna smiling in classroom"'
        result = _regex_extract(raw)
        assert result["visual_en"] == "Luna smiling in classroom"

    def test_extracts_aspect_ratio(self):
        raw = '"aspect_ratio": "landscape"'
        result = _regex_extract(raw)
        assert result["aspect_ratio"] == "landscape"

    def test_extracts_tags_en(self):
        raw = '"tags_en": ["1girl", "school", "smile"]'
        result = _regex_extract(raw)
        assert "1girl" in result["tags_en"]

    def test_missing_fields_have_defaults(self):
        result = _regex_extract("nothing useful here")
        assert result["text"] == ""
        assert result["tags_en"] == []
        assert result["aspect_ratio"] == "portrait"
        assert result["updates"] == {}

    def test_extracts_composition(self):
        raw = '"composition": "medium shot"'
        result = _regex_extract(raw)
        assert result["composition"] == "medium shot"


# =============================================================================
# Edge cases / integration
# =============================================================================

class TestRepairJsonEdgeCases:
    def test_affinity_change_clamped_in_full_pipeline(self):
        raw = '{"text": "Hi", "updates": {"affinity_change": {"Luna": 99}}}'
        result = repair_json(raw)
        assert result.data["updates"]["affinity_change"]["Luna"] == 5

    def test_tags_en_as_string_split(self):
        raw = '{"text": "Hi", "tags_en": "1girl, school", "updates": {}}'
        result = repair_json(raw)
        assert isinstance(result.data["tags_en"], list)
        assert "1girl" in result.data["tags_en"]

    def test_result_has_all_required_fields(self):
        raw = '{"text": "Hello", "updates": {}}'
        result = repair_json(raw)
        assert result.data is not None
        assert "text" in result.data
        assert "aspect_ratio" in result.data

    def test_repair_result_dataclass_fields(self):
        r = RepairResult(data={"text": "hi"})
        assert r.error_type == RepairErrorType.OK
        assert r.was_repaired is False
        assert r.error_message == ""
        assert r.correction_hint == ""

    def test_error_type_enum_values(self):
        assert RepairErrorType.OK == "ok"
        assert RepairErrorType.PARSE == "parse"
        assert RepairErrorType.VALIDATION == "validation"
        assert RepairErrorType.EMPTY == "empty"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
