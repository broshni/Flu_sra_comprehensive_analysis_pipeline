#!/usr/bin/env python3
"""
Read the HA / NA subtype of one sample from its BV-BRC IRMA assembly output.

IRMA writes one FASTA per assembled segment and puts the subtype in the name:
    A_HA_H5.fasta  A_NA_N1.fasta  A_PB2.fasta ... (influenza A)
    B_HA.fasta     B_NA.fasta ...                 (influenza B -- no H/N subtype)
and the combined contigs FASTA uses the same names as headers (>A_HA_H5).

File names are used first; the contigs.fasta headers are the fallback.
Writes a one-row TSV:
    sra_accession, assembly_status, flu_type, n_segments, segments, ha_subtypes, na_subtypes

Usage: assembly_subtype.py --sample SRR... --assembly-dir <bvbrc_output> --contigs contigs.fasta --output out.tsv
"""
import argparse
import csv
import re
from pathlib import Path

SEGMENTS = ["PB2", "PB1", "PA", "HA", "NP", "NA", "MP", "M", "NS"]
# A_HA_H5, A_NA_N1, A_PB2, B_HA ... (optionally with a .fasta/.fa extension)
IRMA_NAME = re.compile(r"^([AB])_(" + "|".join(SEGMENTS) + r")(?:_([HN]\d{1,2}))?$", re.IGNORECASE)
FASTA_EXT = {".fasta", ".fa", ".fna", ".fas"}


def find_fasta_dir(src_dir: Path) -> Path:
    """Same rule as pick_contigs.py: shallowest directory that holds FASTA files."""
    if any(p.suffix.lower() in FASTA_EXT for p in src_dir.glob("*")):
        return src_dir
    for p in sorted(src_dir.rglob("*")):
        if p.is_dir() and "IRMA" not in p.parts and any(q.suffix.lower() in FASTA_EXT for q in p.glob("*")):
            return p
    return src_dir


def names_from_files(fasta_dir: Path):
    return [p.stem for p in fasta_dir.glob("*")
            if p.is_file() and p.suffix.lower() in FASTA_EXT and p.stat().st_size > 0]


def names_from_headers(contigs: Path):
    if not contigs.is_file():
        return []
    with open(contigs) as fh:
        return [line[1:].split()[0] for line in fh if line.startswith(">") and len(line) > 1]


def parse(names):
    flu_types, segments, ha, na = set(), set(), set(), set()
    for name in names:
        m = IRMA_NAME.match(name)
        if not m:
            continue
        flu, seg, sub = m.group(1).upper(), m.group(2).upper(), (m.group(3) or "").upper()
        flu_types.add(flu)
        segments.add(seg)
        if seg == "HA" and sub.startswith("H"):
            ha.add(sub)
        if seg == "NA" and sub.startswith("N"):
            na.add(sub)
    return flu_types, segments, ha, na


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--assembly-dir", required=True, type=Path)
    ap.add_argument("--contigs", required=True, type=Path)
    ap.add_argument("--assembly-jobid", type=Path, default=None,
                    help="assembly job_id.txt; 'FAILED ...' means the BV-BRC job failed or timed out")
    ap.add_argument("--output", required=True, type=Path)
    a = ap.parse_args()

    job_failed = (a.assembly_jobid is not None and a.assembly_jobid.is_file()
                  and a.assembly_jobid.read_text().startswith("FAILED"))

    names = names_from_files(find_fasta_dir(a.assembly_dir)) if a.assembly_dir.is_dir() else []
    flu_types, segments, ha, na = parse(names)
    if not segments:  # fallback: headers of the combined contigs file
        flu_types, segments, ha, na = parse(names_from_headers(a.contigs))

    if job_failed:
        status = "assembly job failed"
    else:
        status = "ok" if segments else "no segments assembled"
    order = {s: i for i, s in enumerate(SEGMENTS)}
    row = {
        "sra_accession": a.sample,
        "assembly_status": status,
        "flu_type": ",".join(sorted(flu_types)),
        "n_segments": len(segments),
        "segments": ",".join(sorted(segments, key=order.get)),
        "ha_subtypes": ",".join(sorted(ha, key=lambda s: int(s[1:]))),
        "na_subtypes": ",".join(sorted(na, key=lambda s: int(s[1:]))),
    }
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with open(a.output, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row), delimiter="\t")
        w.writeheader()
        w.writerow(row)
    print(row)


if __name__ == "__main__":
    main()
