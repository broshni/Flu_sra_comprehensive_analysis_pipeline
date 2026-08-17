#!/usr/bin/env python3
"""
select_no_genbank.py

Automates the manual filtering step at the end of the SRA-selection module:
given the table produced by join_tables_by_biosample.py (SRA RunInfo rows
plus any linked GenBank accessions per BioSample), split it into:
  - the SRA runs whose BioSample has NO linked GenBank (nuccore) accession
    -- a samples TSV that plugs straight into the base BV-BRC pipeline's
    `samples_tsv` option (it recognizes a "Run" column already).
  - the SRA runs whose BioSample DOES already have one, kept for reference
    (so you have a record of what was excluded and why).

Usage:
    python select_no_genbank.py --joined-table 03_joined.tsv \
        --output-no-genbank no_genbank_samples.tsv \
        --output-with-genbank with_genbank_samples.tsv
"""
import argparse
import sys

import pandas as pd

# Candidate column names (checked case-insensitively) for the run accession,
# scientific name, and taxonomy id -- these match the standard SRA RunInfo
# column names (Run, ScientificName, TaxID) as produced by
# fetch_sra_runs_by_bioproject.py, but fall back gracefully if absent.
RUN_COL_CANDIDATES = ["Run", "run", "srr"]
SCI_NAME_COL_CANDIDATES = ["ScientificName", "scientific_name"]
TAXID_COL_CANDIDATES = ["TaxID", "taxid", "taxonomy_id"]
GENBANK_ACCESSIONS_COL_CANDIDATES = ["genbank_accessions"]
GENBANK_EXTRA_COLS = ["genbank_titles", "genbank_dates", "genbank_records"]


def find_column(df, candidates):
    lower_to_actual = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in lower_to_actual:
            return lower_to_actual[candidate.lower()]
    return None


def build_output(df, run_col, sci_name_col, taxid_col, genbank_col, include_genbank_detail):
    df = df.copy()
    df[run_col] = df[run_col].astype(str).str.strip()
    df = df[df[run_col] != ""]
    df = df.drop_duplicates(subset=[run_col], keep="first")

    out = pd.DataFrame()
    out["Run"] = df[run_col]
    out["scientific_name"] = df[sci_name_col] if sci_name_col else ""
    out["reference_virus"] = ""
    out["taxonomy_id"] = df[taxid_col] if taxid_col else ""

    # Keep a few extra columns for audit purposes -- ignored by the base
    # pipeline's samples_tsv loader (it only reads Run/scientific_name/
    # reference_virus/taxonomy_id), but useful context when reviewing this
    # file by hand.
    for extra_col in ["BioSample", "BioProject", "Query_BioProject"]:
        actual = find_column(df, [extra_col])
        if actual:
            out[extra_col] = df[actual].values

    if include_genbank_detail:
        out["genbank_accessions"] = df[genbank_col].values
        for extra_col in GENBANK_EXTRA_COLS:
            actual = find_column(df, [extra_col])
            if actual:
                out[extra_col] = df[actual].values

    return out.fillna("")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--joined-table", required=True, help="Output of join_tables_by_biosample.py")
    ap.add_argument("--output-no-genbank", required=True, help="Where to write the runs with NO linked GenBank accession (the samples TSV to assemble/annotate)")
    ap.add_argument("--output-with-genbank", required=True, help="Where to write the runs that already HAVE a linked GenBank accession (reference/audit only)")
    args = ap.parse_args()

    df = pd.read_csv(args.joined_table, sep="\t", dtype=str)

    run_col = find_column(df, RUN_COL_CANDIDATES)
    if run_col is None:
        print(
            f"ERROR: {args.joined_table} has no recognizable run-accession "
            f"column (tried {RUN_COL_CANDIDATES}; found columns: {list(df.columns)})",
            file=sys.stderr,
        )
        sys.exit(1)

    genbank_col = find_column(df, GENBANK_ACCESSIONS_COL_CANDIDATES)
    if genbank_col is None:
        print(
            f"ERROR: {args.joined_table} has no 'genbank_accessions' column "
            "-- expected output from join_tables_by_biosample.py "
            f"(found columns: {list(df.columns)})",
            file=sys.stderr,
        )
        sys.exit(1)

    sci_name_col = find_column(df, SCI_NAME_COL_CANDIDATES)
    taxid_col = find_column(df, TAXID_COL_CANDIDATES)

    # A row has "no GenBank accession" if the aggregated genbank_accessions
    # field is missing/NaN or an empty/whitespace string.
    no_genbank_mask = df[genbank_col].isna() | (df[genbank_col].astype(str).str.strip() == "")

    no_genbank = build_output(df[no_genbank_mask], run_col, sci_name_col, taxid_col, genbank_col, include_genbank_detail=False)
    with_genbank = build_output(df[~no_genbank_mask], run_col, sci_name_col, taxid_col, genbank_col, include_genbank_detail=True)

    no_genbank.to_csv(args.output_no_genbank, sep="\t", index=False)
    with_genbank.to_csv(args.output_with_genbank, sep="\t", index=False)

    print(
        f"Wrote {len(no_genbank)} SRA run(s) with NO linked GenBank accession to "
        f"{args.output_no_genbank}"
    )
    print(
        f"Wrote {len(with_genbank)} SRA run(s) WITH a linked GenBank accession to "
        f"{args.output_with_genbank}"
    )
    print(f"({len(df)} total rows in {args.joined_table})")


if __name__ == "__main__":
    main()
