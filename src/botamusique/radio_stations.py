"""Persistent radio station management.

Radio stations used to live only in the ``[radio]`` section of the
configuration file, which meant they could not be changed at runtime.
This module merges two sources:

* ``[radio]`` config entries (read-only, ``source == "config"``)
* ``radio`` section of the settings DB (read-write via web UI or chat,
  ``source == "db"``)

DB entries win over config entries with the same (case-insensitive) name,
so a station from the config file can be overridden at runtime.

DB value format is JSON ``{"name": <display name>, "url": <stream url>}``.
Plain URL strings are also accepted for backwards compatibility /
manual edits.
"""
import html
import json
import logging
import re
from configparser import ConfigParser
from typing import Any
from urllib.parse import urlsplit, urlunsplit

log = logging.getLogger("bot")

DB_SECTION = "radio"

NAME_MAX_LEN = 64
# Control characters and angle brackets would break Mumble chat HTML
# rendering (station names are embedded raw in <b>...</b> messages).
# Everything else — including unicode letters like äöü, spaces and
# punctuation — is allowed.
_FORBIDDEN_NAME_CHARS_RE = re.compile(r"[\x00-\x1f\x7f<>]")


class RadioStationError(ValueError):
    pass


def validate_name(name: str) -> str:
    clean = (name or "").strip()
    if not clean or len(clean) > NAME_MAX_LEN:
        raise RadioStationError(
            "Invalid station name. Use 1-64 characters."
        )
    if _FORBIDDEN_NAME_CHARS_RE.search(clean):
        raise RadioStationError(
            "Invalid station name. Characters '<', '>' and control characters are not allowed."
        )
    return clean


def _extract_url(raw: str) -> str:
    """Same extraction as util.get_url_from_input, without the heavy import."""
    try:
        from botamusique import util as _util

        return _util.get_url_from_input(raw)
    except ImportError:
        pass
    string = (raw or "").strip()
    if not (string.startswith("http") or string.startswith("HTTP")):
        res = re.search('href="(.+?)"', string, flags=re.IGNORECASE)
        if res:
            string = res.group(1)
        else:
            return ""
    match = re.search(r"https?://\S+", string, flags=re.IGNORECASE)
    if not match:
        return ""
    url = html.unescape(match[0])
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if not parts.hostname:
        return ""
    # Only scheme and host are case-insensitive (RFC 3986). Path, query
    # and fragment must keep their case (mirrors util.get_url_from_input).
    host = parts.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parts.port:
        netloc += f":{parts.port}"
    if parts.username:
        userinfo = parts.username
        if parts.password:
            userinfo += f":{parts.password}"
        netloc = f"{userinfo}@{netloc}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, parts.query, parts.fragment))


def validate_url(url: str) -> str:
    normalized = _extract_url((url or "").strip())
    if not normalized:
        raise RadioStationError("Invalid URL.")
    try:
        from botamusique import util as _util

        if _util.is_ssrf_blocked_url(normalized):
            raise RadioStationError("URL targets a local or reserved address.")
    except ImportError:
        pass
    return normalized


def parse_config_value(raw: str) -> tuple[str, str]:
    """Split a ``[radio]`` config value into (url, comment).

    Config format is ``<url> ["comment"]``, e.g.::
        jazz = http://example.com/stream "Jazz Yeah !"
    """
    raw = (raw or "").strip()
    if not raw:
        return "", ""
    parts = raw.split(maxsplit=1)
    url = parts[0]
    comment = ""
    if len(parts) == 2:
        comment = parts[1].strip()
        if len(comment) >= 2 and comment[0] == '"' and comment[-1] == '"':
            comment = comment[1:-1]
        elif len(comment) >= 2 and comment[0] == "'" and comment[-1] == "'":
            comment = comment[1:-1]
    return url, comment


def _decode_db_value(option: str, value: str) -> tuple[str, str]:
    """Return (display_name, url) for a raw DB value."""
    try:
        data = json.loads(value)
        if isinstance(data, dict) and data.get("url"):
            name = str(data.get("name") or option)
            return name, str(data["url"])
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    # Fallback: plain URL string (possibly with trailing comment like config).
    url, _comment = parse_config_value(value)
    return option, url


def _encode_db_value(name: str, url: str) -> str:
    return json.dumps({"name": name, "url": url})


def get_radio_stations(config: ConfigParser, db: Any) -> list[dict[str, str]]:
    """Return merged radio stations sorted by name.

    Each entry is ``{"name": ..., "url": ..., "comment": ...,
    "source": "config"|"db"}``. DB entries override config entries with the
    same case-insensitive name.
    """
    stations: dict[str, dict[str, str]] = {}

    if config.has_section("radio"):
        for option, raw in config.items("radio"):
            url, comment = parse_config_value(raw)
            if not url:
                continue
            # ConfigParser lowercases option names; keep the raw option as
            # display name (config has no separate display name).
            stations[option.lower()] = {
                "name": option,
                "url": url,
                "comment": comment,
                "source": "config",
            }

    try:
        db_items = db.items(DB_SECTION)
    except Exception:
        db_items = []
    for option, value in db_items or []:
        name, url = _decode_db_value(option, value)
        if not url:
            continue
        stations[option.lower()] = {
            "name": name,
            "url": url,
            "comment": "",
            "source": "db",
        }

    return sorted(stations.values(), key=lambda s: s["name"].lower())


def resolve_radio_url(name: str, config: ConfigParser, db: Any) -> str | None:
    """Case-insensitive lookup of a station name. Returns URL or None."""
    station = resolve_radio_station(name, config, db)
    return station["url"] if station else None


def resolve_radio_station(name: str, config: ConfigParser, db: Any) -> dict[str, str] | None:
    """Case-insensitive lookup of a station. Returns the station dict or None."""
    if not name:
        return None
    key = name.strip().lower()
    for station in get_radio_stations(config, db):
        if station["name"].lower() == key:
            return station
    return None


def add_radio_station(db: Any, name: str, url: str) -> dict[str, str]:
    """Persist a station in the settings DB. Returns the stored entry."""
    clean_name = validate_name(name)
    clean_url = validate_url(url)
    key = clean_name.lower()

    # Prevent shadowing confusion? No — DB intentionally overrides config.
    db.set(DB_SECTION, key, _encode_db_value(clean_name, clean_url))
    log.info(f"radio: saved station '{clean_name}' -> {clean_url}")
    return {"name": clean_name, "url": clean_url, "comment": "", "source": "db"}


def delete_radio_station(db: Any, name: str) -> bool:
    """Delete a DB-backed station. Returns True if something was removed."""
    if not name:
        return False
    key = name.strip().lower()
    if hasattr(db, "has_option") and not db.has_option(DB_SECTION, key):
        return False
    db.remove_option(DB_SECTION, key)
    log.info(f"radio: deleted station '{name}'")
    return True


def rename_radio_station(db: Any, old_name: str, new_name: str, new_url: str | None = None) -> dict[str, str]:
    """Rename (and optionally re-URL) a DB-backed station.

    Lookup of ``old_name`` is case-insensitive. If ``new_url`` is None or
    empty, the existing URL is kept. Returns the stored entry.
    """
    old_key = (old_name or "").strip().lower()
    if not old_key:
        raise RadioStationError("Original station name is required.")
    clean_new_name = validate_name(new_name)
    new_key = clean_new_name.lower()

    if hasattr(db, "has_option") and not db.has_option(DB_SECTION, old_key):
        raise RadioStationError(f"Station '{(old_name or '').strip()}' not found.")
    if new_key != old_key and hasattr(db, "has_option") and db.has_option(DB_SECTION, new_key):
        raise RadioStationError(f"Station '{clean_new_name}' already exists.")

    # Read the current entry to preserve the URL when none is given.
    old_url = ""
    try:
        for _option, _value in (db.items(DB_SECTION) or []):
            if _option.lower() == old_key:
                _display, old_url = _decode_db_value(_option, _value)
                break
    except Exception:
        old_url = ""
    if not old_url:
        raise RadioStationError(f"Station '{(old_name or '').strip()}' not found.")

    clean_url = validate_url(new_url) if (new_url or "").strip() else old_url

    if new_key != old_key:
        db.remove_option(DB_SECTION, old_key)
    db.set(DB_SECTION, new_key, _encode_db_value(clean_new_name, clean_url))
    log.info(f"radio: renamed station '{old_name}' -> '{clean_new_name}' ({clean_url})")
    return {"name": clean_new_name, "url": clean_url, "comment": "", "source": "db"}
