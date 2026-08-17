#!/usr/bin/env python3
"""
Find nucleotide (nuccore) accessions linked to a BioSample accession.

Requires: Biopython (Entrez) and pandas (optional for DataFrame output)

Single BioSample: python biosample_to_genbank.py SAMN12345678 --email youremail@example.com --out results.csv
Multiple BioSamples from CSV (CSV must have a column with accessions; default column name is 'BioSample'): python biosample_to_nuccore.py --input_csv biosamples.csv --email youremail@example.com --out results.csv
If your CSV uses a different column name, e.g. 'sample_id': python biosample_to_genbank.py --input_csv biosamples.csv --column sample_id --email youremail@example.com --out results.csv

Example:
    python biosample_to_genbank.py SAMN12345678 --email youremail@example.com --out results.csv
    python biosample_to_genbank.py --input_csv biosamples.csv --email your_email@example.com --out results.csv
    python biosample_to_genbank.py --input_csv samples.tsv --email youremail@example.com --out results.tsv --format tsv

Note:
    This script now attempts to capture a GenBank date for each accession (from esummary fields
    such as PubDate, CreateDate, UpdateDate, Pdat or Date) and includes it in the output
    column 'genbank_date'. If unavailable, the field is empty.

"""

import time
import argparse
from typing import Optional
from Bio import Entrez
import pandas as pd


def biosample_to_nucleotide(
    biosample_acc: str,
    email: str,
    api_key: Optional[str] = None,
    sleep: float = 0.34,
    use_efetch_date: bool = False,
) -> pd.DataFrame:
    """
    Given a BioSample accession (e.g. 'SAMN...'), return a DataFrame listing linked nuccore records.

    Columns returned: Biosample, biosample_uid, nuccore_uid, accession (Caption/AccessionVersion), title, genbank_date, genbank_date_source
    """
    Entrez.email = email
    if api_key:
        Entrez.api_key = api_key

    # 1) find BioSample UID
    # use a broad search term including the accession; should catch SAMN*, etc.
    with Entrez.esearch(db="biosample", term=f'"{biosample_acc}"[All]') as h:
        search = Entrez.read(h)
    idlist = search.get("IdList", [])
    if not idlist:
        raise ValueError(f"No BioSample found for accession '{biosample_acc}'")

    biosample_uid = idlist[0]

    # 2) get linked nuccore ids
    with Entrez.elink(dbfrom="biosample", db="nuccore", id=biosample_uid) as h:
        linkset = Entrez.read(h)

    linksetdb = linkset[0].get("LinkSetDb", [])
    if not linksetdb:
        # no direct nuccore links; return empty DataFrame
        return pd.DataFrame(
            columns=["Biosample", "biosample_uid", "nuccore_uid", "accession", "title", "genbank_date", "genbank_date_source"]
        )

    nuccore_ids = [link["Id"] for link in linksetdb[0].get("Link", [])]
    if not nuccore_ids:
        return pd.DataFrame(
            columns=["Biosample", "biosample_uid", "nuccore_uid", "accession", "title", "genbank_date", "genbank_date_source"]
        )

    # 3) fetch summaries (in batches) to get accession/title and date
    rows = []
    batch_size = 200  # esummary can handle larger batches, but 200 is safe
    for i in range(0, len(nuccore_ids), batch_size):
        batch = nuccore_ids[i : i + batch_size]
        id_str = ",".join(batch)
        with Entrez.esummary(db="nuccore", id=id_str) as h:
            summaries = Entrez.read(h)
        # Entrez.read for esummary returns a list of dicts (one per id)
        # Each dict usually has keys like 'Caption' and 'Title' and sometimes 'PubDate' or 'CreateDate'
        for summary in summaries:
            # some fields might differ; try common keys
            accession = summary.get("Caption") or summary.get("AccessionVersion") or ""
            title = summary.get("Title") or ""
            # common date fields returned by esummary: PubDate, CreateDate, UpdateDate, Pdat, Date
            genbank_date = ""
            genbank_date_source = ""
            if summary.get("PubDate"):
                genbank_date = summary.get("PubDate")
                genbank_date_source = "esummary:PubDate"
            elif summary.get("CreateDate"):
                genbank_date = summary.get("CreateDate")
                genbank_date_source = "esummary:CreateDate"
            elif summary.get("UpdateDate"):
                genbank_date = summary.get("UpdateDate")
                genbank_date_source = "esummary:UpdateDate"
            elif summary.get("Pdat"):
                genbank_date = summary.get("Pdat")
                genbank_date_source = "esummary:Pdat"
            elif summary.get("Date"):
                genbank_date = summary.get("Date")
                genbank_date_source = "esummary:Date"
            else:
                genbank_date = ""
                genbank_date_source = ""
            # if still empty and requested, try fetching the full GenBank record to extract a date
            if not genbank_date and use_efetch_date and accession:
                try:
                    # Fetch XML and try to extract create/update dates which better reflect submission/publication
                    with Entrez.efetch(db="nuccore", id=summary.get("Id", ""), retmode="xml") as h2:
                        xml_text = h2.read()
                        if isinstance(xml_text, bytes):
                            xml_text = xml_text.decode('utf-8', errors='ignore')
                        # look for GBSeq_create-date or GBSeq_update-date
                        import re

                        m = re.search(r"<GBSeq_create-date>([^<]+)</GBSeq_create-date>", xml_text)
                        if m:
                            genbank_date = m.group(1)
                            genbank_date_source = "efetch:GBSeq_create-date"
                        else:
                            m2 = re.search(r"<GBSeq_update-date>([^<]+)</GBSeq_update-date>", xml_text)
                            if m2:
                                genbank_date = m2.group(1)
                                genbank_date_source = "efetch:GBSeq_update-date"
                except Exception:
                    # ignore efetch/xml failures and keep genbank_date empty
                    pass
            rows.append(
                {
                    "Biosample": biosample_acc,
                    "biosample_uid": biosample_uid,
                    "nuccore_uid": summary.get("Id", ""),
                    "accession": accession,
                    "title": title,
                    "genbank_date": genbank_date,
                    "genbank_date_source": genbank_date_source,
                }
            )
        time.sleep(sleep)

    df = pd.DataFrame(rows)
    return df


def main():
    p = argparse.ArgumentParser(description="Map a BioSample accession to linked nuccore accessions")
    # allow either a positional biosample or an input CSV for batch mode
    p.add_argument("biosample", nargs='?', help="BioSample accession (e.g. SAMN12345678)")
    p.add_argument("--email", required=True, help="Your email (required by NCBI Entrez)")
    p.add_argument("--api_key", help="NCBI API key (optional)", default=None)
    p.add_argument("--out", help="Output CSV/TSV file (optional)", default=None)
    p.add_argument("--input_csv", "-i", help="CSV/TSV file with BioSample accessions (one column)", default=None)
    p.add_argument("--column", "-c", help="Column name in input file containing biosample accessions (default: BioSample)", default="BioSample")
    p.add_argument("--format", "-f", choices=["csv", "tsv"], default=None, help="Output format (csv or tsv). If omitted, inferred from --out extension or defaults to csv")
    p.add_argument('--efetch-date', action='store_true', help='If set, when esummary lacks a date, fetch the full GenBank record to try to extract a date (slower)')
    args = p.parse_args()

    def _infer_input_sep(path: str) -> dict:
        if not path:
            return {}
        low = path.lower()
        if low.endswith('.tsv') or low.endswith('.txt'):
            return {'sep': '\t'}
        return {}

    def _choose_sep_for_output(args) -> str:
        if args.format:
            return '\t' if args.format == 'tsv' else ','
        if args.out:
            low = args.out.lower()
            if low.endswith('.tsv') or low.endswith('.txt'):
                return '\t'
        return ','

    # Batch mode: input CSV provided
    if args.input_csv:
        try:
            read_kwargs = _infer_input_sep(args.input_csv)
            df_input = pd.read_csv(args.input_csv, **read_kwargs)
        except Exception as e:
            print(f"Failed to read input CSV '{args.input_csv}': {e}")
            return

        # try to find the requested column, case-insensitive fallback
        col = args.column
        if col not in df_input.columns:
            matches = [c for c in df_input.columns if c.lower() == col.lower()]
            if matches:
                col = matches[0]
            else:
                # fallback to first column
                col = df_input.columns[0]
                print(f"Column '{args.column}' not found; using first column '{col}' as biosample column")

        biosamples = df_input[col].dropna().astype(str).unique().tolist()
        print(f"Found {len(biosamples)} unique biosample accessions in '{args.input_csv}' (column '{col}')")

        all_rows = []
        for idx, bs in enumerate(biosamples, 1):
            print(f"[{idx}/{len(biosamples)}] Processing BioSample {bs}...")
            try:
                df_bs = biosample_to_nucleotide(bs, args.email, api_key=args.api_key, use_efetch_date=args.efetch_date)
                if not df_bs.empty:
                    all_rows.append(df_bs)
            except Exception as e:
                print(f"  Error processing {bs}: {e}")
            # small delay to be gentle to NCBI
            time.sleep(0.34)

        if all_rows:
            combined = pd.concat(all_rows, ignore_index=True)
        else:
            combined = pd.DataFrame(columns=["Biosample", "biosample_uid", "nuccore_uid", "accession", "title", "genbank_date", "genbank_date_source"])

        sep_out = _choose_sep_for_output(args)
        if args.out:
            try:
                combined.to_csv(args.out, index=False, sep=sep_out)
                print(f"Wrote combined results for {len(biosamples)} biosamples to {args.out}")
            except Exception as e:
                print(f"Failed to write output file '{args.out}': {e}")
        else:
            # print to stdout using chosen separator
            if combined.empty:
                print("No linked nuccore records found for the provided biosamples.")
            else:
                # print as CSV/TSV
                print(combined.to_csv(index=False, sep=sep_out))

        return

    # Single biosample positional argument mode
    if not args.biosample:
        print("Either provide a single biosample accession as positional argument or use --input_csv to supply a CSV file.")
        return

    try:
        df = biosample_to_nucleotide(args.biosample, args.email, api_key=args.api_key, use_efetch_date=args.efetch_date)
    except Exception as e:
        print(f"Error: {e}")
        return

    if df.empty:
        print(f"No linked nuccore (nucleotide) records found for BioSample {args.biosample}")
    else:
        # print using inferred output sep (if user requests TSV via --format or --out ext)
        sep_out = _choose_sep_for_output(args)
        print(df.to_csv(index=False, sep=sep_out))

    if args.out:
        try:
            sep_out = _choose_sep_for_output(args)
            df.to_csv(args.out, index=False, sep=sep_out)
            print(f"Wrote results to {args.out}")
        except Exception as e:
            print(f"Failed to write output CSV '{args.out}': {e}")


if __name__ == "__main__":
    main()
