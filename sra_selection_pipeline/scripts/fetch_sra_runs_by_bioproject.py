#!/usr/bin/env python3
"""
fetch_sra_runs_by_bioproject.py

Fetch all SRA runs and associated RunInfo metadata for a list of BioProject accessions.

Inputs:
- One or more BioProject IDs (e.g. PRJNAxxxxx) passed via --bioprojects or --bioproject-file
- Entrez email (required) and optional API key
- Optional date filters for SRA publication dates

Outputs:
- A single CSV or TSV file containing RunInfo rows for all matching SRA runs

Example:
    python fetch_sra_runs_by_bioproject.py \
        --bioprojects PRJNA1122849 PRJNA123456 \
        --email you@example.com \
        --output sra_runinfo.tsv --format tsv \
        --cache-dir cache_ncbi

The script uses Biopython Entrez and includes a small disk cache to avoid repeated NCBI requests.

Date filtering (--sra-mindate / --sra-maxdate, inclusive, YYYY-MM-DD):
  1. The window is sent to NCBI as a [PDAT] range in the YYYY/MM/DD form Entrez
     expects, and NCBI's own reading of the query (QueryTranslation) is logged
     so you can see whether it was applied.
  2. Every returned row is then checked locally against its RunInfo
     ReleaseDate, and rows outside the window (or with no ReleaseDate) are
     dropped. This is the authoritative filter: earlier runs showed the
     NCBI-side range alone did not narrow results.
  If no run falls inside the window, a header-only file is written, so a
  quiet week flows through the pipeline as "nothing to do" instead of an error.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from Bio import Entrez


# ---------- small disk cache helper ----------
class DiskCache:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str, key: str, suffix: str = ".json") -> Path:
        safe_key = str(abs(hash(key)))
        p = self.base_dir / namespace
        p.mkdir(parents=True, exist_ok=True)
        return p / f"{safe_key}{suffix}"

    def get_text(self, namespace: str, key: str, suffix: str = ".txt") -> Optional[str]:
        p = self._path(namespace, key, suffix)
        if p.exists():
            return p.read_text(encoding="utf-8")
        return None

    def set_text(self, namespace: str, key: str, text: str, suffix: str = ".txt") -> None:
        p = self._path(namespace, key, suffix)
        p.write_text(text, encoding="utf-8")


# ---------- NCBI client with retry + caching ----------
class NCBIClient:
    def __init__(self, email: str, api_key: Optional[str], cache: DiskCache, tool: str = "fetch_sra_runs"):
        Entrez.email = email
        Entrez.tool = tool
        if api_key:
            Entrez.api_key = api_key
        self.api_key = api_key
        self.cache = cache
        # sleep shorter when API key present
        self.sleep_seconds = 0.34 if api_key else 1.5

    @staticmethod
    def _log_search(result) -> None:
        translation = result.get("QueryTranslation", "")
        print(f"[INFO]   NCBI query translation: {translation}")
        warnings = result.get("WarningList") or {}
        for key in ("PhraseIgnored", "QuotedPhraseNotFound", "OutputMessage"):
            for msg in warnings.get(key, []) or []:
                print(f"[WARN]   NCBI {key}: {msg}")
        errors = result.get("ErrorList") or {}
        for key, msgs in errors.items():
            for msg in msgs or []:
                print(f"[WARN]   NCBI {key}: {msg}")

    def esearch_ids(self, db: str, term: str, retmax: int = 100000) -> List[str]:
        cache_key = f"esearch|db={db}|term={term}|retmax={retmax}"
        cached = self.cache.get_text("esearch", cache_key, ".json")
        if cached:
            try:
                result = json.loads(cached)
                self._log_search(result)
                return result.get("IdList", [])
            except Exception:
                pass

        last_err = None
        for attempt in range(5):
            try:
                time.sleep(self.sleep_seconds)
                with Entrez.esearch(db=db, term=term, retmax=retmax, retmode="xml") as handle:
                    result = Entrez.read(handle)
                self.cache.set_text("esearch", cache_key, json.dumps(result), ".json")
                self._log_search(result)
                return result.get("IdList", [])
            except Exception as exc:
                last_err = exc
                wait = 2 ** attempt
                print(f"[WARN] esearch retry {attempt+1}/5 after error: {exc}", file=sys.stderr)
                time.sleep(wait)
        raise RuntimeError(f"esearch failed after retries: {last_err}")

    def efetch_runinfo_text(self, ids: List[str]) -> str:
        # ids is expected to be a list of SRA IDs (Run IDs). We fetch runinfo for them in one batch.
        ids_key = ",".join(ids)
        cache_key = f"efetch_runinfo|ids={ids_key}"
        cached = self.cache.get_text("efetch_runinfo", cache_key, ".txt")
        if cached is not None:
            return cached

        last_err = None
        for attempt in range(5):
            try:
                time.sleep(self.sleep_seconds)
                with Entrez.efetch(db="sra", id=ids_key, rettype="runinfo", retmode="text") as handle:
                    raw = handle.read()
                    # handle.read() may be bytes or str depending on Biopython/Python versions
                    if isinstance(raw, bytes):
                        text = raw.decode("utf-8")
                    else:
                        text = raw
                self.cache.set_text("efetch_runinfo", cache_key, text, ".txt")
                return text
            except Exception as exc:
                last_err = exc
                wait = 2 ** attempt
                print(f"[WARN] efetch_runinfo retry {attempt+1}/5 after error: {exc}", file=sys.stderr)
                time.sleep(wait)
        raise RuntimeError(f"efetch_runinfo failed after retries: {last_err}")


# ---------- main logic ----------

DEFAULT_COLUMNS = None  # if None keep whatever columns appear in RunInfo

_DATE_RE = re.compile(r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s*$")


def parse_date_arg(value: Optional[str], label: str) -> Optional[date]:
    """Accept YYYY-MM-DD (or YYYY/MM/DD); None/blank means no bound."""
    if value is None or not str(value).strip():
        return None
    m = _DATE_RE.match(str(value))
    if not m:
        sys.exit(f"ERROR: {label} '{value}' is not a date in YYYY-MM-DD form")
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError as exc:
        sys.exit(f"ERROR: {label} '{value}' is not a valid date ({exc})")


def pdat_term(mindate: Optional[date], maxdate: Optional[date]) -> Optional[str]:
    """Entrez [PDAT] range clause, dates in the YYYY/MM/DD form Entrez expects."""
    if not mindate and not maxdate:
        return None
    lo = mindate.strftime("%Y/%m/%d") if mindate else "1900/01/01"
    hi = maxdate.strftime("%Y/%m/%d") if maxdate else "3000/12/31"
    return f'("{lo}"[PDAT] : "{hi}"[PDAT])'


def release_date(row: Dict[str, str]) -> Optional[date]:
    raw = (row.get("ReleaseDate") or "").strip()
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def filter_by_release_date(rows: List[Dict[str, str]], mindate: Optional[date], maxdate: Optional[date]) -> List[Dict[str, str]]:
    """Keep rows whose RunInfo ReleaseDate is inside [mindate, maxdate]."""
    if not mindate and not maxdate:
        return rows
    kept, outside, undated = [], 0, 0
    for row in rows:
        d = release_date(row)
        if d is None:
            undated += 1
        elif (mindate and d < mindate) or (maxdate and d > maxdate):
            outside += 1
        else:
            kept.append(row)
    window = f"{mindate or 'any'} .. {maxdate or 'any'}"
    print(f"[INFO] ReleaseDate filter {window}: kept {len(kept)} of {len(rows)} rows "
          f"({outside} outside the window, {undated} with no ReleaseDate)")
    return kept


def fetch_runinfo_for_bioprojects(ncbi: NCBIClient, bioprojects: List[str], sra_mindate: Optional[date], sra_maxdate: Optional[date]) -> List[Dict[str, str]]:
    all_rows: List[Dict[str, str]] = []

    for bp in bioprojects:
        print(f"[INFO] Searching SRA runs for BioProject: {bp}")
        term_parts = [f'"{bp}"[BioProject]']
        date_clause = pdat_term(sra_mindate, sra_maxdate)
        if date_clause:
            term_parts.append(date_clause)
        term = " AND ".join(term_parts)
        print(f"[INFO]   Query: {term}")

        ids = ncbi.esearch_ids("sra", term, retmax=100000)
        print(f"[INFO]   Found {len(ids)} SRA ids for {bp}")
        if not ids:
            continue

        # fetch runinfo in batches (Entrez limits and to keep responses manageable)
        for batch_start in range(0, len(ids), 500):
            batch = ids[batch_start: batch_start + 500]
            print(f"[INFO]   Fetching runinfo for batch {batch_start}..{batch_start+len(batch)-1}")
            text = ncbi.efetch_runinfo_text(batch)
            # parse as CSV
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                # ensure strings
                clean = {k: (v if v is not None else "") for k, v in row.items()}
                # add original bioproject for context
                clean.setdefault("Query_BioProject", bp)
                all_rows.append(clean)

    return all_rows


def write_output(rows: List[Dict[str, str]], out_path: str, fmt: str, header: Optional[List[str]] = None) -> None:
    if not rows:
        if header:
            # NCBI returned runs but none fall inside the date window: write the
            # header only, so downstream steps see "0 runs" rather than a
            # missing/blank file.
            delimiter = "\t" if fmt == "tsv" else ","
            with open(out_path, "w", encoding="utf-8", newline="") as fh:
                csv.writer(fh, delimiter=delimiter).writerow(header)
            print(f"[INFO] No runs inside the date window; wrote header-only {out_path}")
            return
        # NCBI returned nothing at all: write an empty file
        open(out_path, "w", encoding="utf-8").close()
        print(f"[INFO] Wrote empty output to {out_path}")
        return

    # preserve column order from first row + any additional keys
    cols = list(rows[0].keys())
    # add any keys present elsewhere but missing in the first row
    extra = set()
    for r in rows:
        extra.update(r.keys())
    for k in sorted(extra):
        if k not in cols:
            cols.append(k)

    delimiter = "\t" if fmt == "tsv" else ","
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, delimiter=delimiter, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"[INFO] Wrote {len(rows)} rows to {out_path}")


def parse_args():
    p = argparse.ArgumentParser(description="Fetch SRA RunInfo rows for BioProject lists")
    p.add_argument("--bioprojects", nargs="*", help="List of BioProject accessions (e.g. PRJNA12345)")
    p.add_argument("--bioproject-file", help="File with one BioProject accession per line")
    p.add_argument("--email", required=True, help="Entrez email (NCBI requirement)")
    p.add_argument("--api-key", default=None, help="Entrez API key (optional)")
    p.add_argument("--output", default="sra_runinfo.tsv", help="Output file (CSV or TSV based on --format)")
    p.add_argument("--format", choices=["tsv", "csv"], default="tsv", help="Output format")
    p.add_argument("--cache-dir", default="cache_ncbi", help="Directory to cache NCBI responses")
    p.add_argument("--sra-mindate", default=None, help="Optional SRA min publication date (YYYY-MM-DD)")
    p.add_argument("--sra-maxdate", default=None, help="Optional SRA max publication date (YYYY-MM-DD)")
    return p.parse_args()


def load_bioprojects_from_file(path: str) -> List[str]:
    out: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            v = line.strip()
            if v:
                out.append(v)
    return out


def main():
    args = parse_args()

    bps: List[str] = []
    if args.bioprojects:
        bps.extend(args.bioprojects)
    if args.bioproject_file:
        bps.extend(load_bioprojects_from_file(args.bioproject_file))
    bps = [x.strip() for x in bps if x and x.strip()]
    if not bps:
        print("Provide --bioprojects or --bioproject-file", file=sys.stderr)
        sys.exit(2)

    cache = DiskCache(args.cache_dir)
    ncbi = NCBIClient(args.email, args.api_key, cache)

    mindate = parse_date_arg(args.sra_mindate, "--sra-mindate")
    maxdate = parse_date_arg(args.sra_maxdate, "--sra-maxdate")
    if mindate and maxdate and mindate > maxdate:
        sys.exit(f"ERROR: --sra-mindate {mindate} is after --sra-maxdate {maxdate}")

    rows = fetch_runinfo_for_bioprojects(ncbi, bps, mindate, maxdate)
    header = list(rows[0].keys()) if rows else None
    rows = filter_by_release_date(rows, mindate, maxdate)
    write_output(rows, args.output, args.format, header=header)


if __name__ == "__main__":
    main()

