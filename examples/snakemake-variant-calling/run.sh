#!/usr/bin/env bash
# Reproduce this example end to end: fetch the reads, run the workflow, and
# let the FAIRSCAPE reporter turn the finished DAG into an RO-Crate.
#
#   ./run.sh
#
# Needs snakemake (>=9) and snakemake-report-plugin-fairscape; the workflow's
# own tools (bwa, samtools, bcftools, pysam) come from the per-rule conda
# environments in envs/, created by --use-conda on the first run.
set -euo pipefail
cd "$(dirname "$0")"

DATA_TAG=v5.24.1
DATA_URL="https://codeload.github.com/snakemake/snakemake-tutorial-data/tar.gz/refs/tags/${DATA_TAG}"

if [ ! -d data ]; then
    echo "fetching the reference and reads (~18 MB) from snakemake-tutorial-data ${DATA_TAG} ..."
    curl -sSL "$DATA_URL" \
        | tar -xz --strip-components=1 "snakemake-tutorial-data-${DATA_TAG#v}/data"
fi

mkdir -p run

# 1. run the workflow. --use-conda builds the per-rule environments in envs/
#    the first time (a few minutes); afterwards they are reused.
snakemake --cores 4 --use-conda "$@"

# 2. report on the finished run. A Snakemake report plugin is a second,
#    read-only pass over the DAG and the .snakemake persistence metadata, so
#    the crate describes what actually ran — including the jobs that were
#    already up to date.
#
#    SNAKEMAKE_FAIRSCAPE_DUMP_RECORDS makes the reporter also write the plain
#    records document it hands to fairscape_conversion. That file is this
#    example's input, so the conversion can be re-run without re-running bwa.
SNAKEMAKE_FAIRSCAPE_DUMP_RECORDS=run/records.json \
snakemake \
    --cores 4 \
    --use-conda \
    --reporter fairscape \
    --report-fairscape-path ro-crate-metadata.json \
    --report-fairscape-name "Variant calling on three sequenced samples" \
    --report-fairscape-description "Reads from three samples aligned to the reference with bwa-mem, sorted and indexed with samtools, and jointly called with bcftools; a Snakemake run captured as an EVI RO-Crate." \
    --report-fairscape-author "Example Researcher" \
    --report-fairscape-keywords "snakemake, variant calling, bwa, bcftools, genomics" \
    --report-fairscape-version "1.0" \
    --report-fairscape-schemas \
    --report-fairscape-preview

echo
echo "crate:   $(pwd)/ro-crate-metadata.json"
echo "records: $(pwd)/run/records.json"
