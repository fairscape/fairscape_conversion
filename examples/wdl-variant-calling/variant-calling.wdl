version 1.0

## Read alignment and joint variant calling, scattered over samples.
##
## The same analysis as ../snakemake-variant-calling, written the way WDL
## pipelines are: one task per tool, a scatter over the samples, and a gather
## that calls variants across all of them at once. Run it with
##
##     java -jar cromwell.jar run variant-calling.wdl -i inputs.json -m metadata.json
##
## and the metadata.json Cromwell writes is what fairscape_conversion's
## cromwell plugin converts into an RO-Crate. See run.sh.

workflow VariantCalling {
    input {
        File reference
        File reference_amb
        File reference_ann
        File reference_bwt
        File reference_pac
        File reference_sa
        Array[String] sample_names
        Array[File] sample_reads
        String mpileup_options = "-d 250 -a AD,DP"
        String call_options = "-mv -Ov"
    }

    scatter (sample in zip(sample_names, sample_reads)) {
        call BwaMem {
            input:
                sample = sample.left,
                reads = sample.right,
                reference = reference,
                reference_amb = reference_amb,
                reference_ann = reference_ann,
                reference_bwt = reference_bwt,
                reference_pac = reference_pac,
                reference_sa = reference_sa
        }

        call SamtoolsSort {
            input:
                sample = sample.left,
                bam = BwaMem.bam
        }

        call SamtoolsIndex {
            input:
                sample = sample.left,
                bam = SamtoolsSort.sorted_bam
        }
    }

    call BcftoolsCall {
        input:
            reference = reference,
            bams = SamtoolsSort.sorted_bam,
            bais = SamtoolsIndex.index,
            mpileup_options = mpileup_options,
            call_options = call_options
    }

    call VariantSummary {
        input:
            vcf = BcftoolsCall.vcf
    }

    call PlotQuals {
        input:
            vcf = BcftoolsCall.vcf
    }

    output {
        File variants = BcftoolsCall.vcf
        File variant_summary = VariantSummary.summary
        File quality_plot = PlotQuals.plot
        Array[File] alignments = SamtoolsSort.sorted_bam
    }

    meta {
        description: "Align reads from several samples with bwa-mem and call variants jointly with bcftools."
    }
}


task BwaMem {
    input {
        String sample
        File reads
        File reference
        File reference_amb
        File reference_ann
        File reference_bwt
        File reference_pac
        File reference_sa
        Int threads = 2
    }

    command <<<
        set -euo pipefail
        # bwa wants the index files beside the fasta under their original
        # names; Cromwell localizes each input into its own directory, so
        # rebuild that layout with symlinks.
        mkdir -p reference
        ln -s ~{reference}     reference/genome.fa
        ln -s ~{reference_amb} reference/genome.fa.amb
        ln -s ~{reference_ann} reference/genome.fa.ann
        ln -s ~{reference_bwt} reference/genome.fa.bwt
        ln -s ~{reference_pac} reference/genome.fa.pac
        ln -s ~{reference_sa}  reference/genome.fa.sa

        bwa mem -t ~{threads} \
            -R "@RG\tID:~{sample}\tSM:~{sample}\tPL:ILLUMINA" \
            reference/genome.fa ~{reads} \
            | samtools view -Sb - > ~{sample}.bam
    >>>

    output {
        File bam = "~{sample}.bam"
    }

    runtime {
        cpu: threads
    }
}


task SamtoolsSort {
    input {
        String sample
        File bam
    }

    command <<<
        set -euo pipefail
        samtools sort -T ~{sample} -O bam ~{bam} > ~{sample}.sorted.bam
    >>>

    output {
        File sorted_bam = "~{sample}.sorted.bam"
    }
}


task SamtoolsIndex {
    input {
        String sample
        File bam
    }

    command <<<
        set -euo pipefail
        # the index has to sit beside the bam it indexes
        ln -s ~{bam} ~{sample}.sorted.bam
        samtools index ~{sample}.sorted.bam
    >>>

    output {
        File index = "~{sample}.sorted.bam.bai"
    }
}


task BcftoolsCall {
    input {
        File reference
        Array[File] bams
        Array[File] bais
        String mpileup_options
        String call_options
    }

    command <<<
        set -euo pipefail
        # pile the alignments and their indexes back into one directory
        mkdir -p alignments
        for bam in ~{sep=' ' bams}; do ln -s "$bam" alignments/; done
        for bai in ~{sep=' ' bais}; do ln -s "$bai" alignments/; done

        bcftools mpileup ~{mpileup_options} -f ~{reference} alignments/*.bam \
            | bcftools call ~{call_options} -o all.vcf
    >>>

    output {
        File vcf = "all.vcf"
    }
}


task VariantSummary {
    input {
        File vcf
    }

    command <<<
        set -euo pipefail
        printf 'chrom\tpos\tref\talt\tquality\tdepth\n' > variant_summary.tsv
        bcftools query -f '%CHROM\t%POS\t%REF\t%ALT\t%QUAL\t%INFO/DP\n' ~{vcf} \
            >> variant_summary.tsv
    >>>

    output {
        File summary = "variant_summary.tsv"
    }
}


task PlotQuals {
    input {
        File vcf
    }

    command <<<
        set -euo pipefail
        python3 <<'PYTHON'
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from pysam import VariantFile

        quals = [record.qual for record in VariantFile("~{vcf}")]

        figure, axes = plt.subplots(figsize=(6, 4))
        axes.hist(quals, bins=30, color="#3b6ea5", edgecolor="white")
        axes.set_xlabel("variant quality (Phred)")
        axes.set_ylabel("variants")
        axes.set_title(f"{len(quals)} variants called across all samples")
        figure.tight_layout()
        figure.savefig("quals.svg")
        PYTHON
    >>>

    output {
        File plot = "quals.svg"
    }
}
