"""Plot the quality-score distribution of the called variants.

Snakemake runs this with a ``snakemake`` object in scope carrying the rule's
input and output paths — which is also why the crate records this file as the
rule's Software rather than a shell command.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from pysam import VariantFile

quals = [record.qual for record in VariantFile(snakemake.input[0])]

figure, axes = plt.subplots(figsize=(6, 4))
axes.hist(quals, bins=30, color="#3b6ea5", edgecolor="white")
axes.set_xlabel("variant quality (Phred)")
axes.set_ylabel("variants")
axes.set_title(f"{len(quals)} variants called across all samples")
figure.tight_layout()
figure.savefig(snakemake.output[0])
