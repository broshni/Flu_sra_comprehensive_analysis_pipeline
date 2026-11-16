# Viral SRA -> BV-BRC Assembly + Annotation Pipeline

A Snakemake pipeline that takes an SRA run accession for a viral sample and
runs it through IRMA-based genome assembly and genome annotation using
BV-BRC's command line interface (`p3-tools`) -- the same services behind
bv-brc.org, submitted from the command line. You give it one or more SRA
accessions (directly, or via a TSV); if you instead want to start from a
list of BioProjects and have it work out *which* SRA runs are worth
assembling, see the sibling `sra_selection_pipeline/` in this repo.

## Pipeline steps

1. **Assembly** -- the SRA run accession is submitted directly to BV-BRC's
   IRMA-based Viral Assembly service (`p3-submit-viral-assembly`). BV-BRC
   downloads the reads from SRA and runs IRMA's own internal QC (adapter/
   quality filtering happens as part of IRMA's iterative refinement process)
   itself, so there's no separate local download or QC step. The pipeline
   waits for the job and downloads the resulting contigs (one FASTA per
   genome segment for segmented viruses like influenza) plus the assembly
   report.
2. **Annotation** -- the assembled contigs (BV-BRC's own combined
   `..._all.fasta`, used as-is -- see caveats below) are submitted to the
   BV-BRC Genome Annotation service (`p3-submit-genome-annotation`, recipe
   `viral-lowvan`), which uses VIGOR4 for viral genomes; the pipeline waits
   and downloads the annotation output. If IRMA assembled zero usable contigs
   for a sample, annotation is skipped for that sample (with a clear note in
   its summary report) instead of failing the whole run.
3. **Summary** -- a per-sample Markdown report (`summary_report.md`) links
   the assembly/annotation job IDs and every output file BV-BRC produced.

## Requirements

- Snakemake 8 or newer (`pip install snakemake` or `conda install -c bioconda snakemake`)
- **The BV-BRC command line interface (`p3-tools`)**, installed separately --
  it is not a Python/conda package. Download an installer for your OS from
  https://github.com/BV-BRC/BV-BRC-CLI/releases and follow BV-BRC's install
  docs: https://www.bv-brc.org/docs/cli_tutorial/cli_installation.html
- Specifically, **`p3-submit-viral-assembly`** on your PATH. This command
  isn't (yet) documented on bv-brc.org's public docs site -- run
  `p3-submit-viral-assembly --help` on your machine and sanity-check its
  flags against what `Snakefile` passes (`--srr-id`, `--strategy`, plus the
  usual `output-path output-name` positional args) before depending on this
  pipeline for anything important.
- A [BV-BRC](https://www.bv-brc.org/) account (free), logged in **before**
  running the pipeline:
  ```
  p3-login <your-username>
  ```
  The pipeline checks `p3-whoami` and fails fast with a clear message if
  you're not logged in. Login tokens are long-lived, so you generally only
  need to do this once per machine.

## Setup

```
cp config.yaml.example config.yaml
cp samples.tsv.example samples.tsv
```

Edit `config.yaml` and fill in `bvbrc.username` and `bvbrc.workspace_base`
at minimum. `config.yaml` and `samples.tsv` are both gitignored, so your
real values never get committed.

## Configuration

Samples can come from three places, checked in this order:

1. **A single SRA id (or list) on the command line** -- no file editing needed:
   ```
   snakemake --cores 4 --keep-going --config srr=SRR28752452
   snakemake --cores 4 --keep-going --config srr=SRR28752452,SRR11111111
   ```
   Add `scientific_name=... taxonomy_id=...` to the same `--config` to apply
   that metadata to every accession in the list, e.g.
   `--config srr=SRR28752452 scientific_name="Influenza A virus" taxonomy_id=11320`.
2. **`samples_tsv` in `config.yaml`** (or override it per-run with
   `--config samples_tsv=other.tsv`) -- a tab-separated file with a header
   row and a run-accession column named `srr` (this pipeline's own
   convention), `Run` (matches SRA Run Selector's export column name
   directly), or `sra_accession` (a common convention in other lab scripts)
   -- any of these let a TSV be pointed at with no renaming; `scientific_name`,
   `reference_virus`, and `taxonomy_id` columns are optional (same meaning as
   the inline fields below -- blank is fine). Extra columns are ignored, so a
   TSV built for another script (e.g. one with a `genbank_accessions` column,
   or a full SRA RunInfo table) can usually be reused as-is. See
   `samples.tsv.example` for the format.
3. **The inline `samples:` block in `config.yaml`** -- used only if neither
   of the above is set.

**Batch folder for multi-sample runs.** Whenever a run resolves to more than
one sample (a comma-separated `srr` list, or a `samples_tsv`/inline `samples:`
block with more than one row), you must also pass `--config batch_name=<name>`.
That groups the whole run's outputs into their own subfolder --
`results/<batch_name>/<sample>/...`, `logs/<batch_name>/<sample>/...`, and
`workspace_base/<batch_name>/<sample>/...` on BV-BRC -- instead of mixing with
other runs' per-sample folders at the top level. Forgetting `batch_name` on a
multi-sample run fails fast with a clear error before anything is submitted.
Single-accession runs are unaffected and keep writing straight to
`results/<sample>/...` as before -- no `batch_name` needed. Example:

```
snakemake --cores 4 --keep-going --config samples_tsv=samples.tsv batch_name=flu_panel_2026_08
```

**Local disk cleanup for big batches.** Pass `--config cleanup_local=true` to
delete each sample's local `bvbrc_output/` dirs, `contigs.fasta`, and
`job_id.txt` as soon as that sample's `summary_report.md` is written, keeping
only the summary report on disk. Safe because everything deleted is already
stored in your BV-BRC workspace -- re-download anything you need later with
`p3-cp -r ws:<workspace_path> <local_dir>`. Off by default. Example:

```
snakemake --cores 4 --keep-going --config samples_tsv=samples.tsv batch_name=flu_panel_2026_08 cleanup_local=true
```

Other `config.yaml` fields:

- `samples`: fallback if neither `srr` nor `samples_tsv` is set. One entry per SRA run. Set `srr`, a `scientific_name`, and
  optionally `reference_virus` (an exact name from BV-BRC's VIGOR_DB
  collection, e.g. `"Influenza A"`) if you want to force a specific
  reference for annotation, and/or `taxonomy_id` (NCBI taxon id; defaults to
  `11320` = Influenza A virus species in the example) -- leave either blank
  to let BV-BRC/VIGOR4 infer it.
- `bvbrc.username` / `bvbrc.workspace_base`: your BV-BRC username and the
  workspace path where job outputs will be stored
  (`/<username>@bvbrc/home/...`).
- `bvbrc.viral_assembly_strategy`: passed as `--strategy` to
  `p3-submit-viral-assembly`. IRMA is currently BV-BRC's only viral assembly
  strategy, so this defaults to `"IRMA"`.
- `bvbrc.annotation_recipe` / `bvbrc.genetic_code` / `bvbrc.domain`: passed to
  `p3-submit-genome-annotation`. Defaults (`viral-lowvan`, `11`, `"Bacteria"`)
  match a working BV-BRC influenza annotation pipeline -- yes, `domain:
  Bacteria` is correct even for a virus; BV-BRC's schema has no "Virus"
  option and requires this field.
- `bvbrc.public`: whether annotated genomes are submitted with `--public`
  (visible to other BV-BRC users). Set to `false` to keep them private.
- `bvbrc.poll_interval_sec` / `bvbrc.timeout_sec`: how often to check job
  status and how long to wait before giving up.

## Running

```
snakemake --cores 4 --keep-going
```

`--keep-going` is recommended for multi-sample runs: if BV-BRC job
submission genuinely fails or times out for one sample (as opposed to the
"IRMA ran but assembled nothing" case, which the pipeline already handles
gracefully on its own -- see below), this keeps Snakemake processing your
other samples instead of aborting the whole run.

Add more samples to `samples.tsv` (or `config.yaml`'s inline `samples:` block)
and Snakemake will process them all -- the BV-BRC steps for different samples
run as separate jobs on BV-BRC's servers, so submitting several at once is
fine.

See `RUNNING.md` for a full command reference (every way to supply samples,
useful flags, worked examples).

Outputs land under `results/<sample>/`:

```
results/<sample>/
├── assembly/
│   ├── job_id.txt
│   ├── contigs.fasta            # combined/concatenated if IRMA emitted per-segment FASTAs
│   └── bvbrc_output/             # everything BV-BRC produced (assembly report, per-segment FASTAs, etc.)
├── annotation/
│   ├── job_id.txt
│   └── bvbrc_output/             # genome report, features, .gto, etc.
└── summary_report.md
```

## Notes / caveats

- BV-BRC job submission and polling happen inside the Snakemake rules via
  `scripts/bvbrc_submit_and_wait.sh`, which blocks until the job finishes (or
  times out). This means a rule occupies one Snakemake core for the whole
  wall-clock duration of the remote job -- bump `--cores` if you're running
  many samples concurrently.
- Confirmed IRMA output layout (from a real run): one FASTA per genome
  segment (`A_HA_H4.fasta`, `A_MP.fasta`, `A_NA_N6.fasta`, ...), a combined
  `<jobname>_all.fasta` with every segment already concatenated,
  `AssemblyReport.html`, a `quast/` folder, an `IRMA/` folder with
  intermediate working files, and -- notably -- the raw reads BV-BRC
  downloaded from SRA (`<SRR>_1.fastq`, `<SRR>_2.fastq`, a `<SRR>/` staging
  folder). `scripts/pick_contigs.py` picks the `_all.fasta` file when present
  (falling back to concatenating the per-segment files itself if not). Check
  `results/<sample>/assembly/bvbrc_output/` if this picks the wrong thing for
  an unusual output layout.
- After fetching, the `bvbrc_fetch_assembly` rule deletes the local copies
  of the raw `<SRR>_*.fastq` files and `<SRR>/` folder (100s of MB, already in
  SRA). `p3-cp` nests them under `bvbrc_output/.assembly/`, and the rule looks
  there too.
- `p3-submit-viral-assembly` was provided directly rather than pulled from
  BV-BRC's public docs (which only describe the underlying IRMA service
  through its web form, currently marked Beta). If your installed CLI
  version has a different name/flags, update the `p3-submit-viral-assembly`
  call in `Snakefile`'s `bvbrc_submit_assembly` rule accordingly.
- If IRMA assembles zero usable contigs for a sample, `pick_contigs.py`
  writes an empty `contigs.fasta` instead of failing (caveat: if no FASTA sits
  at the top of the assembly output, it searches subfolders, and could pick
  up IRMA's intermediate files under `IRMA/` instead -- check that sample's
  `pick_contigs.log`), and
  `bvbrc_submit_annotation` detects that empty file and skips submitting an
  annotation job for that sample -- it writes `SKIPPED` to that sample's
  `annotation/job_id.txt` and moves on. The sample's `summary_report.md`
  notes this clearly instead of silently pretending annotation happened.
- A BV-BRC job that fails or times out stops that sample (with
  `--keep-going`, the other samples carry on). Rerunning the same command
  resubmits only the samples that didn't finish.
- `profiles/default/config.yaml` (loaded automatically by Snakemake 8+) sets
  `rerun-triggers: [mtime, params]`, so editing the `Snakefile` or scripts
  never makes Snakemake resubmit BV-BRC jobs for samples that already
  finished. Use `--forcerun <file or rule>` when you do want something redone.
- BV-BRC also has other virus-specific services worth knowing about if they
  fit your sample better: `p3-submit-sars2-assembly` /
  `p3-submit-sars2-analysis` for SARS-CoV-2 specifically.
