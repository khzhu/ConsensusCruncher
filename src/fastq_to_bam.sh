#!/usr/bin/env bash
#$ -S /bin/bash
#$ -cwd

##====================================================================================
##
##  FILE:         fastq_to_bam.sh
##
##  USAGE:        fastq_to_bam.sh --input INPUTDIR --output OUTPUTDIR --project PROJECT
#                                 --barcode 2 --spacer 1 --filter T --ref REF
##
##  OPTIONS:
##
##    -i, --input    Input directory [MANDATORY]
##    -o, --output   Output project directory [MANDATORY]
##    -p, --project  Project name [MANDATORY]
##    -r, --ref      Reference (BWA index) [MANDATORY]
##    -b, --barcode  Barcode length [MANDATORY]
##    -s, --spacer   Spacer length [MANDATORY]
##    -f, --filter   Spacer Filter (e.g. "T" will filter out spacers that are non-T)
##    -q, --qsub     qusb directory, default: output/qsub
##    -h, --help     Show this message
##
##  DESCRIPTION:
##
##  This script extracts molecular barcode tags and removes spacers from unzipped FASTQ
##  files found in the input directory (file names must contain "R1" or "R2"). Barcode
##  extracted FASTQ files are written to the 'fastq_tag' directory and are subsequently
##  aligned with BWA mem. Bamfiles are written to the 'bamfile" directory under the
##  project folder.
##
##====================================================================================
# Help command output
usage()
{
cat << EOF

  FILE:         fastq_to_bam.sh

  USAGE:        fastq_to_bam.sh --input INPUTDIR --output OUTPUTDIR --project PROJECT
                                --barcode 2 --spacer 1 --filter T --ref REF

  OPTIONS:

    -i, --input    Input directory [MANDATORY]
    -o, --output   Output project directory [MANDATORY]
    -p, --project  Project name [MANDATORY]
    -r, --ref      Reference (BWA index) [MANDATORY]
    -b, --barcode  Barcode length [MANDATORY]
    -s, --spacer   Spacer length [MANDATORY]
    -f, --filter   Spacer Filter (e.g. "T" will filter out spacers that are non-T)
    -q, --qsub     qusb directory, default: output/qsub
    -h, --help     Show this message

  DESCRIPTION:

  This script extracts molecular barcode tags and removes spacers from unzipped FASTQ
  files found in the input directory (file names must contain "R1" or "R2"). Barcode
  extracted FASTQ files are written to the 'fastq_tag' directory and are subsequently
  aligned with BWA mem. Bamfiles are written to the 'bamfile" directory under the
  project folder.

EOF
}

################
#    Set-up    #
################
# Error message
error(){
    echo "`cmd`: invalid option -- '$1'";
    echo "Try '`cmd` -h' for more information.";
    exit 1;
}


opts="hi:o:p:r:b:s:f::q"

# There's two passes here: first pass handles long options, second pass uses 'getopt" to canonicalize short options
for pass in 1 2; do
    while [ -n "$OPTION" ]; do
        case $OPTION in
            --) shift; break;;
            -*) case $OPTION in
                -h|--help)
                            usage
                            exit 1
                            ;;
                -i|--input)
                            INPUT=$OPTARG
                            ;;

            *) if [ $pass -eq 1 ]; then ARGS="$ARGS $1";
               else error $1; fi;;
        esac
        shift
    done

    if [ $pass -eq 1 ]
    then
        ARGS='getopt $opts $ARGS'
        if [$? != 0]; then usage; exit; fi; set -- $ARGS
    fi
done



while getopts "hi:o:p:r:b:s:f:q:" OPTION
do
     case $OPTION in
         h)
             usage
             exit 1
             ;;
         i)
             INPUT=$OPTARG
             ;;
         o)
             OUTPUT=$OPTARG
             ;;
         p)
             PROJECT=$OPTARG
             ;;
         r)
             REF=$OPTARG
             ;;
         b)
             BARCODELEN=$OPTARG
             ;;
         s)
             SPACERLEN=$OPTARG
             ;;
         f)
             SPACERFILT=$OPTARG
             ;;
         q)
             QSUBDIR=$OPTARG
             ;;
         ?)
             usage
             exit
             ;;
     esac
done

if [[ -z $INPUT ]] || [[ -z $OUTPUT ]] || [[ -z $PROJECT ]] || [[ -z $REF ]] || [[ -z $BARCODELEN ]] || [[ -z $SPACERLEN ]]
then
     usage
     exit 1
fi


################
#    Modules   #
################
## Load modules
module load python3/3.4.3
module load samtools
module load bwa

##check necessary modules have been loaded
tools="python bwa samtools"
modules=$(module list 2>&1)
for i in $tools
do
    loaded="$(echo $modules|grep -oP "$i.*?([[:space:]]|$)")"
    n=$(wc -l <<<"$loaded")
    if [ "$n" -gt "1" ]; then
        >&2 echo "Error: multiple $i modules were loaded. I am confused."
        exit 1
    fi

    if [[ -z $loaded ]]
    then
        echo Please load module for $i
        exit 1
    else
        eval "${i}_version=$loaded"
        echo "I am going to use $loaded"
    fi
done

##check necessary variables have been set
variables="REF"
for i in $variables; do
    if [[ -z ${!i} ]]; then
        echo "Please set variable $i"
        exit 1
    else
        echo "I am going to use $i=${!i}"
    fi
done

# Set code directory
code_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"


################
#  Create dir  #
################
[ -d $OUTPUT ] || mkdir -p $OUTPUT
: ${QSUBDIR:=$OUTPUT/qsub}
[ -d $QSUBDIR ] || mkdir $QSUBDIR
: ${TAGDIR:=$OUTPUT/fastq_tag}
[ -d $TAGDIR ] || mkdir $TAGDIR
: ${BAMDIR:=$OUTPUT/bamfiles}
[ -d $BAMDIR ] || mkdir $BAMDIR


#####################
# Create sh scripts #
#####################

for R1_file in $( ls $INPUT | grep R1); do
    ################
    #  Set-up IDs  #
    ################
    R2_file=${R1_file//R1/R2}
    filename=${R1_file//_R1/}
    filename=${filename//.fastq/}

    IFS='_' read -a fname_array<<<"$filename"  # Separate filename by "_"
    lane="$(printf -- "%s\n" "${fname_array[@]}" | grep L00)"
    lane_i="$(echo ${fname_array[@]/$lane/-} | cut -d- -f1 | wc -w | tr -d ' ')"
    barcode_i="$(expr $lane_i - 1)"
    barcode=${fname_array[$barcode_i]}

    echo -e "#/bin/bash\n#$ -S /bin/bash\n#$ -cwd\n\nmodule load $python_version\nmodule load $bwa_version\nmodule load $samtools_version\n" > $QSUBDIR/$filename.sh

    #################
    #  Unzip files  #
    #################
    if [[ $R1_file = *"gz" ]]; then
        # Make unzipped file dir
        : ${UNZIPDIR:=$OUTPUT/fastq_unzip}
        [ -d $UNZIPDIR ] || mkdir $UNZIPDIR

        # Create tmp unzipped file
        R1_unzip=${R1_file//.gz/}
        echo -e "zcat $INPUT/$R1_file > $UNZIPDIR/$R1_unzip" >> $QSUBDIR/$filename.sh
        R2_unzip=${R2_file//.gz/}
        echo -e "zcat $INPUT/$R2_file > $UNZIPDIR/$R2_unzip" >> $QSUBDIR/$filename.sh

        R1="$UNZIPDIR/$R1_unzip"
        R2="$UNZIPDIR/$R2_unzip"
    else
        R1="$INPUT/$R1_file"
        R2="$INPUT/$R2_file"
    fi

    #################
    #  Remove tags  #
    #################
    # Change directory so tag stats file will be created in $TAGDIR
    cd $TAGDIR

    # Check if there's a spacer filter
    if [[ -z $SPACERFILT ]]; then
        echo -e "python3 $code_dir/helper/extract_barcodes.py --read1 $R1 --read2 $R2 --outfile $TAGDIR/$filename --blen $BARCODELEN --slen $SPACERLEN \n" >> $QSUBDIR/$filename.sh
    else
        echo -e "python3 $code_dir/helper/extract_barcodes.py --read1 $R1 --read2 $R2 --outfile $TAGDIR/$filename --blen $BARCODELEN --slen $SPACERLEN --sfilt $SPACERFILT \n" >> $QSUBDIR/$filename.sh
    fi

    #################
    #  Align reads  #
    #################
    echo -e "bwa mem -M -t4 -R '@RG\tID:1\tSM:$filename\tPL:Illumina\tPU:$barcode.$lane\tLB:$PROJECT' $REF $TAGDIR/$filename'_barcode_R1.fastq' $TAGDIR/$filename'_barcode_R2.fastq' > $BAMDIR/$filename.sam \n" >>$QSUBDIR/$filename.sh

    # Convert to BAM format and sort by positions
    echo -e "samtools view -bhS $BAMDIR/$filename.sam | samtools sort -@4 - $BAMDIR/$filename \n" >> $QSUBDIR/$filename.sh
    echo -e "samtools index $BAMDIR/$filename.bam" >> $QSUBDIR/$filename.sh

    # Remove sam file
    echo -e "rm $BAMDIR/$filename.sam" >> $QSUBDIR/$filename.sh

    #########################
    # Remove unzipped files #
    #########################
    # Don't want to remove entire folder as there may be other files used by other scripts
    if [[ $UNZIPDIR ]]; then
        echo -e "rm $UNZIPDIR/$R1_unzip" >> $QSUBDIR/$filename.sh
        echo -e "rm $UNZIPDIR/$R2_unzip" >> $QSUBDIR/$filename.sh
    fi

    cd $QSUBDIR
    qsub $QSUBDIR/$filename.sh
done
