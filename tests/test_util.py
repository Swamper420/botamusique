"""Tests for util.get_url_from_input URL normalization."""
import pytest

from botamusique import util


def test_preserves_case_sensitive_path():
    # Regression test: Icecast mount paths can be case-sensitive.
    # .../radio/YleX/... must not become .../radio/ylex/... (was 404).
    assert util.get_url_from_input("https://icecast.live.yle.fi/radio/YleX/icecast.audio") == \
        "https://icecast.live.yle.fi/radio/YleX/icecast.audio"


def test_lowercases_only_scheme_and_host():
    assert util.get_url_from_input("HTTP://EXAMPLE.COM/Path/To/STREAM?Token=AbC") == \
        "http://example.com/Path/To/STREAM?Token=AbC"


def test_extracts_from_anchor_and_preserves_case():
    assert util.get_url_from_input('<a href="https://example.com/Mixed/Case">x</a>') == \
        "https://example.com/Mixed/Case"


def test_unescapes_html_entities():
    assert util.get_url_from_input("https://example.com/?a=1&amp;b=2") == \
        "https://example.com/?a=1&b=2"


def test_preserves_port():
    assert util.get_url_from_input("http://example.com:8000/Stream") == \
        "http://example.com:8000/Stream"


@pytest.mark.parametrize("bad", ["", "not a url", "ftp://example.com/x"])
def test_rejects_non_http(bad):
    assert util.get_url_from_input(bad) == ""
