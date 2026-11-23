"""
data.py - fetching open data, with a cache.

Two sources, both open, both keyless:

  * Queensland Government charging stations, via the data.qld.gov.au CKAN
    datastore API. Returns clean JSON - use this rather than the published CSV,
    which contains embedded newlines inside quoted fields.
  * OpenStreetMap place lookup, via Nominatim (ODbL). The specification requires openly
    licensed sources, which rules out Google Maps geocoding.

Everything is cached on disk. That is not an optimisation: a tool call must
return within 45 seconds, and Nominatim's public endpoint allows only one
request per second. Fifty-five agents calling it live would get the cohort
blocked.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any
from datetime import datetime
import csv
import io
import zipfile
TRANSLINK_PERFORMANCE_LICENCE = "Translink monthly performance data via data.qld.gov.au, CC BY 3.0"
import httpx

CACHE_DIR = Path(__file__).with_name(".cache")
CACHE_DIR.mkdir(exist_ok=True)

# data.qld.gov.au - "Find a charging station - Electric vehicle", CC BY 4.0
QLD_API = "https://www.data.qld.gov.au/api/3/action/datastore_search"
QLD_RESOURCE_ID = "a34d4b5f-8e3c-4995-8950-2e84fd7bb4d5"
QLD_LICENCE = "Queensland Government (TMR) via data.qld.gov.au, CC BY 4.0"

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSM_LICENCE = "© OpenStreetMap contributors, ODbL 1.0"
USER_AGENT = "REIT7820-SMAC-agent/0.1 (UQ teaching project)"

_nominatim_lock = threading.Lock()
_nominatim_last = 0.0

def _cache_path(key: str) -> Path:
    """Where a given cache key lives on disk. Shared by _cached() and is_cached()
    so the two can never disagree about which file a key maps to."""
    return CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest()[:16] + ".json")


def is_cached(key: str, ttl_seconds: int) -> bool:
    """True if THIS SPECIFIC key has a fresh cache file, without fetching.

    Use this - not "does any *.json file exist in the cache dir" - to decide
    whether a particular dataset needs fetching. The cache directory is shared
    by every dataset, so checking "any file exists" tells you nothing about
    whether *this* dataset's own data has ever been fetched: the first dataset
    to populate the directory would make every later dataset look "cached"
    even though its own fetch never ran.
    """
    path = _cache_path(key)
    return path.exists() and time.time() - path.stat().st_mtime < ttl_seconds

def _cached(key: str, ttl_seconds: int, fetch) -> Any:
    """Return cached JSON if fresh, else fetch and store. Falls back to a stale
    copy if the fetch fails - a publisher outage must not fail your tool call."""
    path = CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest()[:16] + ".json")
    if path.exists() and time.time() - path.stat().st_mtime < ttl_seconds:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        payload = fetch()
        path.write_text(json.dumps(payload), encoding="utf-8")
        return payload
    except Exception:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise


def charging_stations(ttl_seconds: int = 6 * 3600) -> list[dict]:
    """All Queensland Electric Super Highway stations, as clean records.

    Fields kept: name, lat, lon, address, host, status, onward_stations.
    The source publishes a `Charging plugs available` column that is empty for
    every row, so it is left out rather than reported as unknown
    detail your caller might mistake for real.
    """
    def fetch():
        response = httpx.get(
            QLD_API,
            params={"resource_id": QLD_RESOURCE_ID, "limit": 1000},
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()["result"]["records"]

    stations = []
    for row in _cached(f"qld:{QLD_RESOURCE_ID}", ttl_seconds, fetch):
        try:
            lat, lon = float(row["Latitude"]), float(row["Longitude"])
        except (KeyError, TypeError, ValueError):
            continue  # skip malformed rows rather than crashing
        stations.append(
            {
                "name": str(row.get("Location Name", "")).strip(),
                "lat": lat,
                "lon": lon,
                "address": " ".join(str(row.get("Address", "")).split()),
                "host": str(row.get("Host", "")).strip() or None,
                "status": str(row.get("Status", "")).strip() or None,
                "onward_stations": " ".join(str(row.get("Nearest QESH charging station", "")).split()) or None,
            }
        )
    return stations


def geocode(place: str, ttl_seconds: int = 30 * 24 * 3600) -> dict | None:
    """Look up a place name on OpenStreetMap. Returns None if there is no match.

    Cached for a month and rate-limited to Nominatim's published 1 req/sec.
    """
    query = (place or "").strip()
    if not query:
        return None

    def fetch():
        global _nominatim_last
        with _nominatim_lock:
            wait = 1.1 - (time.time() - _nominatim_last)
            if wait > 0:
                time.sleep(wait)
            _nominatim_last = time.time()
        response = httpx.get(
            NOMINATIM,
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "au"},
            headers={"User-Agent": USER_AGENT},
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()

    results = _cached(f"osm:{query.lower()}", ttl_seconds, fetch)
    if not results:
        return None
    hit = results[0]
    return {
        "lat": float(hit["lat"]),
        "lon": float(hit["lon"]),
        "matched_name": hit.get("display_name"),
        # building vs suburb vs administrative area - precision varies hugely,
        # and the caller deserves to know which it got.
        "match_kind": f"{hit.get('class', '?')}/{hit.get('type', '?')}",
    }


# Translink GTFS, used by the public transport agent.
# data.qld.gov.au dataset: general-transit-feed-specification-gtfs-translink
GTFS_URL = "https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip"
GTFS_LICENCE = "Translink SEQ GTFS via data.qld.gov.au, CC BY 4.0"

_GTFS_CACHE: dict[str, list[dict]] = {}


def gtfs_table(filename: str, ttl_seconds: int = 24 * 3600) -> list[dict]:
    """Read one file out of the SEQ GTFS archive.

    The archive is 28 MB compressed. Only ask for the small members:
    stops.txt is 1.6 MB and routes.txt is 0.13 MB, but **stop_times.txt is
    164 MB uncompressed** and must never be parsed inside a tool call - you
    would blow the 45-second budget many times over. If you need
    timetables, index that file once at startup into your own structure.
    """
    if filename in _GTFS_CACHE:
        return _GTFS_CACHE[filename]

    archive = CACHE_DIR / "seq_gtfs.zip"
    if not archive.exists() or time.time() - archive.stat().st_mtime > ttl_seconds:
        with httpx.stream("GET", GTFS_URL, timeout=180.0, follow_redirects=True) as response:
            response.raise_for_status()
            with archive.open("wb") as fh:
                for chunk in response.iter_bytes():
                    fh.write(chunk)

    with zipfile.ZipFile(archive) as z, z.open(filename) as member:
        rows = list(csv.DictReader(io.TextIOWrapper(member, encoding="utf-8-sig")))

    # GTFS values arrive space-padded in this feed: ' -27.467834'.
    _GTFS_CACHE[filename] = [{k: (v.strip() if isinstance(v, str) else v) for k, v in r.items()} for r in rows]
    return _GTFS_CACHE[filename]




# ---------------------------------------------------------------------------
# Translink monthly performance data, used by the policy agent.
# data.qld.gov.au dataset: translink-monthly-performance-data
# All five resources below live in that one CKAN dataset and share the same
# QLD_API / datastore_search endpoint as charging_stations() above.
# ---------------------------------------------------------------------------
# Translink patronage, used by the policy agent.
PATRONAGE_SEQ_ID = "c49df919-5c0d-4bd2-9e43-776509b95ef6"
PATRONAGE_LICENCE = "Translink monthly performance data via data.qld.gov.au, CC BY 3.0"

CITYTRAIN_PUNCTUALITY_ID = "d6b9ce31-dd07-4ea2-ac1a-848fa638cd90"
BUS_PUNCTUALITY_ID = "e12aa967-e3ca-491f-9b70-60bbea3f296e"
TRAM_PUNCTUALITY_ID = "549c7dde-ab85-45ba-8b56-ead8f2f31129"
COMPLAINTS_ID = "c4a1cf64-aca9-4447-96eb-55baf5bee31e"
CUSTOMER_EXPERIENCE_OVERALL_ID = "c1984b8b-3822-41b0-bf90-b18b4a930072"
TRANSLINK_PERFORMANCE_LICENCE = "Translink monthly performance data via data.qld.gov.au, CC BY 3.0"


def _fetch_translink_resource(resource_id: str, ttl_seconds: int) -> list[dict]:
    """Shared fetch for any resource in the Translink monthly performance
    dataset - all five below are datastore_search calls that differ only in
    resource_id, so the HTTP part is written once here."""
    def fetch():
        response = httpx.get(
            QLD_API,
            params={"resource_id": resource_id, "limit": 5000},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()["result"]["records"]

    return _cached(f"translink:{resource_id}", ttl_seconds, fetch)


def patronage_seq(ttl_seconds: int = 24 * 3600) -> list[dict]:
    """Monthly SEQ passenger trips by mode.

    Returns records with `month` (ISO 8601 date), `mode` and `trips` (int).
    The published fields are 'Month-Year' ("Dec-2023") and 'Passenger trips'
    (a string) - both normalised here so tools never repeat the parsing.
    """
    records = []
    for row in _fetch_translink_resource(PATRONAGE_SEQ_ID, ttl_seconds):
        try:
            month = datetime.strptime(str(row["Month-Year"]).strip(), "%b-%Y")
            trips = int(float(row["Passenger trips"]))
        except (KeyError, TypeError, ValueError):
            continue  # skip malformed rows rather than crashing
        records.append({"month": month.strftime("%Y-%m-01"), "mode": str(row["Mode"]).strip(), "trips": trips})
    return sorted(records, key=lambda r: (r["month"], r["mode"]))


def _parse_monthly_punctuality(resource_id: str, ttl_seconds: int) -> list[dict]:
    """Shared parser for the three punctuality resources (Citytrain/Bus/Tram).

    All three publish one row per month with a 'Month-Year' column
    ("Dec-2023") plus one or more numeric columns. We keep only the
    on-time-running figure - reliability is dropped project-wide, since
    Bus never published one and the project decided to drop it everywhere
    for a consistent signal set.

    Returns records with `month` (ISO date, first of month) and
    `on_time_running` (float, 0-100 scale as published).
    """
    records = []
    for row in _fetch_translink_resource(resource_id, ttl_seconds):
        try:
            month = datetime.strptime(str(row["Month-Year"]).strip(), "%b-%Y")
        except (KeyError, TypeError, ValueError):
            continue  # skip malformed rows rather than crashing

        on_time_col = next(
            (k for k in row if "on-time" in k.lower() or "on time" in k.lower()
             or ("punctual" in k.lower() and "reliab" not in k.lower())),
            None,
        )
        if on_time_col is None:
            continue  # publisher changed schema - skip rather than guess

        try:
            on_time_running = float(row[on_time_col])
        except (TypeError, ValueError):
            continue

        records.append({
            "month": month.strftime("%Y-%m-01"),
            "on_time_running": on_time_running,
        })
    return sorted(records, key=lambda r: r["month"])


def citytrain_punctuality(ttl_seconds: int = 24 * 3600) -> list[dict]:
    """Monthly Citytrain on-time running (combined peaks), reliability dropped."""
    return _parse_monthly_punctuality(CITYTRAIN_PUNCTUALITY_ID, ttl_seconds)


def bus_punctuality(ttl_seconds: int = 24 * 3600) -> list[dict]:
    """Monthly SEQ Bus on-time running (overall). Bus never published a
    reliability figure, so this metric was always alone here."""
    return _parse_monthly_punctuality(BUS_PUNCTUALITY_ID, ttl_seconds)


def tram_punctuality(ttl_seconds: int = 24 * 3600) -> list[dict]:
    """Monthly SEQ Tram on-time running (overall), reliability dropped.

    VERIFY: the on-time-running column name is matched by substring, the
    same as Citytrain/Bus above - it wasn't checked against a live fetch.
    If this returns an empty list, print a raw record from
    _fetch_translink_resource(TRAM_PUNCTUALITY_ID, ...) and adjust the
    substring match in _parse_monthly_punctuality.
    """
    return _parse_monthly_punctuality(TRAM_PUNCTUALITY_ID, ttl_seconds)




def _norm_key(k: str) -> str:
    """Collapse whitespace/newlines and lower-case, so column headers that
    arrive with embedded newlines (see below) can still be matched."""
    return " ".join(str(k).split()).lower()

def complaints(ttl_seconds: int = 24 * 3600) -> list[dict]:
    def fetch():
        response = httpx.get(
            QLD_API,
            params={"resource_id": COMPLAINTS_ID, "limit": 1000},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()["result"]["records"]

    from datetime import datetime

    records = []
    for row in _cached(f"complaints:{COMPLAINTS_ID}", ttl_seconds, fetch):
        norm = {_norm_key(k): v for k, v in row.items()}
        try:
            week = datetime.strptime(
                str(norm["week ending"]).strip(), "%a, %d %b %Y %I:%M %p"
            )
            trips = float(norm["passenger trips"].replace(",", ""))
            go_card = int(float(norm["customer complaints on go card"].replace(",", "")))
            other = int(float(norm["customer service complaints other than go card"].replace(",", "")))
            go_card_rate = float(norm["customer complaints (go card) per 10,000 trips"])
            other_rate = float(norm["customer complaints (other than go card) per 10,000 trips"])
        except (KeyError, TypeError, ValueError):
            continue  # skip malformed rows rather than crashing
        records.append({
            "week": week.strftime("%Y-%m-%d"),
            "trips": trips,
            "go_card_complaints": go_card,
            "other_complaints": other,
            "go_card_rate_per_10k": go_card_rate,
            "other_rate_per_10k": other_rate,
        })
    return sorted(records, key=lambda r: r["week"])


# The substring this function looks for in the "Categories" column of the
# Customer experience - overall resource, to find the row that stands in
# for tool3's `customer_experience` signal. Confirmed present (as
# "NETWORK-Ease of using the service overall") in the Tram-specific table;
# NOT yet confirmed this exact prefix exists in the OVERALL table - hence
# substring match rather than exact match. Adjust if a first run finds
# nothing.
CUSTOMER_EXPERIENCE_MATCH_SUBSTRING = "ease of using the service overall"


def customer_experience_overall(ttl_seconds: int = 24 * 3600) -> dict:
    """Network-wide 'ease of using the service overall' rating, by month.

    Source table is WIDE and ROLLING: one row per category, one column per
    month, and the publisher keeps only the most recent ~6 months - older
    months silently disappear from future fetches rather than accumulating.
    So this does NOT behave like the other fetchers here: don't assume a
    fixed history length anywhere downstream, and re-fetch rather than
    caching for long TTLs if you need to know what's currently available.

    Returns:
        {
            "records": [{"month": "2025-12-01", "value": 4.67}, ...],
            "available_months": ["2025-12", "2026-01", ...],  # as published
            "raw_categories": [...],  # every category label seen, for
                                       # debugging if the match fails
            "matched_category": "NETWORK-Ease of using the service overall" or None,
        }
    """
    rows = _fetch_translink_resource(CUSTOMER_EXPERIENCE_OVERALL_ID, ttl_seconds)
    raw_categories = []
    target_row = None
    matched_category = None
    for row in rows:
        category = str(row.get("Categories", "")).strip()
        raw_categories.append(category)
        if CUSTOMER_EXPERIENCE_MATCH_SUBSTRING in category.lower():
            target_row = row
            matched_category = category

    if target_row is None:
        return {
            "records": [],
            "available_months": [],
            "raw_categories": raw_categories,
            "matched_category": None,
        }

    # Month columns are everything that isn't the id/Categories column and
    # parses as a "%b-%y" label ("Dec-25"). Detected dynamically because
    # the actual set of columns drifts month to month (rolling window).
    records = []
    available_months = []
    for key, value in target_row.items():
        if key in ("id", "Categories") or value in (None, ""):
            continue
        try:
            month = datetime.strptime(str(key).strip(), "%b-%y")
        except ValueError:
            continue  # not a month column
        try:
            rating = float(value)
        except (TypeError, ValueError):
            continue  # gap cell - e.g. Tram "Ease of transferring" Dec-25
        records.append({"month": month.strftime("%Y-%m-01"), "value": rating})
        available_months.append(month.strftime("%Y-%m"))

    records.sort(key=lambda r: r["month"])
    available_months.sort()

    return {
        "records": records,
        "available_months": available_months,
        "raw_categories": raw_categories,
        "matched_category": matched_category,
    }
