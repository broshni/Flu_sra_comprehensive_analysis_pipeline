# Flu SRA Comprehensive Analysis Pipelines

Two independent Snakemake pipelines for taking viral SRA data through
genome assembly and annotation on [BV-BRC](https://www.bv-brc.org/). They
share no code and don't call each other -- pick whichever fits what you're
starting from.

## Which one do I want?

| | [`sra_selection_pipeline/`](sra_selection_pipeline/) | [`assembly_annotation_pipeline/`](assembly_annotation_pipeline/) |
|---|---|---|
| **Start from** | A list of NCBI BioProject accessions (optionally filtered by date) | One or more SRA run accessions you already have |
| **What it figures out for you** | Which SRA runs under those BioProjects don't have a GenBank accession yet -- i.e. which ones are actually worth assembling | Nothing -- you supply the exact samples to run |
| **What it does** | SRA selection -> assembly -> annotation, one command | Assembly -> annotation, one command |
| **Use it when** | You're doing ongoing surveillance and want "show me what's new" | You already know exactly which SRA runs you want processed |

Both submit jobs to BV-BRC's IRMA-based Viral Assembly service and Genome
Annotation service (VIGOR4) the same way, and produce the same kind of
per-sample output (assembled contigs, annotation output, a
`summary_report.md`). The difference is entirely in how the sample list
gets decided.

## Setup (either pipeline)

Both need:

- A [BV-BRC](https://www.bv-brc.org/) account (free) and the BV-BRC CLI
  (`p3-tools`) installed and logged in (`p3-login <username>`) -- see each
  pipeline's own README for install links.
- Snakemake (`pip install snakemake`).
- A `config.yaml` you create from that pipeline's `config.yaml.example`
  (each pipeline's real `config.yaml` is gitignored, so cloning this repo
  never exposes anyone's actual credentials or workspace paths).

```
git clone <this-repo-url>
cd <repo-folder>

# for BioProject-driven surveillance:
cd sra_selection_pipeline
cp config.yaml.example config.yaml
# edit config.yaml, then:
snakemake --cores 4 --keep-going --config sra_run_name=my_first_run

# for a known list of SRA accessions:
cd ../assembly_annotation_pipeline
cp config.yaml.example config.yaml
cp samples.tsv.example samples.tsv
# edit config.yaml and samples.tsv, then:
snakemake --cores 4 --keep-going
```

Full instructions, all configuration options, and troubleshooting notes are
in each pipeline's own `README.md` (and `RUNNING.md` for the assembly +
annotation pipeline's full command reference).
