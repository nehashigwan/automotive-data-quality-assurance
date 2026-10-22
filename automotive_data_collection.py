"""
Automotive Data Collection and Quality Assurance (Week 1)
=========================================================
Companion code for the "Data Collection Strategy Report".

What this script does
---------------------
1. INGEST   - downloads public automotive data (API, bulk CSV, optional HTML scraping)
              and stores it unchanged in data/raw/ with a manifest entry.
2. PROFILE  - summarises shape, null rates and duplicates for each dataset.
3. VALIDATE - runs rule-based data quality checks (completeness, validity,
              accuracy ranges, uniqueness, timeliness).
4. REPORT   - writes a CSV quality report to reports/.

Usage
-----
    python automotive_data_collection.py --all
    python automotive_data_collection.py --fueleconomy
    python automotive_data_collection.py --vin 1HGCM82633A004352 5YJSA1E26HF000337
    python automotive_data_collection.py --demo        # offline run on built-in sample data

Always check each source's licence, terms of use and robots.txt before use.
URLs and API formats can change; verify them on the publisher's site.
"""

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter, Retry

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
STAGED_DIR = BASE_DIR / "data" / "staged"
REPORT_DIR = BASE_DIR / "reports"
LOG_DIR = BASE_DIR / "logs"
MANIFEST = RAW_DIR / "manifest.jsonl"

USER_AGENT = "auto-dqa-student-project/1.0 (educational use)"
TIMEOUT = 30

VPIC_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}"
FUELECONOMY_URL = "https://www.fueleconomy.gov/feg/epadata/vehicles.csv.zip"

for folder in (RAW_DIR, STAGED_DIR, REPORT_DIR, LOG_DIR):
    folder.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_DIR / "run.log")],
)
log = logging.getLogger("auto-dqa")


# --------------------------------------------------------------------------
# 1. INGEST
# --------------------------------------------------------------------------
def make_session() -> requests.Session:
    """HTTP session with retries/backoff for rate limits and server errors."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(source: str, url: str, path: Path, rows: int) -> None:
    """Record provenance: where, when, what and a checksum of the raw file."""
    entry = {
        "source": source,
        "url": url,
        "file": str(path.relative_to(BASE_DIR)),
        "rows": rows,
        "sha256": sha256_of(path),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(MANIFEST, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ingest_vpic(vins: list[str], session: requests.Session) -> pd.DataFrame:
    """D1: NHTSA vPIC API - decode VINs into vehicle attributes."""
    records = []
    for vin in vins:
        url = VPIC_URL.format(vin=vin)
        try:
            resp = session.get(url, params={"format": "json"}, timeout=TIMEOUT)
            resp.raise_for_status()
            records.append(resp.json()["Results"][0])
            log.info("vPIC decoded VIN %s", vin)
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            log.error("vPIC failed for %s: %s", vin, exc)
    df = pd.DataFrame(records)
    if not df.empty:
        path = RAW_DIR / f"vpic_decoded_{stamp()}.csv"
        df.to_csv(path, index=False)
        write_manifest("NHTSA vPIC", VPIC_URL.format(vin="{vin}"), path, len(df))
    return df


def ingest_fueleconomy(session: requests.Session) -> pd.DataFrame:
    """D3: FuelEconomy.gov bulk CSV (EPA/DOE)."""
    try:
        resp = session.get(FUELECONOMY_URL, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("FuelEconomy.gov download failed: %s", exc)
        return pd.DataFrame()
    zpath = RAW_DIR / f"fueleconomy_vehicles_{stamp()}.csv.zip"
    zpath.write_bytes(resp.content)  # keep raw file unchanged
    df = pd.read_csv(zpath, compression="zip", low_memory=False)
    write_manifest("FuelEconomy.gov", FUELECONOMY_URL, zpath, len(df))
    log.info("FuelEconomy.gov: %d rows, %d columns", *df.shape)
    return df


def allowed_by_robots(url: str, agent: str = USER_AGENT) -> bool:
    """Check robots.txt before scraping."""
    rp = robotparser.RobotFileParser()
    rp.set_url(urljoin(url, "/robots.txt"))
    try:
        rp.read()
    except Exception:  # robots.txt unreachable: be conservative
        return False
    return rp.can_fetch(agent, url)


def scrape_first_table(url: str, session: requests.Session) -> pd.DataFrame:
    """Last-resort HTML table scraper (BeautifulSoup + pandas.read_html)."""
    if not allowed_by_robots(url):
        raise PermissionError(f"Scraping not permitted by robots.txt: {url}")
    resp = session.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    if table is None:
        raise ValueError("No <table> found on page")
    return pd.read_html(str(table))[0]


# --------------------------------------------------------------------------
# 2. PROFILE
# --------------------------------------------------------------------------
def profile(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Per-column profile: dtype, null rate, distinct values."""
    prof = pd.DataFrame(
        {
            "dataset": name,
            "dtype": df.dtypes.astype(str),
            "null_rate": df.isna().mean().round(4),
            "distinct": df.nunique(dropna=True),
        }
    )
    prof.index.name = "column"
    return prof.reset_index()


# --------------------------------------------------------------------------
# 3. VALIDATE
# --------------------------------------------------------------------------
VIN_PATTERN = r"[A-HJ-NPR-Z0-9]{17}"  # 17 chars, no I, O or Q


def check_rule(name: str, dimension: str, failed: int, total: int) -> dict:
    return {
        "rule": name,
        "dimension": dimension,
        "failed_rows": int(failed),
        "total_rows": int(total),
        "fail_rate": round(failed / total, 4) if total else 0.0,
        "status": "PASS" if failed == 0 else "FAIL",
    }


def validate_vehicles(
    df: pd.DataFrame,
    key_cols: list[str],
    year_col: str = "year",
    numeric_ranges: dict | None = None,
    required_cols: list[str] | None = None,
    max_null_rate: float = 0.05,
    vin_col: str | None = None,
    date_col: str | None = None,
    max_age_days: int = 400,
) -> pd.DataFrame:
    """Run rule-based quality checks and return one row per rule."""
    n = len(df)
    results = []

    # Completeness: required columns should not exceed the null-rate threshold
    for col in required_cols or []:
        if col not in df.columns:
            results.append(check_rule(f"column '{col}' exists", "Completeness", 1, 1))
            continue
        nulls = df[col].isna().sum()
        failed = nulls if (nulls / n if n else 0) > max_null_rate else 0
        results.append(check_rule(f"null rate of '{col}' <= {max_null_rate:.0%}", "Completeness", failed, n))

    # Validity: model year range
    if year_col in df.columns:
        years = pd.to_numeric(df[year_col], errors="coerce")
        bad = (~years.between(1980, datetime.now().year + 1)).sum()
        results.append(check_rule(f"'{year_col}' between 1980 and next year", "Validity", bad, n))

    # Validity: VIN format
    if vin_col and vin_col in df.columns:
        bad = (~df[vin_col].astype(str).str.upper().str.fullmatch(VIN_PATTERN)).sum()
        results.append(check_rule(f"'{vin_col}' is a valid 17-character VIN", "Validity", bad, n))

    # Accuracy: physical/domain ranges
    for col, (lo, hi) in (numeric_ranges or {}).items():
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce")
            bad = (vals.notna() & ~vals.between(lo, hi)).sum()
            results.append(check_rule(f"'{col}' within [{lo}, {hi}]", "Accuracy", bad, n))

    # Uniqueness: duplicates on the natural key
    present = [c for c in key_cols if c in df.columns]
    if present:
        dups = df.duplicated(subset=present).sum()
        results.append(check_rule(f"no duplicate keys on {present}", "Uniqueness", dups, n))

    # Consistency: make names should have one canonical form (case/whitespace)
    if "make" in df.columns:
        raw = df["make"].dropna().astype(str)
        canonical = raw.str.strip().str.title()
        variants = raw.groupby(canonical).nunique()
        inconsistent = int(raw[canonical.isin(variants[variants > 1].index)].shape[0])
        results.append(check_rule("make names use a single spelling/case", "Consistency", inconsistent, n))

    # Timeliness: newest record should be recent
    if date_col and date_col in df.columns:
        newest = pd.to_datetime(df[date_col], errors="coerce").max()
        age = (pd.Timestamp.now() - newest).days if pd.notna(newest) else 10**6
        results.append(check_rule(f"newest '{date_col}' within {max_age_days} days", "Timeliness", 1 if age > max_age_days else 0, 1))

    return pd.DataFrame(results)


def flag_outliers_iqr(s: pd.Series, k: float = 1.5) -> pd.Series:
    """Boolean mask of IQR outliers (flag and verify; do not delete blindly)."""
    s = pd.to_numeric(s, errors="coerce")
    q1, q3 = s.quantile([0.25, 0.75])
    iqr = q3 - q1
    return (s < q1 - k * iqr) | (s > q3 + k * iqr)


# --------------------------------------------------------------------------
# 4. CLEAN (minimal, documented)
# --------------------------------------------------------------------------
def standardise(df: pd.DataFrame) -> pd.DataFrame:
    """Standardise column names and text fields; remove exact duplicates."""
    out = df.copy()
    out.columns = [c.strip().lower().replace(" ", "_") for c in out.columns]
    for col in out.columns:
        if pd.api.types.is_object_dtype(out[col]) or pd.api.types.is_string_dtype(out[col]):
            out[col] = out[col].astype("string").str.strip()
    if "make" in out.columns:
        out["make"] = out["make"].str.title()
    return out.drop_duplicates()


# --------------------------------------------------------------------------
# Demo data (offline) and main
# --------------------------------------------------------------------------
def demo_dataframe() -> pd.DataFrame:
    """Small synthetic dataset with deliberate quality problems."""
    return pd.DataFrame(
        {
            "make": ["Toyota", "toyota", "Honda", "Ford", "Ford", "BMW", "Tesla"],
            "model": ["Corolla", "Corolla", "Civic", "Focus", "Focus", "X5", "Model 3"],
            "year": [2019, 2019, 2021, 1975, 1975, 2022, 2023],
            "comb_mpg": [32, 32, 36, 28, 28, 400, 130],
            "displacement_l": [1.8, 1.8, 2.0, None, None, 3.0, None],
        }
    )


def run_quality(df: pd.DataFrame, name: str) -> None:
    # Validate the RAW data first so problems (duplicates, inconsistent
    # spellings, bad values) are reported before cleaning hides them.
    raw = df.copy()
    raw.columns = [c.strip().lower().replace(" ", "_") for c in raw.columns]
    clean = standardise(df)
    prof = profile(raw, name)
    rules = validate_vehicles(
        raw,
        key_cols=["make", "model", "year"],
        year_col="year",
        required_cols=["make", "model", "year"],
        numeric_ranges={"comb_mpg": (5, 150), "displacement_l": (0.1, 10)},
    )
    rules.insert(0, "dataset", name)
    prof.to_csv(REPORT_DIR / f"{name}_profile.csv", index=False)
    rules.to_csv(REPORT_DIR / f"{name}_validation.csv", index=False)
    clean.to_csv(STAGED_DIR / f"{name}_staged.csv", index=False)
    log.info("Quality report for %s:\n%s", name, rules.to_string(index=False))


def main() -> int:
    ap = argparse.ArgumentParser(description="Automotive data collection and quality assurance")
    ap.add_argument("--all", action="store_true", help="run all ingestions")
    ap.add_argument("--fueleconomy", action="store_true", help="download FuelEconomy.gov vehicles data")
    ap.add_argument("--vin", nargs="+", metavar="VIN", help="decode VINs with NHTSA vPIC")
    ap.add_argument("--demo", action="store_true", help="offline demo on synthetic data")
    args = ap.parse_args()

    if not (args.all or args.fueleconomy or args.vin or args.demo):
        ap.print_help()
        return 0

    if args.demo:
        run_quality(demo_dataframe(), "demo")

    session = make_session()

    if args.all or args.fueleconomy:
        fe = ingest_fueleconomy(session)
        if not fe.empty:
            fe = fe.rename(columns={"comb08": "comb_mpg", "displ": "displacement_l"})
            run_quality(fe, "fueleconomy")

    if args.all or args.vin:
        vins = args.vin or ["1HGCM82633A004352", "5YJSA1E26HF000337"]
        vp = ingest_vpic(vins, session)
        if not vp.empty:
            vp = vp.rename(columns={"Make": "make", "Model": "model", "ModelYear": "year"})
            run_quality(vp, "vpic")

    return 0


if __name__ == "__main__":
    sys.exit(main())
