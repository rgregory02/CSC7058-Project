
from __future__ import annotations
from datetime import datetime, date, timedelta, timezone
from typing import Optional, Dict, Any

# ---- Configurable mappings (edit to taste) ----
LIFE_STAGE_TO_AGE = {
    "infant": 0.5,
    "toddler": 1.5,
    "childhood": 6.5,
    "preteen": 11.5,
    "teen": 15, "teens": 15,
    "twenties": 25,
    "thirties": 35,
    "forties": 45,
    "fifties": 55,
    "sixties": 65,
    "seventies": 75,
    "eighties": 85,
    "nineties": 95,
    "hundreds": 105,
}

# Default window around an approximate midpoint (± years)
APPROX_YEARS_WINDOW = 2


# -------------------- tiny date helpers --------------------
def _parse_iso_date(s: str) -> Optional[date]:
    """Accepts 'YYYY'|'YYYY-MM'|'YYYY-MM-DD'. Returns a date (UTC) at earliest day in that period."""
    if not s:
        return None
    try:
        if len(s) == 4:                     # '1992'
            return date(int(s), 1, 1)
        if len(s) == 7:                     # '1992-06'
            y, m = s.split('-', 1)
            return date(int(y), int(m), 1)
        # Best effort: full date
        return datetime.fromisoformat(s.replace('Z','')).date()
    except Exception:
        return None


def _end_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    first_next = date(d.year, d.month + 1, 1)
    return first_next - timedelta(days=1)


def _end_of_period_from_input(s: str) -> Optional[date]:
    """Given the user's ISO-ish input, return the period end (end of year/month/day)."""
    if not s:
        return None
    try:
        if len(s) == 4:
            return date(int(s), 12, 31)
        if len(s) == 7:
            y, m = s.split('-', 1)
            return _end_of_month(date(int(y), int(m), 1))
        d = _parse_iso_date(s)
        return d
    except Exception:
        return None


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _ts_utc(d: Optional[date]) -> Optional[int]:
    if not d:
        return None
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _add_years(d: date, years: float) -> date:
    """Add (possibly fractional) years to a date. Fraction maps across the year length."""
    whole = int(years)
    frac = years - whole
    try:
        base = date(d.year + whole, d.month, d.day)
    except ValueError:
        # Handle 29 Feb on non-leap: move to 28 Feb
        if d.month == 2 and d.day == 29:
            base = date(d.year + whole, 2, 28)
        else:
            raise
    # distribute fraction as days (approx)
    days_in_year = 366 if _is_leap(base.year) else 365
    return base + timedelta(days=int(round(frac * days_in_year)))


def _is_leap(year: int) -> bool:
    return year % 400 == 0 or (year % 4 == 0 and year % 100 != 0)


def _decade_bounds(subvalue: str) -> Optional[tuple[date, date]]:
    """
    Accepts '1990s', '1980s', '1990-1999', or just '1990'.
    Returns (start_date, end_date) for that decade.
    """
    s = (subvalue or '').lower().replace('s', '')
    # forms like '1990-1999'
    if '-' in s:
        try:
            y1, y2 = s.split('-', 1)
            y1, y2 = int(y1), int(y2)
            return date(y1, 1, 1), date(y2, 12, 31)
        except Exception:
            return None
    # forms like '1990'
    try:
        y = int(s)
        return date(y, 1, 1), date(y + 9, 12, 31)
    except Exception:
        return None


# -------------------- main normaliser --------------------
def normalise_time(
    raw: Dict[str, Any],
    *,
    dob_iso: Optional[str] = None,
    dod_iso: Optional[str] = None,
    ref_iso: Optional[str] = None,
    option_meta: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convert the user 'raw' time selection into a normalised payload:

      raw = {
        "label_type": "date" | "life_stage" | "decade" | "era" | "range" | ...,
        "date_value": "YYYY[-MM[-DD]]" (optional),
        "subvalue":   "teens"|"1990s"|<era-id>|... (optional),
        "confidence": 0..100
      }

    - dob_iso:     e.g. '1975-03-21' (for person)
    - ref_iso:     a type-specific reference date: founded_on, built_on, etc.
    - option_meta: the JSON of the chosen label option (if available). If it contains
                   {"start_iso": "...", "end_iso": "..."} we will honour these.

    Returns a dict:
      {
        "kind": "date|life_stage|decade|era|range|unknown",
        "start_iso": "YYYY-MM-DD"|None,
        "end_iso":   "YYYY-MM-DD"|None,
        "start_ts":  int|None,   # unix seconds
        "end_ts":    int|None,
        "precision": "exact|approx|unknown",
        "age_years": float|None, # when derivable
        "notes":     str
      }
    """
    raw = raw or {}
    lt = (raw.get("label_type") or "").strip().lower()
    sub = (raw.get("subvalue") or "").strip().lower()
    date_val = (raw.get("date_value") or "").strip()
    conf = int(raw.get("confidence", 100))

    # default skeleton
    out = {
        "kind": lt or "unknown",
        "start_iso": None,
        "end_iso": None,
        "start_ts": None,
        "end_ts": None,
        "precision": "exact" if conf == 100 and lt == "date" else ("approx" if conf >= 50 else "unknown"),
        "age_years": None,
        "notes": ""
    }

    # Helper to commit start/end to iso+ts
    def _commit_bounds(s: Optional[date], e: Optional[date]):
        out["start_iso"] = _iso(s)
        out["end_iso"]   = _iso(e)
        out["start_ts"]  = _ts_utc(s)
        out["end_ts"]    = _ts_utc(e)

    # 0) ENTIRE / WHOLE LIFE → span start→end if available
    life_slugs = {
        "entire_life", "whole_life", "life", "lifespan",
        "entire_history", "whole_history",
        "entire_period", "whole_period", "whole_span", "entire_span"
    }
    label_text = (raw.get("value") or raw.get("label") or "").strip().lower()
    if lt in life_slugs or (label_text.replace(" ", "_") in life_slugs):
        s = _parse_iso_date(dob_iso or "")
        e = _parse_iso_date(dod_iso or "")
        _commit_bounds(s, e)
        out["kind"] = "life"          # 'life' == existence span for any type
        if s and e:
            out["precision"] = "exact"
            out["notes"] = "Whole span from biography start→end"
        elif s or e:
            out["precision"] = "approx"
            out["notes"] = "Whole span; only one bound available"
        else:
            out["precision"] = "unknown"
            out["notes"] = "Whole span selected; biography has no start/end"
        return out

    # 1) Explicit DATE
    if lt == "date":
        start = _parse_iso_date(date_val)
        end   = _end_of_period_from_input(date_val)
        _commit_bounds(start, end)
        out["precision"] = "exact" if conf >= 90 else "approx"
        out["notes"] = "Direct date entry"
        return out

    # 2) RANGE (optional support: date_value can be 'YYYY..YYYY' or pass range in raw)
    if lt == "range":
        s = raw.get("start_date") or ""
        e = raw.get("end_date") or ""
        sd = _parse_iso_date(s) if s else None
        ed = _end_of_period_from_input(e) if e else None
        _commit_bounds(sd, ed or sd)
        out["precision"] = "approx" if conf < 90 else "exact"
        out["notes"] = "Explicit date range"
        return out

    # 3) LIFE STAGE → approximate age; convert to absolute when DOB/ref available
    if lt == "life_stage" and sub:
        age = LIFE_STAGE_TO_AGE.get(sub)
        out["age_years"] = age
        ref = _parse_iso_date(dob_iso or ref_iso or "")
        if age is not None and ref:
            mid = _add_years(ref, age)
            start = _add_years(mid, -APPROX_YEARS_WINDOW)
            end   = _add_years(mid,  APPROX_YEARS_WINDOW)
            _commit_bounds(start, end)
            out["precision"] = "approx"
            out["notes"] = f"Derived from life stage '{sub}' (~{age}y) with reference date"
        else:
            out["notes"] = f"Life stage '{sub}' (no reference date — absolute bounds unknown)"
        return out

    # 4) DECADE → prefer option metadata; else infer
    if lt == "decade":
        # If your label JSON carries explicit range
        if option_meta and isinstance(option_meta, dict):
            s_iso = option_meta.get("start_iso")
            e_iso = option_meta.get("end_iso")
            if s_iso or e_iso:
                sd = _parse_iso_date(s_iso) if s_iso else None
                ed = _parse_iso_date(e_iso) if e_iso else None
                # If only a start is provided, infer 10-year span
                if sd and not ed:
                    ed = date(sd.year + 9, 12, 31)
                _commit_bounds(sd, ed)
                out["precision"] = "approx"
                out["notes"] = "Decade from option metadata"
                return out

        # Fallback: parse the decade text (e.g., '1990s' or '1990-1999' or '1990')
        bounds = _decade_bounds(sub or date_val)
        if bounds:
            _commit_bounds(*bounds)
            out["precision"] = "approx"
            out["notes"] = "Decade inferred from label"
            return out

    # 5) ERA → expect option metadata to define bounds (you can add them in your JSON)
    if lt == "era":
        if option_meta and isinstance(option_meta, dict):
            s_iso = option_meta.get("start_iso")
            e_iso = option_meta.get("end_iso")
            if s_iso or e_iso:
                sd = _parse_iso_date(s_iso) if s_iso else None
                ed = _parse_iso_date(e_iso) if e_iso else None
                _commit_bounds(sd, ed)
                out["precision"] = "approx"
                out["notes"] = "Era bounds from option metadata"
                return out
        out["notes"] = "Era selected but no explicit bounds available"
        out["precision"] = "unknown"
        return out

    # 6) Fallback: unknown kind, try to parse date_value as a hint
    if date_val:
        start = _parse_iso_date(date_val)
        end   = _end_of_period_from_input(date_val)
        _commit_bounds(start, end)
        out["notes"] = "Fallback date parsing from date_value"
        out["precision"] = "approx" if conf < 90 else "exact"
    else:
        out["notes"] = "Unrecognised time label (no bounds)"
        out["precision"] = "unknown"

    return out


def normalise_time_for_bio_entry(
    raw: Dict[str, Any],
    *,
    biography: Dict[str, Any] | None = None,
    option_meta: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Pulls likely start/end reference dates from a biography, regardless of type.
    Examples (all optional, first present wins):
      Start keys: dob_iso, dob, founded_on, established_on, built_on, opened_on,
                  start_on, start_date, inception_on
      End   keys: dod_iso, dod, dissolved_on, closed_on, demolished_on,
                  end_on, end_date, conclusion_on
    """
    bio = biography or {}

    def _first(keys: list[str]) -> str | None:
        for k in keys:
            val = bio.get(k)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None

    start_iso = _first([
        "dob_iso", "dob",
        "founded_on", "established_on",
        "built_on", "opened_on",
        "start_on", "start_date", "inception_on",
    ])

    end_iso = _first([
        "dod_iso", "dod",
        "dissolved_on", "closed_on", "demolished_on",
        "end_on", "end_date", "conclusion_on",
    ])

    # Keep the generic 'ref' for cases where you select a single date kind
    ref = _first(["reference_date_iso", "founded_on", "built_on", "opened_on", "start_on", "start_date"])

    return normalise_time(
        raw,
        dob_iso=start_iso,   # reuse params: "dob" == existence start
        dod_iso=end_iso,     # "dod" == existence end
        ref_iso=ref,
        option_meta=option_meta,
    )