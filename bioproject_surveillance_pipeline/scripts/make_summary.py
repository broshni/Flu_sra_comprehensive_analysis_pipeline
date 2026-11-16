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


def list_outputs(output_dir: Path, report_dir: Path, ws_base=None):
    """Return (html_reports, all_files) with paths relative to report_dir,
    or as BV-BRC workspace paths when ws_base is given (local copies get deleted)."""
    html_reports = []
    all_files = []
    if not output_dir.is_dir():
        return html_reports, all_files
    for p in sorted(output_dir.rglob("*")):
        if p.is_file():
            all_files.append(p)
            if p.suffix.lower() in (".html", ".htm"):
                html_reports.append(p)
    if ws_base:
        job_folder = ws_base.rsplit("/", 1)[-1]  # .assembly or .annotation

        def loc(p):
            parts = p.relative_to(output_dir).parts
            if parts and parts[0] == job_folder:  # p3-cp may or may not nest the job folder
                parts = parts[1:]
            return "/".join((ws_base,) + parts)
    else:
        def loc(p):
            return rel(p, report_dir)
    return (
        [loc(p) for p in html_reports],
        [(p.name, loc(p)) for p in all_files if p.name != ".snakemake_timestamp"],
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
    ap.add_argument("--workspace-path", default=None,
                    help="BV-BRC workspace folder of this sample; links point there instead of local files")
    args = ap.parse_args()
    ws = args.workspace_path.rstrip("/") if args.workspace_path else None

    report_dir = args.output.parent
    report_dir.mkdir(parents=True, exist_ok=True)

    assembly_job = args.assembly_jobid.read_text().strip()
    annotation_job = args.annotation_jobid.read_text().strip()

    assembly_html, assembly_files = list_outputs(args.assembly_dir, report_dir, ws and f"{ws}/.assembly")
    annotation_html, annotation_files = list_outputs(args.annotation_dir, report_dir, ws and f"{ws}/.annotation")

    lines = []
    lines.append(f"# Comprehensive analysis summary: {args.sample}")
    lines.append("")
    if ws:
        lines.append(f"All outputs are in the BV-BRC workspace folder `{ws}` "
                     "(paths below are workspace paths).")
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

    job_failed = assembly_job.startswith("FAILED")
    failed_id = assembly_job[len("FAILED"):].strip()
    lines.append(f"- BV-BRC job ID: `{(failed_id or 'not submitted') if job_failed else assembly_job}`")
    if job_failed:
        lines.append(
            "- **The BV-BRC assembly job failed or timed out**, so there are no "
            "contigs and annotation was skipped. Check this sample's "
            "`bvbrc_submit_assembly.log`. To retry, rerun the pipeline command with "
            "`--forcerun` followed by this sample's `assembly/job_id.txt`."
        )
    elif no_contigs:
        lines.append(
            "- **No assembled contigs were produced.** IRMA completed but "
            "assembled zero usable segments for this sample (low coverage, "
            "wrong module, or a poor-quality sample are common causes) -- "
            "check the assembly report/logs below. Annotation was skipped."
        )
    else:
        contigs_loc = f"{ws}/uploads/contigs.fasta" if ws else rel(args.contigs, report_dir)
        lines.append(f"- Assembled contigs: [{args.contigs.name}]({contigs_loc})")
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
