"""Tests for persistent radio stations (radio_stations.py)."""
import json
import sqlite3
from configparser import ConfigParser

import pytest

from botamusique import radio_stations
from botamusique.database import SettingsDatabase, DatabaseMigration
from botamusique.database import MusicDatabase


def _config_with_radio(entries=None):
    config = ConfigParser(interpolation=None, allow_no_value=True)
    config.add_section("radio")
    for name, value in (entries or {}).items():
        config.set("radio", name, value)
    return config


def _settings_db(tmp_path):
    settings_path = str(tmp_path / "settings.db")
    music_path = str(tmp_path / "music.db")
    settings_db = SettingsDatabase(settings_path)
    music_db = MusicDatabase(music_path)
    DatabaseMigration(settings_db, music_db).migrate()
    return settings_db


class FakeDb:
    """Minimal settings-DB stub for merge tests."""

    def __init__(self, items=None):
        self._items = items or []
        self.set_calls = []
        self.removed = []

    def items(self, section):
        assert section == "radio"
        return list(self._items)

    def has_option(self, section, option):
        return any(o == option for o, _ in self._items)

    def set(self, section, option, value):
        self.set_calls.append((section, option, value))
        self._items = [(o, v) for o, v in self._items if o != option]
        self._items.append((option, value))

    def remove_option(self, section, option):
        self.removed.append((section, option))
        self._items = [(o, v) for o, v in self._items if o != option]


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def test_validate_name_ok():
    assert radio_stations.validate_name("jazz") == "jazz"
    assert radio_stations.validate_name("  Rock-88_x ") == "Rock-88_x"
    # Unicode, spaces and punctuation are allowed (web UI editable names).
    assert radio_stations.validate_name("Jazz Yeah !") == "Jazz Yeah !"
    assert radio_stations.validate_name("Bärmix Öl-Radio") == "Bärmix Öl-Radio"
    assert radio_stations.validate_name("café") == "café"
    assert radio_stations.validate_name("dot.name") == "dot.name"
    assert radio_stations.validate_name("has space") == "has space"
    assert radio_stations.validate_name("semi;colon") == "semi;colon"


@pytest.mark.parametrize("bad", ["", "   ", "a" * 65, "bad<name>", "a>b", "line\nbreak", "tab\there"])
def test_validate_name_rejects(bad):
    with pytest.raises(radio_stations.RadioStationError):
        radio_stations.validate_name(bad)


def test_validate_url_ok():
    url = radio_stations.validate_url("http://example.com/stream")
    assert url.startswith("http://")


@pytest.mark.parametrize("bad", ["", "not a url", "ftp://example.com/x"])
def test_validate_url_rejects(bad):
    with pytest.raises(radio_stations.RadioStationError):
        radio_stations.validate_url(bad)


def test_validate_url_extracts_from_anchor():
    url = radio_stations.validate_url('<a href="http://example.com/s">x</a>')
    assert url.startswith("http://example.com")


def test_validate_url_preserves_path_case():
    # Regression test: Icecast mount paths can be case-sensitive.
    # .../radio/YleX/... must not become .../radio/ylex/... (was 404).
    url = radio_stations.validate_url("https://icecast.live.yle.fi/radio/YleX/icecast.audio")
    assert url == "https://icecast.live.yle.fi/radio/YleX/icecast.audio"


def test_validate_url_lowercases_only_scheme_and_host():
    url = radio_stations.validate_url("HTTP://EXAMPLE.COM/Path/To/STREAM?Token=AbC")
    assert url == "http://example.com/Path/To/STREAM?Token=AbC"


def test_validate_url_unescapes_entities():
    url = radio_stations.validate_url("https://example.com/?a=1&amp;b=2")
    assert url == "https://example.com/?a=1&b=2"


def test_validate_url_preserves_port():
    url = radio_stations.validate_url("http://example.com:8000/Stream")
    assert url == "http://example.com:8000/Stream"


# ---------------------------------------------------------------------------
# config parsing
# ---------------------------------------------------------------------------

def test_parse_config_value_url_only():
    assert radio_stations.parse_config_value("http://example.com/s") == ("http://example.com/s", "")


def test_parse_config_value_with_double_quoted_comment():
    url, comment = radio_stations.parse_config_value('http://example.com/s "Jazz Yeah !"')
    assert url == "http://example.com/s"
    assert comment == "Jazz Yeah !"


def test_parse_config_value_with_single_quoted_comment():
    url, comment = radio_stations.parse_config_value("http://example.com/s 'hi'")
    assert (url, comment) == ("http://example.com/s", "hi")


def test_parse_config_value_empty():
    assert radio_stations.parse_config_value("") == ("", "")


# ---------------------------------------------------------------------------
# merging
# ---------------------------------------------------------------------------

def test_get_stations_merges_config_and_db():
    config = _config_with_radio({"jazz": 'http://jazz.example/s "Jazz"'})
    db = FakeDb([("rock", json.dumps({"name": "Rock", "url": "http://rock.example/s"}))])
    stations = radio_stations.get_radio_stations(config, db)
    by_name = {s["name"]: s for s in stations}
    assert by_name["jazz"]["source"] == "config"
    assert by_name["jazz"]["comment"] == "Jazz"
    assert by_name["Rock"]["source"] == "db"
    assert by_name["Rock"]["url"] == "http://rock.example/s"


def test_db_overrides_config_with_same_name():
    config = _config_with_radio({"jazz": "http://old.example/s"})
    db = FakeDb([("jazz", json.dumps({"name": "Jazz", "url": "http://new.example/s"}))])
    stations = radio_stations.get_radio_stations(config, db)
    assert len(stations) == 1
    assert stations[0]["url"] == "http://new.example/s"
    assert stations[0]["source"] == "db"


def test_db_plain_url_value_supported():
    config = _config_with_radio({})
    db = FakeDb([("plain", "http://plain.example/s")])
    stations = radio_stations.get_radio_stations(config, db)
    assert stations[0]["url"] == "http://plain.example/s"


def test_stations_sorted_case_insensitively():
    config = _config_with_radio({
        "zebra": "http://z.example/",
        "apple": "http://a.example/",
        # NB: ConfigParser lowercases option names, so config-backed
        # display names are lowercase; DB entries preserve case.
        "mango": "http://m.example/",
    })
    stations = radio_stations.get_radio_stations(config, FakeDb())
    assert [s["name"] for s in stations] == ["apple", "mango", "zebra"]


def test_resolve_is_case_insensitive():
    config = _config_with_radio({"Jazz": "http://jazz.example/s"})
    assert radio_stations.resolve_radio_url("jazz", config, FakeDb()) == "http://jazz.example/s"
    assert radio_stations.resolve_radio_url("JAZZ", config, FakeDb()) == "http://jazz.example/s"
    assert radio_stations.resolve_radio_url("missing", config, FakeDb()) is None


# ---------------------------------------------------------------------------
# add / delete against a real settings DB
# ---------------------------------------------------------------------------

def test_add_and_resolve_roundtrip(tmp_path):
    config = _config_with_radio({})
    db = _settings_db(tmp_path)
    station = radio_stations.add_radio_station(db, "MyStation", "http://example.com/stream")
    assert station["name"] == "MyStation"
    assert radio_stations.resolve_radio_url("mystation", config, db) == station["url"]
    # Stored names preserve case for display, lookup is case-insensitive.
    stations = radio_stations.get_radio_stations(config, db)
    assert stations[0]["name"] == "MyStation"


def test_add_persists_across_reopen(tmp_path):
    db = _settings_db(tmp_path)
    radio_stations.add_radio_station(db, "jazz", "http://example.com/jazz")
    reopened = SettingsDatabase(db.db_path)
    config = _config_with_radio({})
    assert radio_stations.resolve_radio_url("jazz", config, reopened) == "http://example.com/jazz"


def test_delete_removes_station(tmp_path):
    config = _config_with_radio({})
    db = _settings_db(tmp_path)
    radio_stations.add_radio_station(db, "jazz", "http://example.com/jazz")
    assert radio_stations.delete_radio_station(db, "JAZZ") is True
    assert radio_stations.resolve_radio_url("jazz", config, db) is None


def test_delete_missing_returns_false(tmp_path):
    db = _settings_db(tmp_path)
    assert radio_stations.delete_radio_station(db, "nope") is False
    assert radio_stations.delete_radio_station(db, "") is False


def test_add_invalid_raises_and_stores_nothing(tmp_path):
    db = _settings_db(tmp_path)
    with pytest.raises(radio_stations.RadioStationError):
        radio_stations.add_radio_station(db, "bad<name>", "http://example.com/s")
    with pytest.raises(radio_stations.RadioStationError):
        radio_stations.add_radio_station(db, "good", "not a url")
    assert radio_stations.get_radio_stations(_config_with_radio({}), db) == []


def test_add_unicode_name_roundtrip(tmp_path):
    config = _config_with_radio({})
    db = _settings_db(tmp_path)
    station = radio_stations.add_radio_station(db, "Bärmix Öl-Radio", "http://example.com/stream")
    assert station["name"] == "Bärmix Öl-Radio"
    assert radio_stations.resolve_radio_url("bärmix öl-radio", config, db) == station["url"]
    stations = radio_stations.get_radio_stations(config, db)
    assert stations[0]["name"] == "Bärmix Öl-Radio"


def test_rename_ok(tmp_path):
    config = _config_with_radio({})
    db = _settings_db(tmp_path)
    radio_stations.add_radio_station(db, "jazz", "http://example.com/jazz")
    station = radio_stations.rename_radio_station(db, "jazz", "Bärmix Öl-Radio")
    assert station["name"] == "Bärmix Öl-Radio"
    assert station["url"] == "http://example.com/jazz"
    assert radio_stations.resolve_radio_url("JAZZ", config, db) is None
    assert radio_stations.resolve_radio_url("bärmix öl-radio", config, db) == "http://example.com/jazz"


def test_rename_with_new_url(tmp_path):
    config = _config_with_radio({})
    db = _settings_db(tmp_path)
    radio_stations.add_radio_station(db, "jazz", "http://example.com/jazz")
    station = radio_stations.rename_radio_station(db, "JAZZ", "Jazz 24", "http://example.com/jazz24")
    assert station["name"] == "Jazz 24"
    assert station["url"] == "http://example.com/jazz24"
    assert radio_stations.resolve_radio_url("jazz 24", config, db) == "http://example.com/jazz24"


def test_rename_missing_raises(tmp_path):
    db = _settings_db(tmp_path)
    with pytest.raises(radio_stations.RadioStationError):
        radio_stations.rename_radio_station(db, "nope", "new name")


def test_rename_duplicate_raises(tmp_path):
    db = _settings_db(tmp_path)
    radio_stations.add_radio_station(db, "one", "http://example.com/1")
    radio_stations.add_radio_station(db, "two", "http://example.com/2")
    with pytest.raises(radio_stations.RadioStationError):
        radio_stations.rename_radio_station(db, "one", "TWO")


def test_resolve_station_returns_display_name(tmp_path):
    config = _config_with_radio({})
    db = _settings_db(tmp_path)
    radio_stations.add_radio_station(db, "MyStation", "http://example.com/stream")
    station = radio_stations.resolve_radio_station("mystation", config, db)
    assert station is not None
    assert station["name"] == "MyStation"
    assert station["url"] == "http://example.com/stream"
    assert radio_stations.resolve_radio_station("missing", config, db) is None
