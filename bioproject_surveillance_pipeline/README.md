# BioProject Surveillance Pipeline

BioProjects → SRA runs with no GenBank record → NCBI metadata → BV-BRC assembly →
subtype → BV-BRC metadata table → BV-BRC annotation, in one command.

Give it one or more BioProject accessions and a publication date window. It:

1. **Selects SRA runs.**
   - Fetches SRA RunInfo for the BioProjects and keeps the runs released inside
     the date window (`scripts/fetch_sra_runs_by_bioproject.py`).
   - Looks up GenBank (nuccore) records linked to each run's BioSample
     (`scripts/biosample_to_genbank.py`).
   - Joins those GenBank records back onto the SRA runs by BioSample
     (`scripts/join_tables_by_biosample.py`).
   - Keeps the runs whose BioSample has **no** GenBank record
     (`scripts/select_no_genbank.py`). Everything below runs only on these.
2. **Pulls metadata from NCBI** for the selected runs (SRA runinfo + BioSample
   attributes, via edirect) and builds the BV-BRC metadata table
   (`scripts/extract_sra_metadata.py`).
3. **Assembles** each run with BV-BRC's IRMA viral assembly service, picks the
   combined contigs, and **reads the HA/NA subtype** from the assembled segment
   names (`scripts/assembly_subtype.py`).
4. **Finalizes the metadata table**: `h_type`, `n_type`, `subtype` and
   `genome_name` from the assembly (`scripts/finalize_metadata.py`), and
   uploads it to BV-BRC.
5. **Annotates** each run's contigs with BV-BRC genome annotation (VIGOR4,
   recipe `viral-lowvan`), and writes and uploads a `summary_report.md` per run.

The sample list for steps 2–5 is only known after step 1, so
`select_no_genbank` is a Snakemake *checkpoint*: a dry run before step 1 has
run shows `<TBD>` for the later jobs. One `snakemake` command still does
everything.

## Requirements

- Python 3.8+ with Snakemake 8 or newer, biopython, pandas and openpyxl:
  `pip install snakemake biopython pandas openpyxl`
- NCBI E-utilities (`esearch`/`efetch`, a.k.a. edirect) for step 2. Set the
  folder in `config.yaml` → `metadata.edirect_path`; if blank, the script
  uses `$EDIRECT_PATH`, then `~/edirect`, then PATH.
- The BV-BRC CLI (`p3-tools`, from
  [BV-BRC-CLI releases](https://github.com/BV-BRC/BV-BRC-CLI/releases)),
  logged in once per machine with `p3-login <username>`.
- An email address for NCBI (required), and ideally an NCBI API key.

## Setup

```
cp config.yaml.example config.yaml
```

Fill in at least `sra_selection.run_name`, `bioprojects`, `email` and
`bvbrc.workspace_base`. `config.yaml` is gitignored.

## Running

```
# dry run
snakemake -n --cores 4

# real run, using config.yaml
snakemake --cores 8 --keep-going

# a weekly pull: override the run name and date window on the command line
snakemake --cores 8 --keep-going --config sra_run_name=flu_2026_11_w2 \
    sra_mindate=2026-11-08 sra_maxdate=2026-11-14
```

Every `sra_selection` setting can be overridden with `--config sra_<name>=...`:
`sra_run_name`, `sra_bioprojects` (comma-separated), `sra_bioproject_file`,
`sra_mindate`, `sra_maxdate`, `sra_email`, `sra_api_key`.

Each BV-BRC wait holds one local core for the length of the remote job, so set
`--cores` to at least the number of runs you want assembling at once.

## Configuration

`sra_selection:`

- `run_name` (required): names this pull. Outputs go to `results/<run_name>/`
  and `{workspace_base}/<run_name>/`. Use a new name for every pull.
- `bioprojects` / `bioproject_file`: the BioProjects to search (a list, and/or
  a file with one accession per line).
- `mindate` / `maxdate`: publication date window, `YYYY-MM-DD`, inclusive.
  It is sent to NCBI as a `[PDAT]` range and also checked against each run's
  RunInfo `ReleaseDate`; runs outside it, or with no `ReleaseDate`, are dropped.
  Leave blank for no limit.
- `email` (required) and `api_key` (optional; used by every NCBI step,
  including edirect).

Other settings: `metadata.edirect_path`, `default_scientific_name` (annotation
label if a run's SRA record has none), `keep_local` (see Outputs), and the
`bvbrc:` block (`workspace_base`, `viral_assembly_strategy`,
`annotation_recipe` = `viral-lowvan`, `genetic_code`, `domain`, `public`,
`poll_interval_sec`, `timeout_sec`).

## Outputs

```
results/<run_name>/
├── selection/
│   ├── 01_sra_runinfo.tsv          # runs in the BioProjects, inside the date window
│   ├── 02_genbank_by_biosample.tsv # GenBank records linked to each BioSample
│   ├── 03_joined.tsv               # 01 + 02 joined on BioSample
│   ├── no_genbank_samples.tsv      # runs with NO GenBank record -- what steps 2-5 process
│   └── with_genbank_samples.tsv    # runs excluded because a record already exists
├── metadata/
│   ├── <run_name>_metadata.xlsx    # FINAL metadata (see below)
│   ├── <run_name>_metadata.tsv     # BVBRC sheet as TSV
│   ├── ncbi_metadata.xlsx          # NCBI-only metadata, before assembly subtypes
│   └── sra_ids.txt
├── samples/<SRR>/
│   ├── assembly/   job_id.txt, assembly_subtype.tsv  (+ contigs.fasta, bvbrc_output/ with keep_local=true)
│   ├── annotation/ job_id.txt                        (+ bvbrc_output/ with keep_local=true)
│   └── summary_report.md
└── ncbi_cache/                     # NCBI responses; RunInfo fetches are reused on reruns
```

On BV-BRC, under `{workspace_base}/<run_name>/`:

- `selection/`: `all_sra_with_genbank_status.tsv`, `no_genbank_samples.tsv`,
  `with_genbank_samples.tsv` -- a record of which runs went in and why.
- `metadata/`: the final metadata table (`.tsv`, plus `.xlsx` if BV-BRC accepts it).
- `<SRR>/`: each run's assembly and annotation jobs, and its `summary_report.md`.

**Local disk.** By default the downloaded assembly/annotation folders and
`contigs.fasta` are temporary: Snakemake deletes each run's copies once its
summary report is written, and the raw SRA reads BV-BRC downloads are deleted
right after fetching. What stays local is a few KB per run, which Snakemake
needs so a rerun doesn't resubmit finished jobs. `--config keep_local=true`
keeps full local copies.

**The metadata workbook** (`<run_name>_metadata.xlsx`) has the sheets Raw Data
(SRA runinfo + BioSample attributes), BVBRC (the BV-BRC metadata columns, plus
QC columns `assembly_status`, `assembled_segments`, `subtype_source` and
`subtype_note`), Assembly (each run's segments and HA/NA subtypes) and, if any
NCBI lookup failed in step 2, Failed. `genome_name` looks like
`Influenza A virus A/<host>/<country>/<isolate>/<year>(H5N1)`; the host is
written as the BioSample gives it and left out for human samples, and a
BioSample `isolate` or `strain` that is already a full `A/...` name is used
as-is.

### How h_type / n_type are chosen

The assembly takes priority. H and N are resolved separately:

| Assembly has…                 | Result                                         | `subtype_note`                                   |
|-------------------------------|------------------------------------------------|--------------------------------------------------|
| exactly one HA (NA) type      | used                                           | –                                                |
| none                          | BioSample value, if any                        | `no NA segment assembled; N type from BioSample` |
| more than one                 | left blank                                     | `multiple HA subtypes in assembly (H5/H7)`       |
| differs from BioSample        | assembly value used                            | `assembly H5N5 differs from BioSample H5N1`      |
| nothing assembled             | blank, and annotation is skipped               | `assembly produced no segments`                  |
| BV-BRC job failed / timed out | BioSample value, if any; annotation is skipped | `assembly job failed`                            |

`subtype` (and the `(HxNy)` suffix on `genome_name`) is only filled when both
H and N are known. Filter on `subtype_note` to find the records that need a look.

## What happens when something fails

- **A GenBank lookup keeps failing** (rate limit, timeout): each BioSample is
  retried up to 4 times; if any still fails, the run stops after step 1 with
  the list in `logs/<run_name>/biosample_to_genbank.log`, before anything is
  sent to BV-BRC. Rerun the same command to retry (the whole lookup is
  redone). A BioSample that NCBI says doesn't exist counts as "no GenBank
  record".
- **None of the BioProjects return any SRA run**: the run stops with a clear
  error. If runs are found but none fall inside the date window, or all
  already have GenBank records, that is not an error: the selection tables are
  written and uploaded, and nothing is assembled.
- **A BV-BRC assembly job fails or times out**: the run carries on. That run's
  `assembly/job_id.txt` is set to `FAILED <job id>`, annotation is skipped,
  and it still gets a metadata row (`assembly job failed`) and a summary
  report. The end of the run lists such runs and prints the flag that retries
  only them:
  ```
  snakemake --cores 8 --keep-going --forcerun results/<run_name>/samples/<SRR>/assembly/job_id.txt
  ```
  (Deleting `job_id.txt` alone does not work: Snakemake won't rebuild it while
  the run's later outputs exist.)
- **Assembly finishes with no segments**: annotation is skipped for that run
  and it is flagged in the metadata table and its summary.

## Notes

- **Use non-overlapping date windows for recurring pulls.** Each `run_name` is
  independent: a run that still has no GenBank record is assembled -- and,
  with `public: true`, published -- again by every new `run_name` whose
  window includes it, because BV-BRC assemblies don't create GenBank records.
- **Annotated genomes are public by default** (`bvbrc.public: true`). Set it
  to `false` to keep them private.
- The annotation job is labelled with the run's SRA `ScientificName` and
  `TaxID` (falling back to `default_scientific_name`), not with the metadata
  `genome_name`.
- Rerunning an existing `run_name` with the same settings does not re-query
  NCBI or resubmit anything. Changing the BioProjects or date window for an
  existing `run_name` redoes the selection, and any newly selected runs are
  assembled; runs already done are not resubmitted.
- `profiles/default/config.yaml` (loaded automatically by Snakemake 8+) sets
  `rerun-triggers: [mtime, params]`, so editing the `Snakefile` or scripts
  never makes Snakemake resubmit BV-BRC jobs for runs that already finished.
  Use `--forcerun <file or rule>` when you do want something redone.
- The country -> BV-BRC geographic group table is built into
  `scripts/extract_sra_metadata.py` (`GEOGRAPHIC_GROUPS`); countries missing
  from it are listed as a warning in `logs/<run_name>/fetch_metadata.log` and
  `finalize_metadata.log`.
- `p3-submit-viral-assembly` isn't documented on BV-BRC's public docs site;
  run `p3-submit-viral-assembly --help` after installing to check its flags
  against the `bvbrc_submit_assembly` rule.
