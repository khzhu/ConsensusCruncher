#!/usr/bin/env python

###############################################################
#
#                          Consensus Helper
#
# Author: Nina Wang
# Last Modified: May 18, 2016
# Date Created: Mar 24, 2016
###############################################################
# Function: 
# Written for Python 3.5.1
# 
# uid_dict(bamfile): create bam_read dictionaries and counts number of reads
# read_mode(field, bam_reads): return most common occurrence in a specified field of read (e.g. cigar, etc)
# create_aligned_segment(bam_reads, sscs, sscs_qual): Create consensus bam read
#
# Inputs: 
# 1. A position-sorted paired-end BAM file containing reads with a duplex tag 
#    in the header.  
#
# Description:
# Helper functions for single strand and duplex consensus making
#
###############################################################

import pysam # Need to install
import collections
import re
import array
from random import randint
from argparse import ArgumentParser

###############################
##         Functions         ##
###############################

def sscs_qname(tag, flag):
    '''(str, int) -> str
    Return new tag/queryname for consensus sequences:
    barcode_chr_start_chr_end_strand_flags
    
    * Since multiple reads go into making a consensus, a new unique identifier 
    is required to match up the read with its pair *
    
    Note: chr of read and mate pair are used in case of translocations. 
    In addition, coordinates are ordered from low -> high
    
    Examples:
    (+)                  [Flag]
    ACGT_1_1_1_230_fwd_R1 [99] --> ACGT_chr1_1_chr1_230_pos_99_147
    ACGT_1_230_1_1_rev_R2 [147]
    
    (-)
    ACGT_1_230_1_1_rev_R1 [83] --> ACGT_chr1_1_chr1_230_neg_83_163
    ACGT_1_1_1_230_fwd_R2 [163]

    
    ATGT_1_249239818_1_10060_fwd_R1 [65] --> ATGT_1_10060_1_249239818_pos_65_129
    ATGT_1_10060_1_249239818_fwd_R2 [129]
    
    
    Special cases (duplex and pair reads all in the same orientation):
    ['AGAG_3_178919046_8_75462483_rev_R1', 'AGAG_3_178919046_8_75462483_rev_R2',
    'AGAG_8_75462483_3_178919046_rev_R2', 'AGAG_8_75462483_3_178919046_rev_R1']
    - Use coordinate and flags to differentiate between strand

    Test cases:
    >>> sscs_qname('CCCC_12_25398064_12_25398156_fwd_R1', 99)
    'CCCC_12_25398064_12_25398156_pos_99_147
    >>> sscs_qname('CCCC_12_25398156_12_25398064_rev_R2', 147)
    'CCCC_12_25398064_12_25398156_99_147'
    >>> sscs_qname('CCCC_12_25398156_12_25398064_rev_R1', 83)
    'CCCC_12_25398064_12_25398156_83_163'
    >>> sscs_qname('CCCC_12_25398064_12_25398156_fwd_R2', 163)
    'CCCC_12_25398064_12_25398156_83_163'

    
    Translocation:
    >>> sscs_qname('TGGT_1_21842527_13_72956752_rev_R1', 113)
    'TGGT_1_21842527_13_72956752_pos_113_177'
    >>> sscs_qname('TGGT_13_72956752_1_21842527_rev_R2', 177)
    'TGGT_1_21842527_13_72956752_pos_113_177'
    >>> sscs_qname('TTCA_0_2364_10_135461271_fwd_R1', 65)
    'TTCA_0_2364_10_135461271_pos_65_129'
    >>> sscs_qname('TTCA_10_135461271_0_2364_fwd_R2', 129)
    'TTCA_0_2364_10_135461271_pos_65_129'
    
    
    I THINK NAMES ARE NOT UNIQUE ENOUGH FOR LARGER DATASETS -> not true, they are unique
    '''
    
    flag_pairings = {99:147, 147:99, 83:163, 163:83, \
                     # mapped within insert size, but wrong orientation (++, --)
                     67:131, 131:67, 115:179, 179:115, \
                     ## === translocations ===
                     # mapped uniquely, but wrong insert size
                     81:161, 161:81, 97:145, 145:97, \
                     # wrong insert size and wrong orientation
                     65:129, 129:65, 113:177, 177:113
                     }
    
    ## Flags indicating read from positive strand
    pos_flag = [99, 147, 67, 131, 97, 145, 65, 129]    

    ref_chr = tag.split("_")[1]
    mate_chr = tag.split("_")[3]
    ref_coor = tag.split("_")[2]
    mate_coor = tag.split("_")[4]

    # === Order qname by chr coordinate ===
    # e.g. CCCC_12_25398156_12_25398064 -> CCCC_12_25398064_12_25398156
    if (int(ref_coor) > int(mate_coor) and ref_chr == mate_chr) or \
       (int(ref_chr) > int(mate_chr) and ref_chr != mate_coor):
        new_tag = tag.split("_")
        new_tag[1] = mate_chr # swap ref with mate
        new_tag[3] = ref_chr
        new_tag[2] = mate_coor
        new_tag[4] = ref_coor
        new_tag = "_".join(new_tag)[:-7]
        # Determine strand 
        if 'R1' in tag: # rev_R1
            new_tag = new_tag + '_neg'
        else: # rev_R2
            new_tag = new_tag + '_pos'
    else:
        ## === Use flags to determine strand direction === 
        ## for reads with the same coordinate mate (start and stop are the same)
        consensus_tag = tag[:-7]
        if ref_chr == mate_chr and ref_coor == mate_coor:
            if flag in pos_flag:
                new_tag = consensus_tag + '_pos'
            else:
                new_tag = consensus_tag + '_neg'
        elif 'R1' in tag: # fwd_R1
            new_tag = consensus_tag + '_pos'
        else: # fwd_R2
            new_tag = consensus_tag + '_neg'

    # === Add flag information to query name ===
    # Need pos/neg to differentiate between reads with same flag from diff strands (e.g. 113, 177)
    # with smaller flag ordered first, to help differentiate between reads 
    # (e.g. read and its duplex might have same coordinate and strand direction, 
    # after ordering coordinates from smallest -> biggest) 
    if flag < flag_pairings[flag]:
        new_tag = '{}_{}_{}'.format(new_tag, flag, flag_pairings[flag])
    else:
        new_tag = '{}_{}_{}'.format(new_tag, flag_pairings[flag], flag)
    
    return new_tag


def which_read(flag):
    '''(int) -> str
    Returns str indicating read 1 or 2 based on flag.
    '''
    read1 = [99, 83, 67, 115, 81, 97, 65, 113]
    read2 = [147, 163, 131, 179, 161, 145, 129, 177]
    
    if flag in read1:
        read = 'R1'
    elif flag in read2:
        read = 'R2'
    else:
        print('UNMAPPED READ ERROR')
        print(flag)
    
    return read


def which_ori_strand(flag):
    '''(int) -> str
    Return str indicating direction of original DNA strand based on flags.
    '''
    pos = [99, 147, 67, 131, 81, 161, 65, 129]
    neg = [83, 163, 115, 179, 97, 145, 113, 177]
    
    if flag in pos:
        strand = 'pos'
    elif flag in neg:
        strand = 'neg'
    else:
        print('STRAND ERROR')
        print(flag)
        
    return strand
    

def read_bam(bamfile, pair_dict, read_dict, tag_dict, read_pair_dict, badRead_bam, read_chr = None, 
             read_start = None, read_end = None, duplex = None):
    '''(bamfile object, dict, dict, dict, str, int, int, str) -> 
    dict, dict, dict, dict, dict, int, int, int, int
    
    === Input === 
    - bamfile: pysam.AlignmentFile object
    - read_chr: string of chromosome region to fetch reads
    - read_start: integer of starting position to fetch reads
    - read_end: integer of stopping position to fetch reads
    - duplex: any string or bool specifying duplex consensus making,
              query name for SSCS and DCS differ
    - pair_dict: {query name: [read_tag, mate_tag]} -> dictionary of paired tags 
                  (retains data from translocations or reads crossing cytobands 
                  to preserve pairing as reads are divided into sections for 
                  consensus making of large bam files)
    - read_dict: {read_tag: [<pysam.calignedsegment.AlignedSegment>, 
                  <pysam.calignedsegment.AlignedSegment>, ..etc.]}
    - tag_dict: integer dictionary indicating number of reads in each read family 
                 {read_tag: 2, ..etc}
    
    === Output ===
    1) read_dict: dictionary of bamfile reads 
                 {read_tag: [<pysam.calignedsegment.AlignedSegment>, 
                 <pysam.calignedsegment.AlignedSegment>, ..etc.]} 
                 - Key: barcode_chr_startR1_startR2_strand_ReadNum
                 - Value: list of bamfile reads
    2) tag_dict: integer dictionary indicating number of reads in each read family 
                 {read_tag: 2, ..etc} 
    3) pair_dict: dictionary of paired tags  
                    {query name: [read_tag, mate_tag]}
    4) counter: total number of reads
    5) unmapped: reads without a flag
    6) unmapped_flag: unmapped reads or unmapped mates
    7) bad_reads: number of reads that not properly mapped 
                  - secondary reads: same sequence aligns to multiple locations
                  - supplementary reads: multiple parts of sequence align to 
                                         multiple locations
    '''
    if read_chr == None:
        bamLines = bamfile.fetch(until_eof = True)
    else:
        bamLines = bamfile.fetch(read_chr, read_start, read_end)
        
    unmapped = 0
    unmapped_flag = 0
    bad_reads = 0 # secondary/supplementary reads
    counter = 0   
    
    for line in bamLines:
        counter += 1
        
        ### === Filter out 'bad' reads ====
        # Unmapped flags
        bad_flags = [73, 133, 89, 121, 165, 181, 101, 117, 153, 185, 69, 137, 77, 141]
        badRead = False
        if line.is_unmapped: # flag != 0
            unmapped += 1
            badRead = True
        elif line.is_secondary:
            bad_reads += 1
            badRead = True
        elif line.is_supplementary:
            bad_reads += 1
            badRead = True
        elif line.flag in bad_flags:
            unmapped_flag += 1
            badRead = True
        else:
            # Should no longer get this error with samtools calmd creating MD 
            # tags for those missed by bwa mem
            if duplex == None or duplex == False:
                try:
                    line.get_tag('MD')
                except:
                    print('MD error')
                    print(line)
                    badRead = True        
        
        ### MOVE UNMAPPED READS INTO SEPARATE FILE        
        if badRead:
            badRead_bam.write(line)
        else:
            ### === Add reads to dictionary as pairs ===
            if line in read_pair_dict[line.qname]:
                print('Read already read once!')
                print(read_chr, read_start, read_end)
                print(line.qname)
                print(line)
                print(read_pair_dict[line.qname])
                #print(tag)
                #print(read)
                #print(read_dict[tag])
                counter -= 1                
            else:
                read_pair_dict[line.qname].append(line)
            
                if len(read_pair_dict[line.qname]) == 2:
                    ## == Add cigar string to tag ==
                    # Pos strand, R1 cigar first | Neg strand, R2 cigar first 
                    ori_strand = which_ori_strand(read_pair_dict[line.qname][0].flag)
                    read_num = which_read(read_pair_dict[line.qname][0].flag)
                    
                    if (ori_strand == 'pos' and read_num == 'R1') or \
                       (ori_strand == 'neg' and read_num == 'R2'):
                        softclip = '{}_{}'.format(read_pair_dict[line.qname][0].cigarstring, 
                                         read_pair_dict[line.qname][1].cigarstring)
                    else:
                        softclip = '{}_{}'.format(read_pair_dict[line.qname][1].cigarstring, 
                                         read_pair_dict[line.qname][0].cigarstring)        
                    
                    for read in read_pair_dict[line.qname]:
                        ## Barcodes extracted from diff position for duplex                
                        if duplex == None or duplex == False:
                            # SSCS query name: H1080:278:C8RE3ACXX:6:1308:18882:18072|CACT 
                            barcode = read.qname.split("|")[1] 
                        else:
                            # DCS query name: CCTG_12_25398000_12_25398118_neg_83_163:56
                            barcode = read.qname.split("_")[0]             
                        
                        # == identify read ==
                        readNum = which_read(read.flag)   
                        strand = 'fwd'
                        if read.is_reverse:
                            strand = 'rev'        
                    
                        tag = '{}_{}_{}_{}_{}_{}_{}_{}'.format(barcode, # mol barcode
                                                      read.reference_id, # chr num
                                                      read.reference_start, # start R1 (0-based)
                                                      read.next_reference_id,
                                                      read.next_reference_start, # start R2
                                                      softclip,
                                                      #pair_flag,
                                                      strand, # strand direction
                                                      readNum
                                                      )
                        
                        consensus_tag = sscs_qname(tag, int(read.flag))  
                    
                        if tag not in read_dict and tag not in tag_dict:                            
                            read_dict[tag] =[read]
                            
                            # Only add tag to pair_dict once (aka first time creating tag) 
                            if consensus_tag not in pair_dict:
                                pair_dict[consensus_tag] = [tag]
                            else:
                                pair_dict[consensus_tag].append(tag)            
        
                        else:
                            try:
                                if read not in read_dict[tag]:
                                    read_dict[tag].append(read)
                                else:
                                    print('read read multiple times!')
                            except KeyError:
                                # If tag found in tag_dict, but not read_dict means line was previously read and written to file (hence removal from read_dict but presence in tag_dict)
                                print('Pair already written: line read twice - double check to see if its overlapping/near cytoband region (point of data division)')
                                print(read_chr, read_start, read_end)
                                print(tag)
                                print(read)
                                print(tag_dict[tag])
                                print(consensus_tag)
                                print(tag in tag_dict)
                                #print(pair_dict[consensus_tag])
                                counter -= 1
                                continue                            

                        tag_dict[tag] += 1
                    read_pair_dict.pop(line.qname)
                
    return read_dict, tag_dict, pair_dict, read_pair_dict, counter, unmapped, unmapped_flag, \
           bad_reads        
    
    
def read_mode(field, bam_reads):
    '''(str, lst) -> str
    Return mode (most common occurrence) of specified field 
    e.g. cigarstring, flag, mapping quality, template_length
    '''
    field = 'i.{}'.format(field)
    # Rank by number of occurrences 
    field_lst = collections.Counter(eval(field) for i in bam_reads).most_common() 
    # Take max occurrences
    common_field_lst = [i for i, j in field_lst if j == field_lst[0][1]] 
    # Randomly select max if there's multiple   
    common_field = common_field_lst[randint(0, len(common_field_lst)-1)] 
    
    return common_field


def create_aligned_segment(bam_reads, sscs, sscs_qual):
    '''(list, str, list) -> pysam object
    Return pysam object with new consensus seq given list of bam reads.
    
    '''
    # Find most common cigar seq
    common_cigar = read_mode('cigarstring', bam_reads)
    
    # Find first read with most common cigar and set as template read for SSCS
    template_index = [i.cigarstring for i in bam_reads].index(common_cigar)    
    template_read = bam_reads[template_index]
    #print(template_read)
    
    # Create bam read based on template read
    SSCS_read = pysam.AlignedSegment()
    SSCS_read.query_name = template_read.query_name
    SSCS_read.flag = read_mode('flag', bam_reads) # Take most common flag
    SSCS_read.query_sequence = sscs
    SSCS_read.reference_id = template_read.reference_id
    SSCS_read.reference_start = template_read.reference_start
    SSCS_read.mapping_quality = read_mode('mapping_quality', bam_reads) # Most common mapping quality
    SSCS_read.cigar = template_read.cigar
    SSCS_read.next_reference_id= template_read.next_reference_id
    SSCS_read.next_reference_start = template_read.next_reference_start  
    SSCS_read.template_length = read_mode('template_length', bam_reads)
    SSCS_read.query_qualities = sscs_qual
    
    SSCS_read.set_tag('RG', read_mode("get_tag('RG')", bam_reads))
    #SSCS_read.set_tag('MD', )
    
    
    # --NOTE: Tags currently disabled as it gives errors when bams are loaded into IGV 
    #print(read_mode("get_tag('RG')", bam_reads))
    #SSCS_read.tags = read_mode("get_tag('RG')", bam_reads)
    #tag_index = [x for x, y in enumerate(SSCS_read.tags) if y[0] == 'MD'][0]
    #SSCS_read.tags[tag_index] = read_mode("get_tag('MD')", bam_reads)
    #SSCS_read.tags[tag_index] = read_mode("get_tag('RG')", bam_reads)
    
    return SSCS_read


def reverse_seq(seq):
    '''(str) -> str
    Return reverse compliment of sequence (used for writing rev comp sequences to fastq files).
    
    >>> reverse_seq('TCAGCATAATT')
    'AATTATGCTGA'
    >>> reverse_seq('ACTGNN')
    'NNCAGT'
    '''
    rev_comp = ''
    nuc = {'A':'T', 'C':'G', 'G':'C', 'T':'A', 'N':'N'}
    for base in seq:
        rev_comp = nuc[base] + rev_comp
        
    return rev_comp


################################
###           Main            ##
################################
if __name__ == "__main__": 
    import time
    import pysam
    start_time = time.time()
    #bamfile = pysam.AlignmentFile('/Users/nina/Desktop/Ninaa/PughLab/Molecular_barcoding/code/pl_duplex_sequencing/subsampled_bam/MEMU/MEM-001-p015625.bam', "rb")
    
    bamfile = pysam.AlignmentFile('/Users/nina/Desktop/Ninaa/PughLab/Molecular_barcoding/code/pl_duplex_sequencing/subsampled_bam/CAP-001-p0078125.sort.bam', "rb")
    
    #bamfile = pysam.AlignmentFile('/Users/nina/Desktop/Ninaa/PughLab/Molecular_barcoding/code/PL_consensus_test/test/MEM-001_KRAS.bam', "rb")
    badRead_bam = pysam.AlignmentFile('MEM-001.badReads.bam', "wb", template = bamfile)
    
    bam_dict = collections.OrderedDict() # dict that remembers order of entries
    tag_dict = collections.defaultdict(int)
    pair_dict = collections.OrderedDict()
    
    #tag_quality_dict = collections.defaultdict(list)
    quality_dict = collections.defaultdict(list)
    prop_dict = collections.defaultdict(list)
    
    read_pair_dict = collections.defaultdict(list)    
    
    chr_data = read_bam(bamfile, 
                        pair_dict = pair_dict, 
                        read_dict = bam_dict,
                        tag_dict = tag_dict,
                        badRead_bam = badRead_bam,
                        read_pair_dict = read_pair_dict)    
    print((time.time() - start_time)/60)  
    
    bam_dict = chr_data[0]
    tag_dict = chr_data[1]
    pair_dict = chr_data[2]
    
    read_pair_dict = chr_data[3]    
    
    print([x for x in pair_dict.values() if len(x) !=2])

    ### ==== Comparisons ====
    # S/M tags
    # [(1, 650432), (2, 162078), (3, 33644), (4, 6414), (5, 1174), (6, 254), (7, 44), (8, 6), (9, 4)]

    # cigar tags
    #[(1, 653070), (2, 161162), (3, 33432), (4, 6394), (5, 1156), (6, 254), (7, 44), (8, 6), (9, 4)]
    
    #for pair in pair_dict.keys():
        #for tag in pair_dict[pair]:
            #barcode = tag.split('_')[0]
            #barcode_bases = int(len(barcode)/2)
            #pair_barcode = barcode[barcode_bases:] + barcode[:barcode_bases]        
            #read_num = tag[-2:]
            #if read_num == 'R1':
                #read_num = 'R2'
            #else:
                #read_num = 'R1'                
            ## duplex tag
            #ds = pair_barcode + '_' + tag.split('_', 1)[1][:-2] + read_num    
            #if ds in bam_dict:
                #if 'S' in tag:
                    #if tag_dict[ds] > 2:
                        #print(pair)
                        #print('tag')
                        #print(tag)
                        #print('duplex')
                        #print(ds)    
    
    #CGCG_7_55241607_7_55241607_84M14S_15S83M_neg_83_163
    #tag
    #CGCG_7_55241607_7_55241607_84M14S_15S83M_fwd_R2
    #duplex
    #CGCG_7_55241607_7_55241607_84M14S_15S83M_fwd_R1
    
    #CGCG_7_55241607_7_55241607_84M14S_15S83M_pos_99_147
    #tag
    #CGCG_7_55241607_7_55241607_84M14S_15S83M_rev_R1
    #duplex
    #CGCG_7_55241607_7_55241607_84M14S_15S83M_rev_R2
    
    
    #for dup in ['CGCG_7_55241607_7_55241607_84M14S_15S83M_fwd_R2', 'CGCG_7_55241607_7_55241607_84M14S_15S83M_fwd_R1', \
                #'CGCG_7_55241607_7_55241607_84M14S_15S83M_rev_R1', 'CGCG_7_55241607_7_55241607_84M14S_15S83M_rev_R2']:
        #print(dup)
        #for read in bam_dict[dup]:
            #print(read)    
    