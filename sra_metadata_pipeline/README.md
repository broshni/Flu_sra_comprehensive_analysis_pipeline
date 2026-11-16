# SRA → Metadata → BV-BRC Assembly → Annotation Pipeline

Give it one or more SRA run accessions. For each one it:

1. **Pulls metadata from NCBI.** It fetches the SRA runinfo and BioSample
   attributes with edirect and builds the BV-BRC metadata table
   (`scripts/extract_sra_metadata.py`).
2. **Assembles.** The SRA accession is submitted to BV-BRC's IRMA viral
   assembly service. The pipeline waits, fetches the result and picks the
   combined contigs.
3. **Reads the subtype from the assembly.** The HA/NA subtype comes from IRMA's
   segment FASTA names (`A_HA_H5.fasta`, `A_NA_N1.fasta`) or, failing that,
   from the contig headers (`scripts/assembly_subtype.py`).
4. **Updates the metadata table.** `h_type`, `n_type`, `subtype` and
   `genome_name` are filled in from the assembly (`scripts/finalize_metadata.py`).
5. **Annotates.** The contigs are submitted to BV-BRC genome annotation
   (VIGOR4). The pipeline waits, fetches the result and writes a
   `summary_report.md` for each sample.

The NCBI metadata step runs in parallel with the assemblies, because it only
needs the accessions. Each sample's annotation is submitted as soon as that
sample's assembly and subtype are done; it does not wait for the other samples.

## Requirements

- Snakemake 8 or newer (so `profiles/default` is picked up automatically, see
  Notes), pandas and openpyxl: `pip install snakemake pandas openpyxl`
- NCBI E-utilities (`esearch`/`efetch`). Set its folder in `config.yaml` →
  `metadata.edirect_path`. If that is blank, the script uses `$EDIRECT_PATH`,
  then `~/edirect` if it exists, then whatever is on PATH. Setting
  `NCBI_API_KEY` in your shell speeds up the lookups.
- The BV-BRC CLI (`p3-tools`), logged in with `p3-login <username>`.

## Setup

```
cp config.yaml.example config.yaml     # set username, workspace_base, edirect_path
cp samples.tsv.example samples.tsv     # optional: list of SRA accessions
```

## Running

```
# one accession (outputs go to results/<SRR>/)
snakemake --cores 4 --keep-going --config srr=SRR28752452

# several accessions -- batch_name is required
snakemake --cores 8 --keep-going --config srr=SRR1,SRR2,SRR3 batch_name=flu_2026_10
snakemake --cores 8 --keep-going --config samples_tsv=samples.tsv batch_name=flu_2026_10

# dry run first
snakemake -n --cores 4 --config samples_tsv=samples.tsv batch_name=flu_2026_10
```

Each BV-BRC wait holds one core for the length of the remote job, so set
`--cores` to at least the number of samples you want running at once.

`samples.tsv` needs a column named `srr`, `Run` or `sra_accession`. Optional
columns are `scientific_name`, `reference_virus` and `taxonomy_id`; any other
columns are ignored.

## Outputs

```
results/<batch_name>/
├── metadata/
│   ├── <batch_name>_metadata.xlsx   # FINAL metadata (see below)
│   ├── <batch_name>_metadata.tsv    # BVBRC sheet as TSV
│   ├── ncbi_metadata.xlsx           # NCBI-only metadata, before assembly subtypes
│   └── sra_ids.txt
└── samples/<SRR>/
    ├── assembly/   job_id.txt, assembly_subtype.tsv  (+ contigs.fasta, bvbrc_output/ with keep_local=true)
    ├── annotation/ job_id.txt                        (+ bvbrc_output/ with keep_local=true)
    └── summary_report.md
```

**Local disk use.** By default nothing large is kept on your machine. The
downloaded assembly and annotation folders and `contigs.fasta` are temporary:
Snakemake deletes each sample's copies as soon as its summary report is written.
Each sample's `summary_report.md` is uploaded to its workspace folder, with links
pointing to workspace paths. What stays local is a few KB per sample (job ids,
`assembly_subtype.tsv`, the summary report, the metadata table), which Snakemake
needs so a re-run doesn't resubmit finished jobs. Use `--config keep_local=true`
to keep full local copies.

On BV-BRC, the jobs go to `{workspace_base}/{batch_name}/{SRR}/`, and the final metadata
table (`.tsv`, plus the `.xlsx` if BV-BRC accepts it) is uploaded to
`{workspace_base}/{batch_name}/metadata/`.

`<batch_name>_metadata.xlsx` has these sheets:

- **Raw Data**: SRA runinfo merged with the BioSample attributes.
- **BVBRC**: the BV-BRC metadata columns. `genome_name` looks like
  `Influenza A virus A/<host>/<country>/<isolate>/<year>(H5N1)` and `strain`
  like `A/<host>/<country>/<isolate>/<year>`. The host is written exactly as
  the BioSample gives it (e.g. `CATTLE`, `Bos taurus`) and left out for human
  samples; missing parts are skipped rather than left as `//`. If the
  BioSample's `isolate` -- or failing that its `strain` attribute -- is
  already a full name starting with `A/`, that name is used as the strain
  instead (minus any trailing `(HxNy)`). `geographic_group` comes from the
  country via a built-in table. The last four columns are QC columns: `assembly_status`,
  `assembled_segments`, `subtype_source` and `subtype_note`.
- **Assembly**: each sample's assembled segments and its HA/NA subtypes.
- **Failed**: only present when an NCBI lookup failed.

### How h_type / n_type are chosen

The assembly takes priority. H and N are resolved separately:

| Assembly has…            | Result                                              | `subtype_note`                          |
|--------------------------|-----------------------------------------------------|-----------------------------------------|
| exactly one HA (NA) type | used                                                | –                                       |
| none                     | BioSample value, if any                             | `no NA segment assembled; N type from BioSample` |
| more than one            | left blank                                          | `multiple HA subtypes in assembly (H5/H7)` |
| differs from BioSample   | assembly value used                                 | `assembly H5N5 differs from BioSample H5N1` |
| nothing assembled        | blank, and annotation is skipped                    | `assembly produced no segments`         |
| BV-BRC job failed / timed out | BioSample value, if any; annotation is skipped | `assembly job failed`              |

`subtype` (and the `(HxNy)` suffix on `genome_name`) is only filled when both H and
N are known. Filter on `subtype_note` to find the records that need a look.

## Notes

- `profiles/default/config.yaml` (loaded automatically by Snakemake 8+) sets
  `rerun-triggers: [mtime, params]`, so editing the Snakefile or scripts never
  makes Snakemake resubmit BV-BRC jobs for a batch that already finished. Use
  `--forcerun <file or rule>` when you do want something redone.
- A BV-BRC assembly job that fails or times out does not stop the batch: the
  sample's `assembly/job_id.txt` is set to `FAILED <job id>`, annotation is
  skipped, and it still gets a row in the metadata table (`assembly job failed`)
  and a summary report. The end of the run lists any such samples. To retry
  them, rerun the same command with `--forcerun` and their job_id.txt paths
  (the end-of-run report prints the exact flag), e.g.
  `snakemake --cores 8 --keep-going --config ... --forcerun results/<batch>/samples/<SRR>/assembly/job_id.txt`.
  Only those samples are resubmitted, and the batch metadata table is rebuilt.
  (Just deleting job_id.txt does not work: Snakemake won't rebuild it while the
  sample's later outputs exist.)
- Annotated genomes are private by default (`bvbrc.public: false`); set it to
  `true` to submit them with `--public` (visible to all BV-BRC users).
- The annotation job is labelled with `scientific_name` from `samples.tsv`,
  falling back to `default_scientific_name` ("Influenza A virus"). It is not
  labelled with the metadata `genome_name`.
- The raw SRA reads BV-BRC downloads into the assembly folder are deleted
  locally after fetching; they are still available in SRA.
- `scripts/extract_sra_metadata.py` also works on its own, without
  Snakemake: `python3 scripts/extract_sra_metadata.py ids.txt out.xlsx
  [--subtype H5N1] [--location country] [--subtype-suffix]` (one SRA id per
  line; SRX/SRS/SRP ids are expanded to their runs, and a run reached through
  two ids is only listed once). The subtype is read from the BioSample
  `serotype`/`subtype`/`strain`/`isolate` fields; forms like `H1N1pdm09` and
  `H3N2v` count as H1N1 and H3N2.
- The country -> BV-BRC geographic group table is built into
  `scripts/extract_sra_metadata.py` (`GEOGRAPHIC_GROUPS`); edit it there to add
  countries. Countries missing from it are listed as a warning in
  `logs/<batch>/fetch_metadata.log` and `finalize_metadata.log`.
