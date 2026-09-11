#!/usr/bin/env bash
# Reproduce this example end to end: fetch the reads, run the WDL workflow
# with Cromwell, and convert the metadata.json Cromwell writes into an
# RO-Crate.
#
#   ./run.sh
#
# Needs a JVM (Cromwell is a jar) and the workflow's tools on PATH — bwa,
# samtools, bcftools, and a python3 with pysam and matplotlib. The local
# backend runs tasks as plain shell scripts, so nothing here needs Docker;
# on a Docker-enabled backend you would add a `docker:` runtime attribute to
# each task and Cromwell would record the image digest in the metadata (and
# so would the crate).
set -euo pipefail
cd "$(dirname "$0")"

DATA_TAG=v5.24.1
DATA_URL="https://codeload.github.com/snakemake/snakemake-tutorial-data/tar.gz/refs/tags/${DATA_TAG}"
CROMWELL_VERSION=${CROMWELL_VERSION:-92}
CROMWELL_JAR=${CROMWELL_JAR:-cromwell-${CROMWELL_VERSION}.jar}

if [ ! -d data ]; then
    echo "fetching the reference and reads (~18 MB) from snakemake-tutorial-data ${DATA_TAG} ..."
    curl -sSL "$DATA_URL" \
        | tar -xz --strip-components=1 "snakemake-tutorial-data-${DATA_TAG#v}/data"
fi

if [ ! -f "$CROMWELL_JAR" ]; then
    echo "fetching Cromwell ${CROMWELL_VERSION} (~210 MB) ..."
    curl -sSL -o "$CROMWELL_JAR" \
        "https://github.com/broadinstitute/cromwell/releases/download/${CROMWELL_VERSION}/cromwell-${CROMWELL_VERSION}.jar"
fi

mkdir -p run

# 1. run the workflow. -m is the whole point for provenance: it asks Cromwell
#    to write the run's metadata — every call's command, inputs, outputs,
#    timings and status — to a file when the run finishes.
java -Dconfig.file=cromwell.conf -jar "$CROMWELL_JAR" run variant-calling.wdl \
    --inputs inputs.json \
    --options options.json \
    --metadata-output run/metadata.json

# 2. convert. The cromwell plugin reads that metadata file itself: extract.py
#    resolves the call graph and writes the submitted WDL into the crate, then
#    the mapping turns each call into an EVI Computation.
python convert.py

echo
echo "crate:    $(pwd)/ro-crate-metadata.json"
echo "metadata: $(pwd)/run/metadata.json"
