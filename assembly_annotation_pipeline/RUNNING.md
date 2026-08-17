# How to Run This Pipeline

Quick reference for every way to run the pipeline. See `README.md` for full
background on what each step does.

## 0. One-time setup

```
p3-login <your-username>
```

Do this once per machine (login tokens are long-lived). The pipeline checks
`p3-whoami` and fails fast with a clear message if you're not logged in.

## 1. Pick how you want to supply samples

There are three ways to tell the pipeline which SRA runs to process. Pick
whichever fits what you're doing right now -- you don't need to edit
`Snakefile` to switch between them.

### Option A -- one-off: a single SRA id on the command line

```
snakemake --cores 4 --keep-going --config srr=SRR28752452
```

Optionally attach metadata (applied to that one id):

```
snakemake --cores 4 --keep-going --config srr=SRR28752452 scientific_name="Influenza A virus" taxonomy_id=11320
```

### Option B -- a few samples: a list on the command line

Comma-separated (or space/semicolon-separated, if you quote it). Because
this is more than one sample, you must also add `batch_name=<name>` so the
outputs get grouped into their own folder instead of mixing with other runs:

```
snakemake --cores 4 --keep-going --config srr=SRR28752452,SRR11111111,SRR22222222 batch_name=my_batch
```

Metadata applied via `--config` here applies to *every* id in the list, so
this is best when all the samples share the same virus/taxonomy. Leaving out
`batch_name` on a multi-id run stops with a clear error before anything is
submitted.

### Option C -- many samples / different metadata per sample: a TSV file

Best when samples need different `scientific_name` / `taxonomy_id` values, or
you already keep a running list of accessions in a spreadsheet.

1. Edit `samples.tsv` (tab-separated), one row per sample:

   ```
   srr	scientific_name	reference_virus	taxonomy_id
   SRR28752452	Influenza A virus		11320
   SRR11111111	Influenza A virus		11320
   ```

   The run-accession column can be named `srr`, `Run`, or `sra_accession` --
   all three are recognized, so you can point this straight at an SRA Run
   Selector export or another script's TSV without renaming its header. Only
   that one column is required; the rest can be left blank. Extra columns you
   don't use are ignored, so a TSV built for another script (or a full SRA
   RunInfo table) can usually be reused as-is.

2. Since a TSV normally has more than one row, add `batch_name=<name>` so
   these outputs get grouped into their own folder:

   ```
   snakemake --cores 4 --keep-going --config batch_name=my_batch
   ```

   To use a different TSV file for one run without editing `config.yaml`:

   ```
   snakemake --cores 4 --keep-going --config samples_tsv=other_samples.tsv batch_name=my_batch
   ```

   (If your TSV happens to have exactly one row, `batch_name` isn't required
   -- the requirement is based on how many samples actually get resolved,
   not which option you used to supply them.)

### Option D -- fallback: inline `samples:` block in `config.yaml`

Only used if neither `srr` nor `samples_tsv` is set (comment out or remove
the `samples_tsv:` line in `config.yaml` to fall back to this). Edit the
`samples:` block in `config.yaml` directly, same fields as the TSV.

**Priority if more than one is set at once:** `--config srr=...` overrides
everything; then `samples_tsv` (from `--config` or `config.yaml`); then the
inline `samples:` block.

**`batch_name` is required whenever more than one sample resolves**,
regardless of which option supplied them (comma list, TSV with multiple
rows, or inline `samples:` block with multiple entries). It groups that
run's outputs into `results/<batch_name>/<sample>/...`,
`logs/<batch_name>/<sample>/...`, and
`workspace_base/<batch_name>/<sample>/...` on BV-BRC. Single-sample runs
don't need it and keep writing to `results/<sample>/...` directly.

## 2. Useful flags

- `--cores N` -- how many samples to process in parallel (BV-BRC runs the
  actual assembly/annotation on their servers, but each running sample holds
  one local core while it polls for job completion).
- `--keep-going` -- if one sample's BV-BRC job genuinely fails, keep
  processing the rest instead of aborting the whole run.
- `-n` / `--dry-run` -- preview what would run without actually submitting
  anything to BV-BRC. Good to run first, especially after changing samples.
- `--printshellcmds` -- add to a dry run to see the exact shell commands that
  would execute.
- `--until <rule>` -- stop after a specific rule, e.g.
  `--until bvbrc_submit_assembly` to only submit assembly jobs and check them
  manually.

## 3. Examples end to end

Dry run with a single id:

```
snakemake -n --cores 4 --config srr=SRR28752452
```

Real run with a list, keeping going on per-sample failures:

```
snakemake --cores 4 --keep-going --config srr=SRR28752452,SRR11111111 batch_name=my_batch
```

Real run from your TSV:

```
snakemake --cores 4 --keep-going --config batch_name=my_batch
```

## 4. Where results land

Single-sample run (no `batch_name`):

```
results/<sample>/
├── assembly/{job_id.txt, contigs.fasta, bvbrc_output/}
├── annotation/{job_id.txt, bvbrc_output/}
└── summary_report.md
```

Multi-sample run (with `batch_name`):

```
results/<batch_name>/<sample>/
├── assembly/{job_id.txt, contigs.fasta, bvbrc_output/}
├── annotation/{job_id.txt, bvbrc_output/}
└── summary_report.md
```

Open `summary_report.md` first for any sample -- it links every other output
file for that sample.
