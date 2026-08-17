#!/usr/bin/env python3
"""
Locate/build a single "contigs" FASTA file from a downloaded BV-BRC IRMA
Viral Assembly output directory, suitable for feeding into
p3-submit-genome-annotation --contigs-file.

Confirmed IRMA output layout (from a real run) sits flat in the job's
output directory and looks like:

    A_HA_H4.fasta
    A_MP.fasta
    A_NA_N6.fasta
    A_NP.fasta
    A_NS.fasta
    A_PA.fasta
    A_PB1.fasta
    A_PB2.fasta
    AssemblyReport.html
    IRMA/                       <- nested working files (bam/vcf/logs/intermediate fastas)
    irma_<job>_all.fasta        <- all segments already combined into one file
    quast/
    SRR.../, SRR..._1.fastq, SRR..._2.fastq   <- raw reads BV-BRC downloaded from SRA

So this script:
  1. Only looks at the top level of the output directory (not recursively --
     the nested IRMA/ folder can contain its own per-round/per-segment
     FASTAs we don't want to double-count).
  2. Prefers a file whose name ends in "_all" (the already-combined,
     all-segments assembly IRMA produces) if one exists.
  3. Otherwise prefers a file whose name contains an explicit "combined"-type
     hint (contigs/cumulative/combined/all_segments).
  4. Otherwise, if there's exactly one FASTA candidate, uses it directly.
  5. Otherwise (multiple per-segment FASTAs, no combined file), concatenates
     all of them into one multi-contig FASTA.
  6. If no FASTA files are found at all (assembly completed but produced no
     usable contigs), writes an empty output file and exits 0 rather than
     failing -- the annotation step checks for this and skips itself with a
     clear message instead of hard-failing the whole sample.

Usage: pick_contigs.py <bvbrc_output_dir> <output_contigs.fasta>
"""
import sys
from pathlib import Path

EXCLUDE_HINTS = ("report", "reference", "ref.", "quast")
COMBINED_HINTS = ("contigs", "cumulative", "combined", "all_segments", "all-segments")


def find_fasta_dir(src_dir: Path) -> Path:
    """IRMA output may be nested one level under the fetched directory
    (e.g. bvbrc_output/.assembly/...). Find the shallowest directory that
    actually contains FASTA files."""
    if list(src_dir.glob("*.fasta")) or list(src_dir.glob("*.fa")):
        return src_dir
    for p in sorted(src_dir.rglob("*")):
        if p.is_dir() and (list(p.glob("*.fasta")) or list(p.glob("*.fa"))):
            return p
    return src_dir


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <bvbrc_output_dir> <output_contigs.fasta>", file=sys.stderr)
        sys.exit(1)

    src_dir = Path(sys.argv[1])
    dest = Path(sys.argv[2])

    if not src_dir.is_dir():
        print(f"ERROR: {src_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    fasta_dir = find_fasta_dir(src_dir)

    # Top-level only -- deliberately not recursive, see module docstring.
    fasta_files = [
        p for p in fasta_dir.glob("*")
        if p.is_file() and p.suffix.lower() in (".fasta", ".fa", ".fna")
    ]

    if not fasta_files:
        # No usable assembly output -- e.g. IRMA completed but assembled zero
        # segments for this sample. Don't hard-fail the pipeline: write an
        # empty contigs file so downstream rules can detect this and skip
        # annotation for this sample (with a clear message) instead of
        # blocking the whole run.
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"")
        print(
            f"WARNING: no FASTA files found under {fasta_dir} -- assembly "
            f"produced no usable contigs. Writing an empty {dest} so "
            f"annotation will be skipped for this sample."
        )
        return

    candidates = [p for p in fasta_files if not any(h in p.name.lower() for h in EXCLUDE_HINTS)]
    if not candidates:
        candidates = fasta_files

    dest.parent.mkdir(parents=True, exist_ok=True)

    # 1. Files IRMA names "..._all.fasta" -- already all segments combined.
    all_suffix = [p for p in candidates if p.stem.lower().endswith("_all")]
    # 2. Other explicit "combined" naming hints.
    hinted = [p for p in candidates if any(h in p.name.lower() for h in COMBINED_HINTS)]

    combined = all_suffix or hinted
    if combined:
        chosen = max(combined, key=lambda p: p.stat().st_size)
        dest.write_bytes(chosen.read_bytes())
        print(f"Picked combined contigs file: {chosen} -> {dest}")
        return

    if len(candidates) == 1:
        dest.write_bytes(candidates[0].read_bytes())
        print(f"Picked contigs file: {candidates[0]} -> {dest}")
        return

    # Multiple per-segment FASTA files (typical IRMA output for segmented
    # viruses like influenza) -- concatenate them into one multi-contig file.
    with open(dest, "wb") as out:
        for p in sorted(candidates):
            data = p.read_bytes()
            out.write(data)
            if not data.endswith(b"\n"):
                out.write(b"\n")
    print(f"Concatenated {len(candidates)} segment FASTA files -> {dest}")
    for p in sorted(candidates):
        print(f"  - {p}")


if __name__ == "__main__":
    main()
