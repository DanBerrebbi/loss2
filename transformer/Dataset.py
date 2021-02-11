# -*- coding: utf-8 -*-

import sys
import os
import logging
import numpy as np
from collections import defaultdict

##############################################################################################################
### Batch ####################################################################################################
##############################################################################################################
class Batch():
  def __init__(self, batch_size, batch_type):
    super(Batch, self).__init__()
    self.batch_size = batch_size
    self.batch_type = batch_type
    self.idxs_pos = []
    self.max_lsrc = 0
    self.max_ltgt = 0

  def fits(self, lsrc, ltgt):
    ### returns True if a new example with lengths (lsrc, ltgt) can be kept in batch
    ### False otherwise
    if self.batch_type == 'tokens':
      if max(lsrc,self.max_lsrc) * (len(self.idxs_pos)+1) > self.batch_size:
        return False
      if max(ltgt,self.max_ltgt) * (len(self.idxs_pos)+1) > self.batch_size:
        return False
    elif self.batch_type == 'sentences':
      if len(self.idxs_pos) == self.batch_size:
        return False
    else:
      logging.error('Bad -batch_type option')
      sys.exit()
    return True

  def add(self, pos, lsrc, ltgt):
    ### adds the example (pos) with lengths (lsrc, ltgt) in batch
    self.idxs_pos.append(pos)
    self.max_lsrc = max(lsrc,self.max_lsrc)
    self.max_ltgt = max(ltgt,self.max_ltgt)
    return True

  def __len__(self):
    return len(self.idxs_pos)

  def idxs_pos(self):
    return self.idxs_pos

##############################################################################################################
### Dataset ##################################################################################################
##############################################################################################################
class Dataset():
  def __init__(self, vocab_src, token_src, ftxt_src, vocab_tgt, token_tgt, ftxt_tgt=None, shard_size=100000, batch_size=64, batch_type='sentences', max_length=100):    
    super(Dataset, self).__init__()
    assert vocab_src.idx_pad == vocab_tgt.idx_pad
    assert vocab_src.idx_bos == vocab_tgt.idx_bos
    assert vocab_src.idx_eos == vocab_tgt.idx_eos
    self.shard_size = shard_size
    self.batch_type = batch_type
    self.batch_size = batch_size
    self.max_length = max_length
    self.vocab_src = vocab_src
    self.vocab_tgt = vocab_tgt
    self.token_src = token_src
    self.token_tgt = token_tgt
    self.ftxt_src = ftxt_src
    self.ftxt_tgt = ftxt_tgt

    ### original corpora
    self.lines_src = None
    self.lines_tgt = None
    self.idxs_src = None
    self.idxs_tgt = None
    self.idxs_pos = None ### order in which corpora is traversed to build shards/batches

    with open(ftxt_src) as f:
      self.lines_src = f.read().splitlines()
      self.idxs_src = [None] * len(self.lines_src)

    if self.shard_size == 0:
      self.shard_size = len(self.lines_src) ### all examples in one shard
      logging.info('shard_size set to {}'.format(self.shard_size))

    if ftxt_tgt is not None:
      with open(ftxt_tgt) as f:
        self.lines_tgt = f.read().splitlines()
        self.idxs_tgt = [None] * len(self.lines_tgt)

      if len(self.lines_src) != len(self.lines_tgt):
        logging.error('Different number of lines in parallel dataset {}-{}'.format(len(self.lines_src),len(self.lines_tgt)))
        sys.exit()

    self.idxs_pos = [i for i in range(len(self.lines_src))]

    logging.info('Read dataset with {}-{} sentences {}-{}'.format(len(self.lines_src), len(self.lines_tgt), ftxt_src, ftxt_tgt))


  def build_batchs(self, lens, idxs_pos):
    batchs = []
    ordered = np.argsort(lens) # sort by lens (lower to higher lenghts)
    idxs_pos = idxs_pos[ordered]

    b = Batch(self.batch_size, self.batch_type) #empty batch
    for pos in idxs_pos:
      lsrc = len(self.idxs_src[pos])
      ltgt = len(self.idxs_tgt[pos]) if self.idxs_tgt is not None else 0

      if not b.fits(lsrc,ltgt): ### cannot add in current batch b
        if len(b):
          ### save batch
          batchs.append(b.idxs_pos())
          ### start a new batch 
          b = Batch(self.batch_size, self.batch_type) #empty batch

      if b.fits(lsrc,ltgt):
        ### add current example
        b.add(pos,lsrc,ltgt)
      else:
        ### discard current example
        logging.warning('Example {} does not fit in empty batch [Discarded] {}-{}'.format(pos,self.ftxt_src,self.ftxt_tgt))

    if len(b): 
      ### save batch
      batchs.append(b.idxs_pos())

    return batchs


  def get_shard(self, shard):
    ### for pos in shard:
    ### tokenizes and finds indexes into self.idxs_src, self.idxs_tgt if not done
    ### filter out examples (self.length) and returns (len, pos) of those kept
    idxs_len = []
    idxs_pos = []
    n_filtered = 0
    n_src_tokens = 0
    n_tgt_tokens = 0
    n_src_unks = 0
    n_tgt_unks = 0
    for pos in shard:
      ### SRC ###
      if self.idxs_src[pos] is None:
        tok_src = [self.vocab_src.str_bos] + self.token_src.tokenize(self.lines_src[pos]) + [self.vocab_src.str_eos]
        self.idxs_src[pos] = [self.vocab_src[t] for t in tok_src]

      if self.max_length and len(self.idxs_src[pos]) > self.max_length:
        n_filtered += 1
        continue

      if self.lines_tgt is not None:
        ### TGT ###
        if self.idxs_tgt[pos] is None:
          tok_tgt = [self.vocab_tgt.str_bos] + self.token_tgt.tokenize(self.lines_tgt[pos]) + [self.vocab_tgt.str_eos] 
          self.idxs_tgt[pos] = [self.vocab_tgt[t] for t in tok_tgt]

        if self.max_length and len(self.idxs_tgt[pos]) > self.max_length:
          n_filtered += 1
          continue
      ###################
      ### ADD example ###
      ###################
      idxs_pos.append(pos)
      idxs_len.append(len(self.idxs_src[pos]))

      n_src_tokens += len(self.idxs_src[pos])
      n_src_unks += sum([i==self.vocab_src.idx_unk for i in self.idxs_src[pos]])
      #print(['{}:{}'.format(tok[i],idx[i]) for i in range(len(tok))])

      if self.lines_tgt is not None:
        n_tgt_tokens += len(self.idxs_tgt[pos])
        n_tgt_unks += sum([i==self.vocab_tgt.idx_unk for i in self.idxs_tgt[pos]])
        #print(['{}:{}'.format(tok[i],idx[i]) for i in range(len(tok))])

      if len(idxs_pos) == self.shard_size:
        break

    logging.info('Built shard with {} examples ~ {}-{} tokens ~ {}-{} OOVs ~ {} filtered examples {}-{}'.format(len(idxs_pos), n_src_tokens, n_tgt_tokens, n_src_unks, n_tgt_unks, n_filtered, self.ftxt_src, self.ftxt_tgt))
    return idxs_len, idxs_pos


  def __iter__(self):
    ##########################
    ### randomize all data ###
    ##########################
    np.random.shuffle(self.idxs_pos)
    logging.info('Shuffled Dataset with {} examples'.format(len(self.idxs_pos)))
    ###############################
    ### split dataset in shards ###
    ###############################
    shards = [self.idxs_pos[i:i+self.shard_size] for i in range(0, len(self.idxs_pos), self.shard_size)]
    for shard in shards: #each shard is a list of positions referring the original corpus
      ####################
      ### format shard ###
      ####################
      lens, idxs_pos = self.get_shard(shard)
      ####################
      ### build batchs ###
      ####################
      batchs = self.build_batchs(lens, idxs_pos)
      idxs_batchs = [i for i in range(len(batchs))]
      np.random.shuffle(idxs_batchs)
      logging.info('Shuffled shard with {} batchs'.format(len(idxs_batchs)))
      for i in idxs_batchs:
        idxs_pos = batchs[i]
        idxs_src = []
        idxs_tgt = []
        for pos in idxs_pos:
          idxs_src.append(self.idxs_src[pos])
          idxs_tgt.append(self.idxs_tgt[pos])
        yield [idxs_pos, idxs_src, idxs_tgt]

