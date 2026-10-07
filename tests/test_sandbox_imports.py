"""Tests for sandbox import rules."""

from agent_smith.sandbox import _is_import_allowed


def test_exact_import_is_allowed():
    assert _is_import_allowed("math", ["math"]) is True


def test_different_import_is_denied():
    assert _is_import_allowed("os", ["math"]) is False


def test_submodule_is_allowed_with_wildcard():
    assert _is_import_allowed(
        "collections.abc",
        ["collections.*"],
    ) is True


def test_root_module_is_not_allowed_by_wildcard():
    assert _is_import_allowed(
        "collections",
        ["collections.*"],
    ) is False


def test_similar_prefix_is_not_allowed():
    assert _is_import_allowed(
        "collections_extra.abc",
        ["collections.*"],
    ) is False


def test_empty_patterns_denies_import():
    assert _is_import_allowed("math", []) is False


def test_any_matching_pattern_allows_import():
    assert _is_import_allowed(
        "math",
        ["json", "collections.*", "math"],
    ) is True