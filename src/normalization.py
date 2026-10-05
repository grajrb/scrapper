"""RawJob -> Job normalization. Source-agnostic cleanup only.

Adapters map their website-specific fields into the CANONICAL RAW PAYLOAD
(see ``adapters/base.py``); this module cleans text, parses dates, derives
city/country from a location string and computes hashes. It NEVER invents
missing information - unknown fields stay ``None``.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Optional

from .models import Company, Job, RawJob, RemoteStatus, TEST_SOURCES, utcnow_iso

_WS = re.compile(r"\s+")

_REMOTE_WORDS = ("remote", "work from home", "wfh", "anywhere")
_HYBRID_WORDS = ("hybrid", "hybrid role")
_NON_CITY = {"remote", "hybrid", "onsite", "on-site", "anywhere", "worldwide", "virtual"}

_REMOTE_ALIASES = {
    "remote": RemoteStatus.REMOTE.value,
    "fully remote": RemoteStatus.REMOTE.value,
    "work from home": RemoteStatus.REMOTE.value,
    "wfh": RemoteStatus.REMOTE.value,
    "hybrid": RemoteStatus.HYBRID.value,
    "onsite": RemoteStatus.ONSITE.value,
    "on-site": RemoteStatus.ONSITE.value,
    "in-office": RemoteStatus.ONSITE.value,
    "in office": RemoteStatus.ONSITE.value,
    "office": RemoteStatus.ONSITE.value,
}


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = _WS.sub(" ", str(value)).strip()
    return text or None


def to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    cleaned = re.sub(r"[^\d.]", "", str(value))
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y",
    "%b %d, %Y", "%B %d, %Y", "%d-%m-%Y", "%b %d %Y", "%B %d %Y",
)


def parse_date(value: Any) -> Optional[str]:
    """Parse a date/datetime into an ISO string (or None). Never guesses."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return None


def normalize_employment_type(value: Any) -> Optional[str]:
    """'Full-time' -> 'full_time' (stable token for filtering)."""
    text = clean_text(value)
    if not text:
        return None
    token = re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")
    return token or None


def detect_remote_status(explicit: Any, *texts: Optional[str]) -> str:
    """Use the explicit field first; only fall back to text hints."""
    key = (clean_text(explicit) or "").casefold()
    if key in _REMOTE_ALIASES:
        return _REMOTE_ALIASES[key]
    blob = " ".join(t for t in texts if t).casefold()
    if any(w in blob for w in _HYBRID_WORDS):
        return RemoteStatus.HYBRID.value
    if any(w in blob for w in _REMOTE_WORDS):
        return RemoteStatus.REMOTE.value
    return RemoteStatus.UNKNOWN.value


def split_location(location: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """'Bangalore, India' -> ('Bangalore', 'India'). No comma -> (None, None)."""
    text = clean_text(location)
    if not text or "," not in text:
        return None, None
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) < 2:
        return None, None
    city = parts[0] if parts[0].casefold() not in _NON_CITY else None
    country = parts[-1] if len(parts) > 2 or parts[-1].casefold() not in _NON_CITY else None
    if country and country.casefold() in _NON_CITY:
        country = None
    return city, country


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Canonical form for URL matching: strips tracking params, fragments,
    default ports, trailing slashes; lowercases scheme+host."""
    text = clean_text(url)
    if not text:
        return None
    try:
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    except ImportError:  # pragma: no cover
        return text
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return text.rstrip("/")
    host = parts.netloc.casefold()
    if host.endswith(":80") and parts.scheme == "http":
        host = host[:-3]
    if host.endswith(":443") and parts.scheme == "https":
        host = host[:-4]
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.casefold().startswith("utm_")
             and k.casefold() not in {"gclid", "fbclid", "ref", "ref_src",
                                      "source", "trk", "mkt_tok"}]
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.casefold(), host, path,
                       urlencode(sorted(query)), ""))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_job(raw: RawJob, company: Optional[Company] = None,
                  company_id: Optional[int] = None) -> Job:
    """Convert a canonical raw payload into a normalized :class:`Job`.

    Missing fields remain ``None``/defaults - nothing is fabricated.
    """
    payload = raw.payload or {}
    now = utcnow_iso()

    title = clean_text(payload.get("title")) or ""
    company_name = (
        clean_text(payload.get("company_name"))
        or (company.company_name if company else None)
        or clean_text(raw.company_hint)
        or ""
    )
    source_url = clean_text(raw.source_url) or clean_text(payload.get("url"))
    canonical_url = normalize_url(source_url)

    location = clean_text(payload.get("location"))
    city = clean_text(payload.get("city"))
    country = clean_text(payload.get("country"))
    if not city or not country:
        derived_city, derived_country = split_location(location)
        city = city or derived_city
        country = country or derived_country

    remote_status = detect_remote_status(
        payload.get("remote_status"), location, payload.get("description"),
        payload.get("title"))

    skills_raw = payload.get("skills") or []
    if isinstance(skills_raw, str):
        skills_raw = [s for s in re.split(r"[,;|]", skills_raw)]
    skills = [s for s in (clean_text(s) for s in skills_raw) if s]

    raw_hash = sha256_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str))

    exp_min = to_int(payload.get("experience_min"))
    exp_max = to_int(payload.get("experience_max"))
    if exp_min is not None and exp_max is not None and exp_min > exp_max:
        exp_min, exp_max = exp_max, exp_min

    return Job(
        company_name=company_name,
        company_id=company_id if company_id is not None
        else (company.id if company else None),
        source=raw.source,
        source_job_id=clean_text(payload.get("source_job_id")),
        title=title,
        canonical_url=canonical_url,
        source_url=source_url,
        location=location,
        country=country,
        city=city,
        remote_status=remote_status,
        employment_type=normalize_employment_type(payload.get("employment_type")),
        department=clean_text(payload.get("department")),
        experience_min=exp_min,
        experience_max=exp_max,
        description=clean_text(payload.get("description")),
        skills=skills,
        salary_min=to_float(payload.get("salary_min")),
        salary_max=to_float(payload.get("salary_max")),
        salary_currency=(clean_text(payload.get("salary_currency")) or None),
        posted_date=parse_date(payload.get("posted_date")),
        updated_date=parse_date(payload.get("updated_date")),
        first_seen=now,
        last_seen=now,
        is_active=True,
        ats=clean_text(payload.get("ats")),
        raw_data_hash=raw_hash,
        is_fixture=raw.source in TEST_SOURCES
        or bool(payload.get("_fixture")),
    )

