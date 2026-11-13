#!/usr/bin/env python3
"""
Merge the NCBI metadata (from extract_sra_metadata.py) with each sample's
assembly-derived HA/NA subtype and write the final metadata workbook.

Subtype rule: the assembly wins. For H and N separately:
  - exactly one HA (NA) subtype in the assembly  -> use it
  - none in the assembly                         -> fall back to the BioSample metadata, flagged
  - more than one (mixed infection)              -> left blank, flagged
Any disagreement between assembly and BioSample is flagged in subtype_note.

Output sheets: Raw Data, BVBRC (+ assembly_status, assembled_segments,
subtype_source, subtype_note at the end), Assembly, Failed (if any NCBI lookups failed).
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_sra_metadata as esm  # noqa: E402


def split(v):
    return [] if esm.is_missing(v) else [x for x in str(v).split(",") if x]


def resolve(ha, na, meta_subtype, status, have_metadata):
    """Return (h, n, source, note) for one record."""
    m = re.match(r"H(\d+)N(\d+)$", meta_subtype or "")  # find_subtype() always returns HxNy
    meta_h, meta_n = (m.group(1), m.group(2)) if m else (None, None)
    notes, sources = [], []

    def pick(found, meta, seg, letter):
        if len(found) == 1:
            sources.append("assembly")
            return found[0][1:]
        if len(found) > 1:
            notes.append(f"multiple {seg} subtypes in assembly ({'/'.join(found)})")
            return None
        if status == "ok":
            notes.append(f"no {seg} segment assembled")
        if meta:
            sources.append("biosample")
            notes.append(f"{letter} type from BioSample")
            return meta
        return None

    h = pick(ha, meta_h, "HA", "H")
    n = pick(na, meta_n, "NA", "N")

    if status != "ok":
        if status == "no segments assembled":
            notes.insert(0, "assembly produced no segments")
        else:  # e.g. "assembly job failed"
            notes.insert(0, status or "no assembly result")
    if not have_metadata:
        notes.append("NCBI metadata not retrieved")
    if meta_subtype and (len(ha) == 1 or len(na) == 1):
        asm = f"H{ha[0][1:] if len(ha) == 1 else '?'}N{na[0][1:] if len(na) == 1 else '?'}"
        if (len(ha) == 1 and meta_h and ha[0][1:] != meta_h) or (len(na) == 1 and meta_n and na[0][1:] != meta_n):
            notes.append(f"assembly {asm} differs from BioSample {meta_subtype}")

    uniq = sorted(set(sources))
    source = "+".join(uniq) if uniq else ""
    return h, n, source, "; ".join(notes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metadata", required=True, type=Path, help="workbook from extract_sra_metadata.py")
    ap.add_argument("--assembly", required=True, nargs="+", type=Path, help="per-sample assembly_subtype.tsv files")
    ap.add_argument("--samples", required=True, nargs="+", help="all SRA accessions in this run")
    ap.add_argument("--geo", default=None, help="optional CSV to use instead of the built-in country table")
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--output-tsv", type=Path)
    a = ap.parse_args()

    sheets = pd.read_excel(a.metadata, sheet_name=None, dtype=str)
    raw = sheets.get("Raw Data", pd.DataFrame())
    failed = sheets.get("Failed")
    failed = list(failed.itertuples(index=False, name=None)) if failed is not None else []

    asm = pd.concat([pd.read_csv(p, sep="\t", dtype=str) for p in a.assembly], ignore_index=True)
    asm_by_run = asm.set_index("sra_accession")

    # every sample in the run gets a row, even if NCBI metadata could not be fetched
    if "Run" not in raw.columns:
        raw["Run"] = pd.Series(dtype=str)
    have = set(raw["Run"].dropna())
    missing = [s for s in a.samples if s not in have]
    if missing:
        raw = pd.concat([raw, pd.DataFrame({"Run": missing, "SRA_ID": missing})], ignore_index=True)
    order = {s: i for i, s in enumerate(a.samples)}
    raw = raw.assign(_o=raw["Run"].map(order)).sort_values("_o", kind="stable").drop(columns="_o")
    raw = raw.reset_index(drop=True)

    meta_sub = esm.metadata_subtypes(raw)
    h_types, n_types, sources, notes, statuses, segs = [], [], [], [], [], []
    for i, row in raw.iterrows():
        run = row["Run"]
        r = asm_by_run.loc[run] if run in asm_by_run.index else None
        status = "" if r is None else r["assembly_status"]
        h, n, src, note = resolve(
            split(None if r is None else r["ha_subtypes"]),
            split(None if r is None else r["na_subtypes"]),
            meta_sub.iloc[i], status, run in have)
        h_types.append(h); n_types.append(n); sources.append(src); notes.append(note)
        statuses.append(status or "not assembled")
        segs.append("" if r is None or esm.is_missing(r["segments"]) else r["segments"])

    groups = esm.load_country_geographic_groups(a.geo)
    out = esm.build_bvbrc_table(raw, groups, h_types=h_types, n_types=n_types,
                                location="country", subtype_suffix=True)
    out["sra_accession"] = raw["Run"].values  # filled for rows without NCBI metadata too
    out["assembly_status"] = statuses
    out["assembled_segments"] = segs
    out["subtype_source"] = sources
    out["subtype_note"] = notes

    a.output.parent.mkdir(parents=True, exist_ok=True)
    esm.write_workbook(a.output, raw, out, failed, extra_sheets={"Assembly": asm})
    if a.output_tsv:
        out.to_csv(a.output_tsv, sep="\t", index=False)

    flagged = out[out["subtype_note"] != ""]
    print(f"Wrote {len(out)} record(s) to {a.output}; {len(flagged)} with subtype notes")
    for _, r in flagged.iterrows():
        print(f"  {r['sra_accession']}: {r['subtype_note']}")


if __name__ == "__main__":
    main()
