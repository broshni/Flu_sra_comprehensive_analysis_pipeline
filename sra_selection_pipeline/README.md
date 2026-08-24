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
- **Python 3.8+** with **Snakemake** (`pip install snakemake`) and
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
   filtered by publication date range) -- `scripts/fetch_sra_runs_by_bioproject.py`.
2. **Look up linked GenBank records** for each run's BioSample --
   `scripts/biosample_to_genbank.py`.
3. **Join the two tables** on BioSample -- `scripts/join_tables_by_biosample.py`.
4. **Split into runs with vs. without a linked GenBank accession** --
   `scripts/select_no_genbank.py` (new -- automates the step you were doing
   by hand).

If zero SRA runs are found for any of the given BioProjects, the pipeline
stops here with a clear error.

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
- `mindate` / `maxdate`: optional SRA publication date filters (`YYYY-MM-DD`).
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
`timeout_sec`.

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

- If a BioProject returns zero SRA runs, `fetch_sra_runs_by_bioproject.py`
  writes a genuinely empty output file, which the pipeline detects and stops
  on with a clear error (rather than letting the next step fail with a
  confusing pandas error). Double check the BioProject accession before
  rerunning.
- `biosample_to_genbank.py` makes one NCBI round trip per unique BioSample,
  so a BioProject with hundreds of samples will take a while and is worth an
  `--api-key` (NCBI's rate limit is much lower without one).
- `select_no_genbank.py` treats a run as "no GenBank accession" if the
  joined table's `genbank_accessions` field is empty or missing --
  double-check `03_joined.tsv` by eye the first time you run a new
  BioProject, to confirm the join actually matched BioSamples as expected.
- Tested end-to-end (with BV-BRC and NCBI calls mocked out) for three cases:
  a normal run with a mix of runs with/without GenBank accessions, a run
  where every SRA run already has one (step 2 correctly does nothing), and a
  run where the BioProjects return zero SRA runs at all (hard stop with a
  clear error).

## Adding more modules

This folder can hold more than one module. Follow the same pattern: new
scripts under `scripts/`, new rules in `Snakefile`, and document how each
module's output connects to the rest here.
