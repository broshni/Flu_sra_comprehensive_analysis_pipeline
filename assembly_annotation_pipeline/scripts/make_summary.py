#!/usr/bin/env python3
"""
Build a per-sample Markdown summary report tying together the BV-BRC IRMA
assembly + genome annotation job outputs.

This intentionally does not try to hard-code exact BV-BRC output file names
(they can change between service versions). Instead it walks the downloaded
BV-BRC output directories and links every HTML report it finds there
(IRMA/assembly report, QUAST report, annotation/genome report, etc.) plus
lists all other output files for reference. Read/QC statistics live inside
BV-BRC's own assembly report (IRMA downloads the SRA reads and performs its
own internal QC as part of assembly, so there's no separate local QC step).
"""
import argparse
import os
from pathlib import Path


def rel(path: Path, start: Path) -> str:
    return os.path.relpath(path, start=start)


def list_outputs(output_dir: Path, report_dir: Path):
    """Return (html_reports, all_files) with paths relative to report_dir."""
    html_reports = []
    all_files = []
    if not output_dir.is_dir():
        return html_reports, all_files
    for p in sorted(output_dir.rglob("*")):
        if p.is_file():
            all_files.append(p)
            if p.suffix.lower() in (".html", ".htm"):
                html_reports.append(p)
    return (
        [rel(p, report_dir) for p in html_reports],
        [(p.name, rel(p, report_dir)) for p in all_files],
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--assembly-dir", required=True, type=Path)
    ap.add_argument("--contigs", required=True, type=Path)
    ap.add_argument("--annotation-dir", required=True, type=Path)
    ap.add_argument("--assembly-jobid", required=True, type=Path)
    ap.add_argument("--annotation-jobid", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    report_dir = args.output.parent
    report_dir.mkdir(parents=True, exist_ok=True)

    assembly_job = args.assembly_jobid.read_text().strip()
    annotation_job = args.annotation_jobid.read_text().strip()

    assembly_html, assembly_files = list_outputs(args.assembly_dir, report_dir)
    annotation_html, annotation_files = list_outputs(args.annotation_dir, report_dir)

    lines = []
    lines.append(f"# Comprehensive analysis summary: {args.sample}")
    lines.append("")

    lines.append("## 1. BV-BRC IRMA Viral Assembly (read download, QC, and assembly)")
    lines.append("")
    lines.append(
        "BV-BRC fetched the reads for this sample directly from SRA and ran "
        "them through IRMA, which performs its own internal read QC/filtering "
        "as part of its iterative assembly process -- see the assembly report "
        "below for read and QC statistics."
    )
    lines.append("")
    no_contigs = args.contigs.stat().st_size == 0

    lines.append(f"- BV-BRC job ID: `{assembly_job}`")
    if no_contigs:
        lines.append(
            "- **No assembled contigs were produced.** IRMA completed but "
            "assembled zero usable segments for this sample (low coverage, "
            "wrong module, or a poor-quality sample are common causes) -- "
            "check the assembly report/logs below. Annotation was skipped."
        )
    else:
        lines.append(f"- Assembled contigs: [{args.contigs.name}]({rel(args.contigs, report_dir)})")
    if assembly_html:
        lines.append("- Reports:")
        for h in assembly_html:
            lines.append(f"  - [{Path(h).name}]({h})")
    lines.append("")
    lines.append("<details><summary>All assembly output files</summary>")
    lines.append("")
    for name, relpath in assembly_files:
        lines.append(f"- [{name}]({relpath})")
    lines.append("")
    lines.append("</details>")
    lines.append("")

    lines.append("## 2. BV-BRC Genome Annotation (VIGOR4)")
    lines.append("")
    if annotation_job == "SKIPPED":
        lines.append(
            "**Annotation was skipped for this sample** -- no assembled "
            "contigs were available from step 1 above."
        )
    else:
        lines.append(f"- BV-BRC job ID: `{annotation_job}`")
        if annotation_html:
            lines.append("- Reports:")
            for h in annotation_html:
                lines.append(f"  - [{Path(h).name}]({h})")
        lines.append("")
        lines.append("<details><summary>All annotation output files</summary>")
        lines.append("")
        for name, relpath in annotation_files:
            lines.append(f"- [{name}]({relpath})")
        lines.append("")
        lines.append("</details>")
    lines.append("")

    args.output.write_text("\n".join(lines))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
