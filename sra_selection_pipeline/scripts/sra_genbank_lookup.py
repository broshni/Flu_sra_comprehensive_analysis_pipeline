#!/usr/bin/env python3
"""
sra_genbank_lookup.py -- does each SRA run already have a GenBank record?

Reads a table of SRA runs (xlsx, csv or tsv) with a run-accession column and a
BioSample column, and checks NCBI two ways:
  1. BioSample -> nuccore links (records submitted against the run's BioSample)
  2. SRA run   -> nuccore links (records that cite the SRA run directly)
Queries are batched (100 accessions per request) with retries, so a few
thousand runs take minutes, not hours.

Every input row comes back with these columns added:
  genbank_accessions   pipe-separated accession.version list ("" = none found)
  genbank_titles       pipe-separated titles, same order
  genbank_dates        pipe-separated create dates, same order
  genbank_n_records    number of linked records
  genbank_found_via    biosample | sra_run | biosample+sra_run | ""
  genbank_lookup       ok | failed   <- "failed" rows are NOT a "no" answer;
                                        rerun them (see --only-failed)

Example:
  python3 sra_genbank_lookup.py metadata_unique_runs_2026-10-13.xlsx \
      --sheet "Raw Data" --email you@example.com [--api-key KEY] [--limit 20]

Writes <input>_genbank.xlsx and <input>_genbank.tsv next to the input unless
--out is given. Requires: biopython, pandas, openpyxl.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
from Bio import Entrez

BATCH = 100
SUMMARY_BATCH = 200
RUN_COLS = ["Run", "sra_accession", "srr", "run_accession"]
BIOSAMPLE_COLS = ["BioSample", "biosample_accession", "biosample"]


class NCBI:
    def __init__(self, email, api_key):
        Entrez.email = email
        Entrez.tool = "sra_genbank_lookup"
        if api_key:
            Entrez.api_key = api_key
        # NCBI allows 3 req/s without a key, 10 req/s with one.
        self.pause = 0.12 if api_key else 0.4
        self.calls = 0

    def _json(self, func, **kw):
        last = None
        for attempt in range(6):
            try:
                time.sleep(self.pause)
                self.calls += 1
                with func(retmode="json", **kw) as h:
                    raw = h.read()
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                return json.loads(raw)
            except Exception as exc:  # network blips, 429s, truncated reads
                last = exc
                wait = min(2 ** attempt, 30)
                print(f"  [retry {attempt + 1}/6 in {wait}s] {type(exc).__name__}: {exc}", file=sys.stderr)
                time.sleep(wait)
        raise RuntimeError(f"NCBI request failed after retries: {last}")

    def search_uids(self, db, accessions):
        term = " OR ".join(f"{a}[accn]" for a in accessions)
        res = self._json(Entrez.esearch, db=db, term=term, retmax=len(accessions) * 5)
        return res.get("esearchresult", {}).get("idlist", [])

    def summaries(self, db, uids):
        if not uids:
            return {}
        res = self._json(Entrez.esummary, db=db, id=",".join(uids)).get("result", {})
        return {u: res[u] for u in res.get("uids", []) if u in res}

    def links_to_nuccore(self, dbfrom, uids):
        """One-to-one elink: {from_uid: [nuccore uids]}."""
        if not uids:
            return {}
        # A list id makes Biopython send one id= per uid -> one linkset per uid.
        res = self._json(Entrez.elink, dbfrom=dbfrom, db="nuccore", id=list(uids))
        out = {}
        for ls in res.get("linksets", []):
            ids = [str(i) for i in ls.get("ids", [])]
            links = []
            for lsdb in ls.get("linksetdbs", []):
                if lsdb.get("dbto") == "nuccore":
                    links.extend(str(x) for x in lsdb.get("links", []))
            for i in ids:
                out.setdefault(i, []).extend(links)
        return out


def find_col(df, candidates, label, override=None):
    if override:
        if override not in df.columns:
            sys.exit(f"ERROR: column '{override}' not in input (columns: {list(df.columns)})")
        return override
    lower = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    sys.exit(f"ERROR: no {label} column found (tried {candidates}); use --{label}-col")


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def biosample_route(ncbi, biosamples, failed):
    """{biosample_accession: set(nuccore uids)}"""
    hits = {}
    for i, batch in enumerate(chunks(biosamples, BATCH), 1):
        print(f"[BioSample] batch {i}/{-(-len(biosamples) // BATCH)}")
        try:
            uids = ncbi.search_uids("biosample", batch)
            summ = ncbi.summaries("biosample", uids)
            uid_to_acc = {u: (s.get("accession") or "").strip() for u, s in summ.items()}
            links = ncbi.links_to_nuccore("biosample", uids)
            for u, acc in uid_to_acc.items():
                if acc:
                    hits.setdefault(acc, set()).update(links.get(u, []))
        except RuntimeError as exc:
            print(f"  batch failed: {exc}", file=sys.stderr)
            failed.update(("biosample", b) for b in batch)
    return hits


def sra_route(ncbi, runs, failed):
    """{run_accession: set(nuccore uids)}"""
    import re
    hits = {}
    for i, batch in enumerate(chunks(runs, BATCH), 1):
        print(f"[SRA run]   batch {i}/{-(-len(runs) // BATCH)}")
        try:
            uids = ncbi.search_uids("sra", batch)
            summ = ncbi.summaries("sra", uids)
            links = ncbi.links_to_nuccore("sra", uids)
            wanted = set(batch)
            for u, s in summ.items():
                # An SRA uid is an experiment; its runs are listed in an XML snippet.
                for acc in re.findall(r'acc="([^"]+)"', s.get("runs", "") or ""):
                    if acc in wanted:
                        hits.setdefault(acc, set()).update(links.get(u, []))
        except RuntimeError as exc:
            print(f"  batch failed: {exc}", file=sys.stderr)
            failed.update(("run", r) for r in batch)
    return hits


def nuccore_details(ncbi, uids):
    info = {}
    uids = sorted(uids)
    for i, batch in enumerate(chunks(uids, SUMMARY_BATCH), 1):
        print(f"[GenBank]   details batch {i}/{-(-len(uids) // SUMMARY_BATCH)}")
        try:
            for u, s in ncbi.summaries("nuccore", batch).items():
                info[u] = (
                    s.get("accessionversion") or s.get("caption") or u,
                    (s.get("title") or "").replace("|", "/"),
                    s.get("createdate") or "",
                )
        except RuntimeError as exc:
            print(f"  details batch failed (accessions shown as uids): {exc}", file=sys.stderr)
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("--sheet", default=None, help="Excel sheet name (default: first sheet)")
    ap.add_argument("--email", required=True, help="contact email (NCBI requirement)")
    ap.add_argument("--api-key", default=None, help="NCBI API key (optional, ~3x faster)")
    ap.add_argument("--run-col", default=None)
    ap.add_argument("--biosample-col", default=None)
    ap.add_argument("--limit", type=int, default=None, help="only the first N rows (for a test run)")
    ap.add_argument("--only-failed", type=Path, default=None,
                    help="a previous *_genbank.tsv: re-check only its genbank_lookup=failed rows")
    ap.add_argument("--out", type=Path, default=None, help="output prefix (default: <input>_genbank)")
    args = ap.parse_args()

    suffix = args.input.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(args.input, sheet_name=args.sheet or 0, dtype=str)
    else:
        df = pd.read_csv(args.input, sep="\t" if suffix in (".tsv", ".txt") else ",", dtype=str)
    df = df.fillna("")

    run_col = find_col(df, RUN_COLS, "run", args.run_col)
    bs_col = find_col(df, BIOSAMPLE_COLS, "biosample", args.biosample_col)
    df[run_col] = df[run_col].str.strip()
    df[bs_col] = df[bs_col].str.strip()
    df = df[df[run_col] != ""].reset_index(drop=True)

    if args.only_failed:
        prev = pd.read_csv(args.only_failed, sep="\t", dtype=str).fillna("")
        redo = set(prev.loc[prev["genbank_lookup"] == "failed", run_col])
        df = df[df[run_col].isin(redo)].reset_index(drop=True)
        print(f"Re-checking {len(df)} previously failed runs")
    if args.limit:
        df = df.head(args.limit)

    runs = sorted(set(df[run_col]))
    biosamples = sorted(set(b for b in df[bs_col] if b))
    print(f"{len(df)} rows: {len(runs)} runs, {len(biosamples)} BioSamples")

    ncbi = NCBI(args.email, args.api_key)
    failed = set()
    t0 = time.time()
    by_bs = biosample_route(ncbi, biosamples, failed)
    by_run = sra_route(ncbi, runs, failed)
    all_uids = set().union(*by_bs.values(), *by_run.values()) if (by_bs or by_run) else set()
    details = nuccore_details(ncbi, all_uids)

    cols = {k: [] for k in ("genbank_accessions", "genbank_titles", "genbank_dates",
                            "genbank_n_records", "genbank_found_via", "genbank_lookup")}
    for run, bs in zip(df[run_col], df[bs_col]):
        u_bs = by_bs.get(bs, set())
        u_run = by_run.get(run, set())
        uids = sorted(u_bs | u_run, key=lambda u: details.get(u, (u,))[0])
        recs = [details.get(u, (u, "", "")) for u in uids]
        via = "+".join(n for n, s in (("biosample", u_bs), ("sra_run", u_run)) if s)
        bad = ("biosample", bs) in failed or ("run", run) in failed
        cols["genbank_accessions"].append("|".join(r[0] for r in recs))
        cols["genbank_titles"].append("|".join(r[1] for r in recs))
        cols["genbank_dates"].append("|".join(r[2] for r in recs))
        cols["genbank_n_records"].append(len(recs))
        cols["genbank_found_via"].append(via)
        # A failed batch only makes the row uncertain if nothing was found another way.
        cols["genbank_lookup"].append("failed" if bad and not recs else "ok")
    for k, v in cols.items():
        df[k] = v

    prefix = args.out or args.input.with_name(args.input.stem + "_genbank")
    df.to_csv(f"{prefix}.tsv", sep="\t", index=False)
    df.to_excel(f"{prefix}.xlsx", index=False, sheet_name="genbank_lookup")

    n_found = int((df["genbank_n_records"] > 0).sum())
    n_failed = int((df["genbank_lookup"] == "failed").sum())
    print(f"\nDone in {time.time() - t0:.0f}s ({ncbi.calls} NCBI requests)")
    print(f"  with GenBank record(s): {n_found}")
    print(f"  no GenBank record:      {len(df) - n_found - n_failed}")
    print(f"  lookup failed:          {n_failed}" + ("  -> rerun with --only-failed" if n_failed else ""))
    print(f"Wrote {prefix}.xlsx and {prefix}.tsv")


if __name__ == "__main__":
    main()
