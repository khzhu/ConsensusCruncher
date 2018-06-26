from Bio import SeqIO
import itertools

#Setup variables (could parse command line args instead)
reads_f = "read_1.fastq"
reads_r = "read_2.fastq"
file_out = "read_12.fastq"
format = "fastq" #or "fastq-illumina", or "fasta", or ...

def interleave(iter1, iter2) :
    for (forward, reverse) in itertools.izip(iter1,iter2):
        assert forward.id == reverse.id
        forward.id += "/1"
        reverse.id += "/2"
        yield forward
        yield reverse

records_f = SeqIO.parse(open(reads_f,"rU"), format)
records_r = SeqIO.parse(open(reads_r,"rU"), format)

handle = open(file_out, "w")
count = SeqIO.write(interleave(records_f, records_r), handle, format)
handle.close()
print "%i records written to %s" % (count, file_out)