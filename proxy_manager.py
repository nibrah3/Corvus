"""
proxy_manager.py - Manages IPRoyal proxy entries and IXBrowser profile creation.

Ensures each postgres profile gets an IXBrowser profile with a proxy matching
the profile's home country (UK profile -> GB proxy, etc.).

IPRoyal country targeting: append _country-XX to the password.
  HTTP port:   12321
  SOCKS5 port: 12323
"""
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

CB_DIR = Path(__file__).resolve().parent

# ── Country normalisation ─────────────────────────────────────────────────────

_ALIASES: dict[str, str] = {
    # UK
    "uk": "gb", "united kingdom": "gb", "england": "gb", "london": "gb",
    "britain": "gb", "great britain": "gb", "scotland": "gb", "wales": "gb",
    # US
    "us": "us", "usa": "us", "united states": "us", "america": "us",
    "remote": "us",   # default US for purely remote profiles
    # Philippines
    "ph": "ph", "philippines": "ph", "manila": "ph", "cebu": "ph",
    # Nigeria
    "ng": "ng", "nigeria": "ng", "lagos": "ng", "abuja": "ng",
    # Australia
    "au": "au", "australia": "au", "sydney": "au", "melbourne": "au",
    # Canada
    "ca": "ca", "canada": "ca", "toronto": "ca", "vancouver": "ca",
    # Germany
    "de": "de", "germany": "de", "berlin": "de",
    # India
    "in": "in", "india": "in", "bangalore": "in", "mumbai": "in",
}


def location_to_country(location: str) -> str:
    """
    Parse a freeform location string to an ISO-2 country code.
    Returns 'us' as default if unrecognised (most job sites are US-centric).
    """
    if not location:
        return "us"
    loc = location.lower().strip()
    # Direct match
    if loc in _ALIASES:
        return _ALIASES[loc]
    # Substring scan (longest alias first for specificity)
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if alias in loc:
            return _ALIASES[alias]
    # ISO-2 code embedded in string, e.g. "(US)" or "US)"
    m = re.search(r"\b([a-z]{2})\b", loc)
    if m and m.group(1) in _ALIASES:
        return _ALIASES[m.group(1)]
    return "us"


# ── IPRoyal proxy credentials ─────────────────────────────────────────────────

_IX_API = "http://127.0.0.1:53200/api/v2"

def _iproyal_creds() -> tuple[str, str]:
    """Return (username, base_password) from env."""
    url = os.environ.get("IPROYAL_PROXY_URL", "")
    if url:
        m = re.match(r"https?://([^:]+):([^@]+)@", url)
        if m:
            return m.group(1), m.group(2).split("_country")[0]
    return "8EDYlP4dRd06CJAc", "OcY1ARnMZVwkNTGV"


def iproyal_proxy_config(country: str, proxy_type: str = "socks5") -> dict:
    """Return raw proxy config dict for IXBrowser create_proxy call."""
    user, base_pass = _iproyal_creds()
    host = "geo.iproyal.com"
    port = "12323" if proxy_type == "socks5" else "12321"
    password = f"{base_pass}_country-{country.lower()}"
    return {
        "proxy_type": proxy_type,
        "proxy_host": host,
        "proxy_port": port,
        "proxy_user": user,
        "proxy_password": password,
        "country": country.upper(),
    }


# ── IXBrowser proxy management ────────────────────────────────────────────────

def _ix_post(endpoint: str, params: dict, timeout: int = 30) -> dict:
    import requests
    r = requests.post(f"{_IX_API}/{endpoint}", json=params, timeout=timeout)
    return r.json()


def ensure_ixbrowser_proxy(country: str, proxy_type: str = "socks5") -> int:
    """
    Find or create an IPRoyal proxy entry in IXBrowser for the given country.
    Returns the IXBrowser proxy id.
    """
    from ixbrowser_local_api import IXBrowserClient
    client = IXBrowserClient()
    proxies = client.get_proxy_list(limit=100) or []

    country_upper = country.upper()
    note_tag = f"IPRoyal-{country_upper}"

    # Find existing
    for px in proxies:
        if px.get("note") == note_tag:
            logger.info(f"Reusing proxy id={px['id']} for {country_upper}")
            return int(px["id"])

    # Create
    cfg = iproyal_proxy_config(country, proxy_type)
    logger.info(f"Creating IPRoyal {proxy_type.upper()} proxy for {country_upper}")
    proxy_id = client.create_proxy(
        cfg["proxy_type"],
        cfg["proxy_host"],
        cfg["proxy_port"],
        proxy_user=cfg["proxy_user"],
        proxy_password=cfg["proxy_password"],
        note=note_tag,
    )
    if not proxy_id:
        raise RuntimeError(f"Failed to create IXBrowser proxy for {country_upper}: {client.message}")
    logger.info(f"Created proxy id={proxy_id} for {country_upper}")
    return int(proxy_id)


def ensure_ixbrowser_profile(postgres_id: str, full_name: str, country: str,
                               proxy_type: str = "socks5") -> int:
    """
    Find or create an IXBrowser profile for the postgres profile, with the
    correct country proxy attached.

    Reads/writes the mapping from D:\\cb-core\\defaults.json.
    Returns the IXBrowser profile_id (int).
    """
    defaults_path = CB_DIR / "defaults.json"
    try:
        defaults = json.loads(defaults_path.read_text())
    except Exception:
        defaults = {}

    mapping = defaults.get("ixbrowser_profiles", {})

    # Check if mapping already exists and the profile is present in IXBrowser
    if postgres_id in mapping:
        ix_id = int(mapping[postgres_id])
        from ixbrowser_local_api import IXBrowserClient
        existing = IXBrowserClient().get_profile_list(limit=200) or []
        if any(int(p.get("profile_id", 0)) == ix_id for p in existing):
            logger.info(f"IXBrowser profile for {postgres_id} exists: id={ix_id}")
            return ix_id
        # Profile was deleted — recreate
        logger.warning(f"Profile id={ix_id} no longer exists, recreating")

    proxy_id = ensure_ixbrowser_proxy(country, proxy_type)

    from ixbrowser_local_api import IXBrowserClient, entities
    client = IXBrowserClient()

    # Create profile (name + start page only — proxy set via separate call)
    profile = entities.Profile()
    profile.name = full_name
    profile.set_custom_page("https://google.com")
    result = client.create_profile(profile)
    if result is None:
        raise RuntimeError(f"IXBrowser create_profile failed for {postgres_id}: {client.message}")

    ix_id = int(result)

    # Now attach proxy using the method that actually works
    cfg = iproyal_proxy_config(country, proxy_type)
    r = client.update_profile_to_custom_proxy_mode(
        profile_id=ix_id,
        proxy_type=cfg["proxy_type"],
        proxy_ip=cfg["proxy_host"],
        proxy_port=cfg["proxy_port"],
        proxy_user=cfg["proxy_user"],
        proxy_password=cfg["proxy_password"],
    )
    if r != "success":
        logger.warning(f"Proxy attach returned: {r!r} (message: {client.message})")

    logger.info(f"Created IXBrowser profile id={ix_id} name={full_name!r} country={country.upper()} proxy={proxy_type}")

    # Persist mapping
    if "ixbrowser_profiles" not in defaults:
        defaults["ixbrowser_profiles"] = {}
    defaults["ixbrowser_profiles"][postgres_id] = ix_id
    defaults_path.write_text(json.dumps(defaults, indent=4))

    return ix_id
