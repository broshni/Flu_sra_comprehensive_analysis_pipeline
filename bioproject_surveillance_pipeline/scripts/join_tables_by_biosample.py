#!/usr/bin/env python3
"""
Join two tables (TSV/CSV) on a BioSample column.

This script reads an SRA table and a GenBank table, groups GenBank records by BioSample
and aggregates accession and title information into pipe-separated strings, then
attaches those aggregated fields to every SRA row for the matching BioSample.

Output columns added to the SRA table:
- genbank_accessions : pipe-separated accession list
- genbank_titles     : pipe-separated title list
- genbank_records    : pipe-separated "accession - title" records

Usage examples:
  python join_tables_by_biosample.py \
    --sra-table sra.tsv --genbank-table genbank.tsv --out joined.tsv

Options allow you to specify column names if your files use different headers.
The script infers TSV vs CSV from file extensions (.tsv/.txt -> tab) or you can
explicitly set --format csv|tsv for the output.

Dependencies:
  pip install pandas
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import pandas as pd


def infer_sep(path: Optional[str]) -> dict:
    if not path:
        return {}
    lower = path.lower()
    if lower.endswith('.tsv') or lower.endswith('.txt'):
        return {'sep': '\t'}
    return {}


def find_column(df: pd.DataFrame, requested: str) -> Optional[str]:
    # case-insensitive match
    if requested in df.columns:
        return requested
    lowreq = requested.lower()
    for c in df.columns:
        if c.lower() == lowreq:
            return c
    return None


def aggregate_genbank(genbank_df: pd.DataFrame, gb_biosample_col: str, gb_accession_col: str, gb_title_col: str, gb_date_col: Optional[str] = None) -> pd.DataFrame:
    # Ensure columns exist
    # Normalize by converting to string and dropping NA
    df = genbank_df.copy()
    df[gb_biosample_col] = df[gb_biosample_col].astype(str).str.strip()
    df[gb_accession_col] = df[gb_accession_col].astype(str).str.strip()
    df[gb_title_col] = df[gb_title_col].astype(str).str.strip()

    # Remove empty biosample keys
    df = df[df[gb_biosample_col] != '']

    # Group and aggregate unique accessions and titles preserving order
    def uniq_keeporder(seq):
        seen = set()
        out = []
        for x in seq:
            if x not in seen and x != '':
                seen.add(x)
                out.append(x)
        return out

    # include date aggregation if requested
    agg_map = {
        gb_accession_col: lambda s: '|'.join(uniq_keeporder(list(s.dropna().astype(str)))),
        gb_title_col: lambda s: '|'.join(uniq_keeporder(list(s.dropna().astype(str)))),
    }
    if gb_date_col is not None and gb_date_col in df.columns:
        df[gb_date_col] = df[gb_date_col].astype(str).str.strip()
        agg_map[gb_date_col] = lambda s: '|'.join(uniq_keeporder(list(s.dropna().astype(str))))

    # also aggregate a genbank_date_source column if present (e.g., 'genbank_date_source')
    gb_date_source_col = None
    if 'genbank_date_source' in df.columns:
        gb_date_source_col = 'genbank_date_source'
        df[gb_date_source_col] = df[gb_date_source_col].astype(str).str.strip()
        agg_map[gb_date_source_col] = lambda s: '|'.join(uniq_keeporder(list(s.dropna().astype(str))))

    grouped = df.groupby(gb_biosample_col).agg(agg_map).reset_index()

    # build combined record (accession - title) for display
    def combine_row(accs: str, titles: str, dates: str = '') -> str:
        if not accs and not titles:
            return ''
        acc_list = accs.split('|') if accs else []
        title_list = titles.split('|') if titles else []
        date_list = dates.split('|') if dates else []
        # pair up: if unequal lengths, pair by index when possible, others get empty
        recs = []
        maxlen = max(len(acc_list), len(title_list), len(date_list))
        for i in range(maxlen):
            a = acc_list[i] if i < len(acc_list) else ''
            t = title_list[i] if i < len(title_list) else ''
            d = date_list[i] if i < len(date_list) else ''
            if a and t:
                recs.append(f"{a} - {t}")
            elif a:
                recs.append(a)
            elif t:
                recs.append(t)
            if d:
                recs[-1] += f" ({d})"
        return '|'.join(recs)

    grouped['genbank_accessions'] = grouped[gb_accession_col]
    grouped['genbank_titles'] = grouped[gb_title_col]
    if gb_date_col is not None and gb_date_col in grouped.columns:
        grouped['genbank_dates'] = grouped[gb_date_col]
        # include date in the combined record
        # list comprehension, not DataFrame.apply: apply on an empty frame returns a
        # DataFrame and this assignment crashes when no BioSample has a record
        grouped['genbank_records'] = [
            combine_row(a, t, d)
            for a, t, d in zip(grouped[gb_accession_col], grouped[gb_title_col], grouped[gb_date_col])
        ]
    else:
        grouped['genbank_dates'] = ''
        grouped['genbank_records'] = [
            combine_row(a, t, '') for a, t in zip(grouped[gb_accession_col], grouped[gb_title_col])
        ]

    # include aggregated date sources if present
    if gb_date_source_col and gb_date_source_col in grouped.columns:
        grouped['genbank_date_sources'] = grouped[gb_date_source_col]
    else:
        grouped['genbank_date_sources'] = ''

    # keep only biosample and the new columns (including dates and sources)
    return grouped[[gb_biosample_col, 'genbank_accessions', 'genbank_titles', 'genbank_dates', 'genbank_date_sources', 'genbank_records']]


def main():
    p = argparse.ArgumentParser(description='Join SRA table with GenBank table by BioSample')
    p.add_argument('--sra-table', required=True, help='Path to SRA table (CSV/TSV)')
    p.add_argument('--genbank-table', required=True, help='Path to GenBank table (CSV/TSV)')
    p.add_argument('--out', default='joined.tsv', help='Output path (CSV/TSV). Defaults to joined.tsv in CWD')
    p.add_argument('--format', choices=['csv', 'tsv'], default=None, help='Output format; if omitted, inferred from --out extension or defaults to csv')

    p.add_argument('--sra-biosample-col', default='BioSample', help='Column name in SRA table with BioSample (default: BioSample)')
    p.add_argument('--gb-biosample-col', default='BioSample', help='Column name in GenBank table with BioSample (default: BioSample)')
    p.add_argument('--gb-accession-col', default='accession', help='Column name in GenBank table for accession (default: accession)')
    p.add_argument('--gb-title-col', default='title', help='Column name in GenBank table for title (default: title)')

    args = p.parse_args()

    # read inputs with inferred separator
    sra_kwargs = infer_sep(args.sra_table)
    gb_kwargs = infer_sep(args.genbank_table)
    try:
        sra_df = pd.read_csv(args.sra_table, **sra_kwargs)
    except Exception as e:
        print(f"Failed to read SRA table '{args.sra_table}': {e}", file=sys.stderr)
        sys.exit(2)
    try:
        gb_df = pd.read_csv(args.genbank_table, **gb_kwargs)
    except Exception as e:
        print(f"Failed to read GenBank table '{args.genbank_table}': {e}", file=sys.stderr)
        sys.exit(2)

    # find actual column names (case-insensitive)
    sra_bio_col = find_column(sra_df, args.sra_biosample_col)
    if sra_bio_col is None:
        print(f"SRA table does not contain a column matching '{args.sra_biosample_col}'", file=sys.stderr)
        sys.exit(3)
    gb_bio_col = find_column(gb_df, args.gb_biosample_col)
    if gb_bio_col is None:
        print(f"GenBank table does not contain a column matching '{args.gb_biosample_col}'", file=sys.stderr)
        sys.exit(3)

    gb_acc_col = find_column(gb_df, args.gb_accession_col)
    if gb_acc_col is None:
        # try some common alternatives
        for alt in ['accession', 'genbank_accession', 'Accession', 'accession.version', 'AccessionVersion']:
            if find_column(gb_df, alt):
                gb_acc_col = find_column(gb_df, alt)
                break
    if gb_acc_col is None:
        print(f"GenBank table does not contain an accession column; tried '{args.gb_accession_col}' and common alternatives.", file=sys.stderr)
        sys.exit(3)

    gb_title_col = find_column(gb_df, args.gb_title_col)
    if gb_title_col is None:
        for alt in ['title', 'genbank_title', 'Title']:
            if find_column(gb_df, alt):
                gb_title_col = find_column(gb_df, alt)
                break
    if gb_title_col is None:
        # if no title column, create an empty title column
        gb_df['__genbank_title_empty'] = ''
        gb_title_col = '__genbank_title_empty'

    # detect a date column in the GenBank table (common variants)
    gb_date_col = None
    for cand in ['genbank_date', 'date', 'PubDate', 'CreateDate', 'UpdateDate', 'Pdat', 'collection_date', 'release_date', 'pub_date']:
        if find_column(gb_df, cand):
            gb_date_col = find_column(gb_df, cand)
            break

    # aggregate genbank records by biosample
    agg = aggregate_genbank(gb_df, gb_bio_col, gb_acc_col, gb_title_col, gb_date_col)

    # now left-join SRA table with aggregated genbank on biosample
    # normalize sra biosample column to string
    sra_df[sra_bio_col] = sra_df[sra_bio_col].astype(str).str.strip()
    agg[gb_bio_col] = agg[gb_bio_col].astype(str).str.strip()

    joined = sra_df.merge(agg, how='left', left_on=sra_bio_col, right_on=gb_bio_col)

    # drop the redundant gb_bio_col (right side) if it's different from sra_bio_col
    if gb_bio_col in joined.columns and gb_bio_col != sra_bio_col:
        joined = joined.drop(columns=[gb_bio_col])

    # choose output separator
    if args.format == 'tsv':
        out_sep = '\t'
    elif args.format == 'csv':
        out_sep = ','
    else:
        if args.out and Path(args.out).suffix.lower() in ['.tsv', '.txt']:
            out_sep = '\t'
        else:
            out_sep = ','

    # ensure output directory exists and write output file
    out_path = Path(args.out)
    if out_path.parent and str(out_path.parent) != '.':
        out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        joined.to_csv(out_path, index=False, sep=out_sep)
        print(f"Wrote joined table to {out_path}")
    except Exception as e:
        print(f"Failed to write output file '{out_path}': {e}", file=sys.stderr)
        sys.exit(4)


if __name__ == '__main__':
    main()

