# SRA Selection -> BV-BRC Assembly -> Annotation Pipeline

A self-contained Snakemake pipeline that starts from a list of NCBI
BioProject accessions, works out which SRA runs don't have a GenBank
accession yet, and takes those all the way through viral genome assembly
and annotation on [BV-BRC](https://www.bv-brc.org/) -- in one command.

Everything it needs lives in this repo: the `Snakefile`, `config.yaml.example`,
and every script it calls, including the BV-BRC submission helpers. Nothing
here depends on any other pipeline or repo.

## Prerequisites

Before cloning, you'll need:

- **A [BV-BRC](https://www.bv-brc.org/) account.** BV-BRC is free to sign up
  for. The pipeline submits assembly/annotation jobs to BV-BRC's servers
  under your account.
- **The BV-BRC command line interface (`p3-tools`)**, installed separately --
  it's not a Python/conda package. Get an installer for your OS from
  [BV-BRC-CLI releases](https://github.com/BV-BRC/BV-BRC-CLI/releases) and
  follow BV-BRC's [install docs](https://www.bv-brc.org/docs/cli_tutorial/cli_installation.html).
  Specifically, `p3-submit-viral-assembly` isn't documented on BV-BRC's
  public docs site as of writing -- run `p3-submit-viral-assembly --help`
  after installing to sanity-check its flags against what this pipeline
  passes it.
- Log in once per machine: `p3-login <your-username>` (the pipeline checks
  this and fails fast with a clear message if you're not logged in).
- **Python 3.8+** with **Snakemake 8 or newer** (`pip install snakemake`) and
  **biopython** + **pandas** (see Requirements below).
- **An NCBI Entrez contact email.** NCBI requires this for any automated
  querying (this is what SRA/GenBank lookups use); it doesn't need to be
  registered anywhere in advance, just a real address they can reach you at
  if your usage causes problems.

## Setup

```
git clone <this-repo-url>
cd <repo-folder>
cp config.yaml.example config.yaml
```

Then edit `config.yaml` and fill in: your NCBI Entrez contact email, the
BioProject accession(s) you want to pull, and your BV-BRC workspace path
(`bvbrc.workspace_base`, e.g. `/yourusername@bvbrc/home/some_folder_name`
-- it gets created automatically if it doesn't exist). `config.yaml` is
gitignored, so your real values never get committed if you push changes
back to a fork.

## What it does

**Step 1 -- SRA selection:**

1. **Fetch SRA RunInfo** for a list of BioProject accessions (optionally
   limited to a date window, see `mindate` / `maxdate` below) --
   `scripts/fetch_sra_runs_by_bioproject.py`.
2. **Look up linked GenBank records** for each run's BioSample --
   `scripts/biosample_to_genbank.py`.
3. **Join the two tables** on BioSample -- `scripts/join_tables_by_biosample.py`.
4. **Split into runs with vs. without a linked GenBank accession** --
   `scripts/select_no_genbank.py`.

If none of the given BioProjects return any SRA runs at all, the pipeline
stops here with a clear error. (A BioProject that returns nothing is skipped
as long as at least one other one returns runs.) If runs are found but none
fall inside the date window, that is not an error: step 1 writes header-only
tables and step 2 has nothing to do.

**Step 2 -- assembly + annotation**, for every run with no GenBank
accession: submit to BV-BRC's IRMA-based Viral Assembly service, pick the
assembled contigs, submit those to BV-BRC's Genome Annotation service
(VIGOR4), fetch both, and write a per-sample summary report. If assembly
produces no usable contigs for a sample, annotation is skipped for that
sample only (with a clear note), instead of failing the whole run.

If step 1 finds SRA runs but every one of them already has a GenBank
accession, step 2 has nothing to do and the pipeline stops there too --
without ever calling BV-BRC's assembly/annotation services.

## Requirements

```
pip install snakemake biopython pandas
```

(If you're running inside BV-BRC's own CLI environment and hit a
"externally-managed-environment" pip error, add `--break-system-packages`
to the command above.)

## Quickstart

Putting it all together, end to end:

```
git clone <this-repo-url>
cd <repo-folder>
pip install snakemake biopython pandas
cp config.yaml.example config.yaml
# edit config.yaml: set sra_selection.email and bvbrc.workspace_base at minimum
p3-login <your-bvbrc-username>
snakemake -n --cores 4 --config sra_bioprojects=PRJNA1122849 sra_run_name=my_first_run   # dry run
snakemake --cores 4 --keep-going --config sra_bioprojects=PRJNA1122849 sra_run_name=my_first_run
```

## Running -- one command

Once configured, every subsequent run is just:

```
snakemake --cores 4 --keep-going --config sra_run_name=flu_2026_08
```

Under the hood, `select_no_genbank` is a Snakemake *checkpoint* rather than
a plain rule: step 2's sample list isn't known until step 1 has actually
produced `no_genbank_samples.tsv`, so Snakemake runs step 1, re-evaluates
the job graph to see how many samples step 2 needs, then runs step 2 -- all
within this one invocation. You don't need to know anything about
checkpoints to use this; the one thing worth knowing is that a dry run (`-n`)
before the checkpoint has ever run for this `run_name` won't show you step
2's job count -- it'll say `<TBD>` and note "DAG of jobs will be updated
after completion." Run it again after step 1 has completed once (or just
run for real) to see step 2's jobs listed.

```
snakemake -n --cores 4 --config sra_run_name=flu_2026_08
```

## Configuration

Edit `config.yaml`'s `sra_selection:` block:

- `run_name`: names the output subfolder (`results/<run_name>/`) -- use a
  different name per BioProject pull to keep them from overwriting each
  other.
- `bioprojects`: list of BioProject accessions, e.g. `["PRJNA1122849"]`.
- `bioproject_file`: optional, a file with one BioProject per line, used in
  addition to (or instead of) `bioprojects`.
- `mindate` / `maxdate`: optional date window (`YYYY-MM-DD`, inclusive). It
  is sent to NCBI as a `[PDAT]` range, but NCBI's range alone did not
  reliably narrow results, so every returned run is also checked against its
  RunInfo `ReleaseDate`; runs outside the window, or with no `ReleaseDate`,
  are dropped. `logs/<run_name>/fetch_sra_runinfo.log` shows NCBI's reading
  of the query and how many runs the date filter kept.
- `email`: required by NCBI Entrez -- set this to your own address.
- `api_key`: optional NCBI API key.

Every one of these can also be overridden per-run on the command line
without editing `config.yaml`, using `sra_` + the field name:

```
snakemake --cores 4 --keep-going --config sra_bioprojects=PRJNA1122849 sra_run_name=flu_2026_08 sra_mindate=2026-01-01 sra_maxdate=2026-01-07
```

And `config.yaml`'s `bvbrc:` block controls step 2 -- `workspace_base`
(where BV-BRC job output goes), `viral_assembly_strategy`,
`annotation_recipe`, `genetic_code`, `domain`, `public`, `poll_interval_sec`,
`timeout_sec`. `public` is `false` by default, so annotated
genomes stay private; set it to `true` to submit them with `--public`.

Note: batches that already finished were annotated with `--public`, and Snakemake
remembers that. Rerunning one of those batches now would resubmit its annotation
jobs as private copies; add `--rerun-triggers mtime` if you rerun an old batch.

**Local disk cleanup for big BioProject pulls.** Pass
`--config cleanup_local=true` to delete each sample's local `bvbrc_output/`
dirs, `contigs.fasta`, and `job_id.txt` as soon as that sample's
`summary_report.md` is written, keeping only the summary report on disk.
Safe because everything deleted is already stored in your BV-BRC workspace
-- re-download anything you need later with
`p3-cp -r ws:<workspace_path> <local_dir>`. Off by default. Example:

```
snakemake --cores 4 --keep-going --config sra_run_name=flu_2026_08 cleanup_local=true
```

## Outputs

```
results/<run_name>/
├── 01_sra_runinfo.tsv               # every SRA run for the given BioProject(s)
├── 02_genbank_by_biosample.tsv      # GenBank records linked to each BioSample
├── 03_joined.tsv                    # 01 + 02 joined on BioSample
├── no_genbank_samples.tsv           # runs with NO GenBank accession -- what step 2 processes
├── with_genbank_samples.tsv         # runs excluded because one already exists
├── ncbi_cache/                      # NCBI responses; RunInfo fetches are reused on reruns
└── samples/
    └── <SRR...>/
        ├── assembly/{job_id.txt, contigs.fasta, bvbrc_output/}
        ├── annotation/{job_id.txt, bvbrc_output/}
        └── summary_report.md
```

With `cleanup_local=true`, each `samples/<SRR...>/` folder is reduced to just
`summary_report.md` (plus a `.cleaned` marker) once that sample finishes --
the report's links to `assembly/bvbrc_output/` etc. will point to files that
are no longer local, but they're still in your BV-BRC workspace.

Every run also uploads `all_sra_with_genbank_status.tsv`,
`no_genbank_samples.tsv`, and `with_genbank_samples.tsv` to
`workspace_base/<run_name>/sra_selection/` on BV-BRC (via
`rule publish_sra_lists_to_workspace`, part of the default target), so the
same batch folder that holds each sample's assembly/annotation output there
(`workspace_base/<run_name>/<SRR>/...`) also has a record of which SRA runs
went in and which were excluded, and why.

## Notes / caveats

- If none of the BioProjects return SRA runs, `fetch_sra_runs_by_bioproject.py`
  writes a genuinely empty output file, which the pipeline detects and stops
  on with a clear error (rather than letting the next step fail with a
  confusing pandas error). Double check the BioProject accessions before
  rerunning.
- `biosample_to_genbank.py` makes a few NCBI requests per unique BioSample
  (search, link, summary), so a BioProject with hundreds of samples will take
  a while and is worth an `api_key` (NCBI's rate limit is much lower without
  one).
- **Failed GenBank lookups stop the run instead of being guessed.** Each
  BioSample lookup is retried up to 4 times with backoff (rate limits,
  timeouts). If any still fails, `biosample_to_genbank` stops with a list of
  those BioSamples in `logs/<run_name>/biosample_to_genbank.log` and writes no
  table, so nothing reaches assembly on a half-finished lookup; rerun the same
  command to retry. A BioSample that NCBI says doesn't exist is a real answer
  and counts as "no GenBank record".
- **Each `run_name` is independent.** A run that still has no GenBank record
  is assembled and annotated again by every new
  `run_name` whose BioProjects/date window include it -- BV-BRC assemblies
  don't create GenBank records. Use non-overlapping date windows for
  recurring pulls.
- Re-running an existing `run_name` with the same settings does not re-query
  NCBI (step 1's outputs already exist); change the settings or use a new
  `run_name` for a fresh pull.
- `ncbi_cache/` (per `run_name`) keeps every NCBI response. The RunInfo
  fetches, keyed by the exact run ids, are reused when the same `run_name` is
  rerun; the BioProject searches are always re-run, so newly added SRA runs
  are never hidden by the cache. Safe to delete.
- After fetching the assembly, the pipeline deletes the local copies of the
  raw reads BV-BRC downloaded from SRA (`<SRR>_1.fastq`, `<SRR>_2.fastq`,
  `<SRR>/`, inside `bvbrc_output/.assembly/`); they are 100s of MB and still
  in SRA.
- `profiles/default/config.yaml` (loaded automatically by Snakemake 8+) sets
  `rerun-triggers: [mtime, params]`, so editing the `Snakefile` or scripts
  never makes Snakemake resubmit BV-BRC jobs for samples that already
  finished. Use `--forcerun <file or rule>` when you do want something redone.
- `select_no_genbank.py` treats a run as "no GenBank accession" if the
  joined table's `genbank_accessions` field is empty or missing --
  double-check `03_joined.tsv` by eye the first time you run a new
  BioProject, to confirm the join actually matched BioSamples as expected.
- Tested end-to-end (with BV-BRC and NCBI calls mocked out) for three cases:
  a normal run with a mix of runs with/without GenBank accessions, a run
  where every SRA run already has one (step 2 correctly does nothing), and a
  run where the BioProjects return zero SRA runs at all (hard stop with a
  clear error).

## Standalone helper: `scripts/sra_genbank_lookup.py`

Not part of the Snakefile (yet). A faster, more careful version of the
GenBank check for a table you already have: it reads an xlsx/csv/tsv with a
run column and a BioSample column, checks NCBI both ways (BioSample ->
nuccore and SRA run -> nuccore) in batches of 100 with retries, and marks
every row `genbank_lookup = ok` or `failed`, so failed lookups are never
mistaken for "no GenBank record".

```
python3 scripts/sra_genbank_lookup.py runs.xlsx --sheet "Raw Data" --email you@example.com [--api-key KEY] [--limit 20]
# re-check only the rows that failed last time:
python3 scripts/sra_genbank_lookup.py runs.xlsx --email you@example.com --only-failed runs_genbank.tsv
```

Writes `<input>_genbank.xlsx` and `<input>_genbank.tsv` next to the input
(or `--out <prefix>`), adding `genbank_accessions`, `genbank_titles`,
`genbank_dates`, `genbank_n_records`, `genbank_found_via` and
`genbank_lookup`. Needs biopython, pandas and openpyxl.

## Adding more modules

This folder can hold more than one module. Follow the same pattern: new
scripts under `scripts/`, new rules in `Snakefile`, and document how each
module's output connects to the rest here.
