# Flu SRA Comprehensive Analysis Pipelines

Four independent Snakemake pipelines for taking viral (influenza) SRA data
through genome assembly and annotation on [BV-BRC](https://www.bv-brc.org/).
They share no code at runtime and don't call each other -- each folder has
its own `Snakefile`, `config.yaml.example` and copies of every script it
needs. Pick whichever fits what you're starting from.

## Which one do I want?

| | [`bioproject_surveillance_pipeline/`](bioproject_surveillance_pipeline/) | [`sra_selection_pipeline/`](sra_selection_pipeline/) | [`assembly_annotation_pipeline/`](assembly_annotation_pipeline/) | [`sra_metadata_pipeline/`](sra_metadata_pipeline/) |
|---|---|---|---|---|
| **Start from** | BioProject accessions + a publication date window | BioProject accessions (optionally a date window) | One or more SRA run accessions | One or more SRA run accessions |
| **What it works out for you** | Which runs have no GenBank record yet, **and** the BV-BRC metadata for them | Which runs have no GenBank record yet | Nothing -- you supply the exact samples | The BV-BRC metadata for each run, with H/N subtype from the assembly |
| **What it does** | SRA selection -> NCBI metadata -> assembly -> subtype -> annotation, plus the final metadata table | SRA selection -> assembly -> annotation | Assembly -> annotation | NCBI metadata -> assembly -> subtype -> annotation, plus the final metadata table |
| **Use it when** | Ongoing surveillance where you also need the BV-BRC metadata table -- the all-in-one option | Ongoing surveillance, assemblies/annotations only | You know exactly which runs you want, assemblies/annotations only | You know which runs you want and also need the metadata table |

All four submit to BV-BRC's IRMA-based Viral Assembly service and its
Genome Annotation service (VIGOR4, recipe `viral-lowvan`) the same way, and
write a `summary_report.md` per sample. Annotated genomes are private by default;
set `bvbrc.public: true` in a pipeline's `config.yaml` to submit them with
`--public` (visible to all BV-BRC users).

## Setup

All four need:

- A [BV-BRC](https://www.bv-brc.org/) account (free) and the BV-BRC CLI
  (`p3-tools`) installed and logged in (`p3-login <username>`) -- see each
  pipeline's own README for install links.
- Snakemake 8 or newer (`pip install snakemake`). Each pipeline has a
  `profiles/default/config.yaml` that Snakemake picks up automatically, so
  editing a `Snakefile` never resubmits BV-BRC jobs for finished samples.
- A `config.yaml` you create from that pipeline's `config.yaml.example`.
  Each pipeline's real `config.yaml` (and `samples.tsv`) is gitignored, as are
  `results/`, `logs/` and `.snakemake/`, so cloning or pushing this repo never
  exposes anyone's credentials, workspace paths or outputs.

Plus, per pipeline:

- `bioproject_surveillance_pipeline`: `pip install biopython pandas openpyxl`, edirect, and an NCBI contact email in `config.yaml`.
- `sra_selection_pipeline`: `pip install biopython pandas`, and an NCBI contact email in `config.yaml`.
- `sra_metadata_pipeline`: `pip install pandas openpyxl`, and NCBI E-utilities (`esearch`/`efetch`, a.k.a. edirect).

```
git clone <this-repo-url>
cd <repo-folder>

# BioProject-driven surveillance, all-in-one (selection + metadata + assembly + annotation):
cd bioproject_surveillance_pipeline
cp config.yaml.example config.yaml          # edit: run_name, bioprojects, dates, email, workspace_base
snakemake --cores 8 --keep-going

# BioProject-driven surveillance, assemblies/annotations only:
cd ../sra_selection_pipeline
cp config.yaml.example config.yaml          # edit: email, bioprojects, workspace_base
snakemake --cores 4 --keep-going --config sra_run_name=my_first_run

# a known list of SRA accessions, assembly + annotation only:
cd ../assembly_annotation_pipeline
cp config.yaml.example config.yaml          # edit: username, workspace_base
cp samples.tsv.example samples.tsv          # list your accessions
snakemake --cores 4 --keep-going --config batch_name=my_batch

# a known list of SRA accessions, with the BV-BRC metadata table:
cd ../sra_metadata_pipeline
cp config.yaml.example config.yaml          # edit: username, workspace_base, edirect_path
snakemake --cores 4 --keep-going --config srr=SRR1,SRR2 batch_name=my_batch
```

`batch_name` is required whenever a run has more than one sample (in the
two accession-driven pipelines; the two BioProject-driven ones name each pull
with `sra_run_name` instead).

Full instructions, all configuration options and caveats are in each
pipeline's own `README.md` (and `RUNNING.md` for the assembly + annotation
pipeline's full command reference).
