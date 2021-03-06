import subprocess

import numpy as np
import chainer
from chainer import training
from chainer.training import extensions

from chainer.training import triggers
from chainer import reporter
from chainer.datasets import tuple_dataset
import os
import logging

from m_reader import *
from mreader_v6 import *
# from argparse import ArgumentParser
import argparse
import random

from utils import *
from mreader_evaluate import *
from mreader_evaluate_pred import *
import pickle

# Defaults
DATA_DIR = os.path.join('data', 'datasets')
MODEL_DIR = os.path.join('data', 'models')
EMBED_DIR = os.path.join('data', 'embeddings')


def str2bool(v):
    return v.lower() in ('yes', 'true', 't', '1', 'y')


def add_train_args(parser):
    """Adds commandline arguments pertaining to training a model. These
    are different from the arguments dictating the model architecture.
    """
    parser.register('type', 'bool', str2bool)

    # Runtime environment
    runtime = parser.add_argument_group('Environment')
    runtime.add_argument('--no-cuda', type='bool', default=False,
                         help='Train on CPU, even if GPUs are available.')
    runtime.add_argument('--gpu', type=int, default=-1,
                         help='Run on a specific GPU')
    runtime.add_argument('--random-seed', type=int, default=1013,
                         help=('Random seed for all numpy/cuda '
                               'operations (for reproducibility)'))
    runtime.add_argument('--num-epochs', type=int, default=40,
                         help='Train data iterations')
    runtime.add_argument('--batch-size', type=int, default=45,
                         help='Batch size for training')
    runtime.add_argument('--test-batch-size', type=int, default=32,
                         help='Batch size during validation/testing')
    runtime.add_argument('--dropout', type=float, default=0.2,
                         help='Dropout for training')
    runtime.add_argument('--char-dropout', type=float, default=0.2,
                         help='Dropout for character embedding')
    runtime.add_argument('--hops', type=int, default=1,
                         help='Hops for aligners')
    runtime.add_argument('--ptr-hops', type=int, default=1,
                         help='Hops for pointer-network')

    runtime.add_argument('--encoder-dropout', type=float, default=0,
                         help='Dropout for lstm encoder')

    runtime.add_argument('--lambda-param', type=float, default=1.0,
                         help='training weight for mreader and rl')

    # runtime.add_argument('--fine-tune', type=bool, default='false',
    #                     help='use RL or not')
    runtime.add_argument('--fine-tune', action="store_true")

    runtime.add_argument('--gamma', type=float, default=0,
                         help='reattention weight')

    runtime.add_argument('--nonlinear_dim', type=int, default=50,
                         help='nonlinear transformation')

    runtime.add_argument('--learning-rate', type=float, default=0.0008,
                         help='learning rate')

    runtime.add_argument('--predict', action="store_true")

    runtime.add_argument('--train-ratio', type=float, default=0.005)
    runtime.add_argument('--dev-ratio', type=float, default=0.05)

    # Files
    files = parser.add_argument_group('Filesystem')
    files.add_argument('--model-dir', type=str, default=MODEL_DIR,
                       help='Directory for saved models/checkpoints/logs')
    files.add_argument('--model-name', type=str, default='',
                       help='Unique model identifier (.mdl, .txt, .checkpoint)')
    files.add_argument('--data-dir', type=str, default=DATA_DIR,
                       help='Directory of training/validation data')
    files.add_argument('--train-file', type=str,
                       default='SQuAD-train-v1.1-processed-spacy.txt',
                       help='Preprocessed train file')
    files.add_argument('--dev-file', type=str,
                       default='SQuAD-dev-v1.1-processed-spacy.txt',
                       help='Preprocessed dev file')
    files.add_argument('--train-json', type=str, default='SQuAD-train-v1.1.json',
                       help=('Unprocessed train file to run validation '
                             'while training on'))
    files.add_argument('--dev-json', type=str, default='SQuAD-dev-v1.1.json',
                       help=('Unprocessed dev file to run validation '
                             'while training on'))
    files.add_argument('--embed-dir', type=str, default=EMBED_DIR,
                       help='Directory of pre-trained embedding files')
    files.add_argument('--embedding-file', type=str,
                       # default='glove.840B.300d.txt',
                       default='glove.6B.100d.txt',
                       help='Space-separated pretrained embeddings file')
    files.add_argument('--char-embedding-file', type=str,
                       default='glove.840B.300d-char.txt',
                       help='Space-separated pretrained embeddings file')

    # Saving + loading
    save_load = parser.add_argument_group('Saving/Loading')
    save_load.add_argument('--checkpoint', type='bool', default=False,
                           help='Save model + optimizer state after each epoch')
    save_load.add_argument('--pretrained', type=str, default='',
                           help='Path to a pretrained model to warm-start with')
    save_load.add_argument('--expand-dictionary', type='bool', default=False,
                           help='Expand dictionary of pretrained model to ' +
                                'include training/dev words of new data')

    # General
    general = parser.add_argument_group('General')
    general.add_argument('--official-eval', type='bool', default=True,
                         help='Validate with official SQuAD eval')
    general.add_argument('--valid-metric', type=str, default='exact_match',
                         help='The evaluation metric used for model selection: None, exact_match, f1')
    general.add_argument('--display-iter', type=int, default=25,
                         help='Log state after every <display_iter> epochs')
    general.add_argument('--context-max-length', type=int, default=300,
                         help='Max length of context(paragraph or document)')
    general.add_argument('--log-interval', type=int, default=1,
                         help='Log interval')

    # Layer settings
    layer = parser.add_argument_group('Layer')
    layer.add_argument('--char-hidden-size', type=int, default=50,
                       help='Dimensions of character hidden state')
    layer.add_argument('--encoder-hidden-size', type=int, default=100,
                       help='Dimensions of hidden state')

    # Optimizer
    optimizer_setting = parser.add_argument_group('Optimizer_setting')
    optimizer_setting.add_argument('--reader-optimizer', type=str, default='Adam',
                                   help='Optimizer for training mreader')
    optimizer_setting.add_argument('--reader-initial-learning-rate', type=float, default=0.0008,
                                   help='Initial learning rate for training mreader')
    optimizer_setting.add_argument('--rl-optimizer', type=str, default='SGD',
                                   help='Optimizer for training RL')
    optimizer_setting.add_argument('--rl-initial-learning-rate', type=float, default=0.0001,
                                   help='Initial learning rate for training RL')

    # elmo
    elmo_arg = parser.add_argument_group('Elmo')
    elmo_arg.add_argument('--vocab-file', type=str, default="", help="precomputed elmo vocab file")
    elmo_arg.add_argument('--embedding-token-file', type=str, default="",
                          help="precomputed elmo embedding file (for initialization?)")
    elmo_arg.add_argument('--options-file', type=str, default="", help="elmo options file")
    elmo_arg.add_argument('--weight-file', type=str, default="", help="elmo weight file")
    elmo_arg.add_argument('--use-elmo', action="store_true")
    elmo_arg.add_argument('--context-elmo-embedding', type=str, default="", help="precomputed elmo document embedding")
    elmo_arg.add_argument('--question-elmo-embedding', type=str, default="", help="precomputed elmo question embedding")

    # dictionary
    dict_arg = parser.add_argument_group('Dictionary')
    elmo_arg.add_argument('--use-dict', action="store_true")
    dict_arg.add_argument('--dict-embedding-dim', type=int, default=300)
    dict_arg.add_argument('--dictionary-file', type=str, default="")
    dict_arg.add_argument('--dict-embedding-file', type=str, default="")
    dict_arg.add_argument('--dict-max-length', type=int, default=100)
    dict_arg.add_argument('--dict-dropout', type=float, default=0.0)


def set_defaults(args):
    """Make sure the commandline arguments are initialized properly."""
    # Check critical files exist
    args.train_json = os.path.join(args.data_dir, args.train_json)
    if not os.path.isfile(args.train_json):
        raise IOError('No such file: %s' % args.train_json)

    args.dev_json = os.path.join(args.data_dir, args.dev_json)
    if not os.path.isfile(args.dev_json):
        raise IOError('No such file: %s' % args.dev_json)

    args.train_file = os.path.join(args.data_dir, args.train_file)
    if not os.path.isfile(args.train_file):
        raise IOError('No such file: %s' % args.train_file)

    args.dev_file = os.path.join(args.data_dir, args.dev_file)
    if not os.path.isfile(args.dev_file):
        raise IOError('No such file: %s' % args.dev_file)

    if args.embedding_file:
        args.embedding_file = os.path.join(args.embed_dir, args.embedding_file)
        if not os.path.isfile(args.embedding_file):
            raise IOError('No such file: %s' % args.embedding_file)

    if args.char_embedding_file:
        args.char_embedding_file = os.path.join(args.embed_dir, args.char_embedding_file)
        if not os.path.isfile(args.char_embedding_file):
            raise IOError('No such file: %s' % args.char_embedding_file)

    # Set model directory
    subprocess.call(['mkdir', '-p', args.model_dir])

    # Set model name
    if not args.model_name:
        import uuid
        import time
        args.model_name = time.strftime("%Y%m%d-") + str(uuid.uuid4())[:8]

    # Set log + model file names
    args.log_file = os.path.join(args.model_dir, args.model_name + '.txt')
    args.model_file = os.path.join(args.model_dir, args.model_name + '.mdl')

    # Embeddings options
    if args.embedding_file:
        with open(args.embedding_file) as f:
            dim = len(f.readline().strip().split(' ')) - 1
        args.embedding_dim = dim
    elif not args.embedding_dim:
        raise RuntimeError('Either embedding_file or embedding_dim '
                           'needs to be specified.')

    if args.char_embedding_file:
        with open(args.char_embedding_file) as f:
            dim = len(f.readline().strip().split(' ')) - 1
        args.char_embedding_dim = dim
    elif not args.char_embedding_dim:
        raise RuntimeError('Either char_embedding_file or char_embedding_dim '
                           'needs to be specified.')

    return args


def train(args):
    return


def set_random_seed(seed):
    # set Python random seed
    random.seed(seed)

    # set NumPy random seed
    np.random.seed(seed)


# model v3:
# --gpu=0 --hops=2 --ptr-hops=2 --data-dir=../data/datasets --train-file=SQuAD-train-v1.1-processed-spacy.txt --dev-file=SQuAD-dev-v1.1-processed-spacy.txt --embed-dir=../data/embeddings --fine-tune=false --lambda-param=1 --gamma=3
# --gpu=0 --hops=3 --ptr-hops=2 --data-dir=../data/datasets --train-file=SQuAD-train-v1.1-processed-spacy.txt --dev-file=SQuAD-dev-v1.1-processed-spacy.txt --embed-dir=../data/embeddings --lambda-param=1 --gamma=3  --learning-rate=0.0001 --encoder-dropout=0.3 --fine-tune  --options-file ../../test_elmo/src/elmo-chainer/elmo_2x4096_512_2048cnn_2xhighway_options.json --weight-file ../../test_elmo/src/elmo-chainer/elmo_2x4096_512_2048cnn_2xhighway_weights.hdf5
def main():
    parser = argparse.ArgumentParser(
        'Reinforced Mnemonic Reader',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # Read parameters
    add_train_args(parser)
    args = parser.parse_args()
    set_defaults(args)

    set_random_seed(args.random_seed)

    train_data = DataUtils.load_data(args.train_file)
    dev_data = DataUtils.load_data(args.dev_file)

    # for Debug
    if DataUtils.IS_DEBUG:
        train_data = train_data[:128]
        dev_data = dev_data[:128]
    else:
        train_size = int(len(train_data) * args.train_ratio)

        print(train_size)

        train_data = train_data[:train_size]

        dev_size = int(len(dev_data) * args.dev_ratio)

        print(dev_size)

        dev_data = dev_data[:dev_size]

    all_data = train_data + dev_data

    args.pos_size = DataUtils.transform_pos_feature(all_data)
    args.ner_size = DataUtils.transform_ner_feature(all_data)
    args.qtype_size = 11

    # max_question_len = DataUtils.get_max_question_len(all_data)
    args.context_max_length = DataUtils.get_max_len(all_data, DataType.CONTEXT)
    max_question_len = DataUtils.get_max_len(all_data, DataType.QUESTION)

    DataUtils.MAX_DOC_LENGTH = args.context_max_length
    DataUtils.MAX_Q_LENGTH = max_question_len

    DataUtils.cal_mask(train_data, args.context_max_length, max_question_len)
    DataUtils.cal_mask(dev_data, args.context_max_length, max_question_len)

    ##
    # pretrain_embedding_file = os.path.join(args.embed_dir, "pretrain_embedding_v6_a_0.005_0.05")
    # pretrain_index_file = os.path.join(args.embed_dir, "pretrain_index_file_v6_0.005_0.05.txt")
    pretrain_embedding_file = os.path.join(args.embed_dir,
                                           "pretrain_embedding_v6_a_" + str(args.train_ratio) + "_" + str(
                                               args.dev_ratio))
    pretrain_index_file = os.path.join(args.embed_dir, "pretrain_index_file_v6_" + str(args.train_ratio) + "_" + str(
        args.dev_ratio) + ".txt")

    # args.w_embeddings = DataUtils.load_embedding(all_data, args.embedding_file, args.embedding_dim)
    args.w_embeddings = DataUtils.load_embedding(all_data, args.embedding_file, args.embedding_dim,
                                                 pretrained_embedding_file=pretrain_embedding_file,
                                                 pretrained_index_file=pretrain_index_file,
                                                 overwrite=False)

    # args.w_embeddings = object()
    # DataUtils.load_embedding(all_data, args.embedding_file, args.embedding_dim, args.w_embeddings)
    if DataUtils.IS_DEBUG:
        print("load_embedding : finished...")

    pretrain_char_embedding_file = os.path.join(args.embed_dir,
                                                "pretrain_char_embedding_v6_a_" + str(args.train_ratio) + "_" + str(
                                                    args.dev_ratio))
    pretrain_char_index_file = os.path.join(args.embed_dir,
                                            "pretrain_char_index_file_v6_a_" + str(args.train_ratio) + "_" + str(
                                                args.dev_ratio) + ".txt")

    args.char_embeddings = DataUtils.load_char_embedding(all_data, args.char_embedding_file, args.char_embedding_dim,
                                                         pretrained_embedding_file=pretrain_char_embedding_file,
                                                         pretrained_index_file=pretrain_char_index_file,
                                                         overwrite=False)

    args.vocab_size = len(DataUtils.word_dict)
    args.char_size = len(DataUtils.char_dict)

    print(args.vocab_size)

    if args.use_dict:
        # add dictionary
        args.dictionary = DataUtils.load_dictionary(args.dictionary_file, args.dict_embedding_file)

    if args.use_elmo:
        # add elmo online
        # initialize elmo batcher
        DataUtils.load_elmo_batcher(args.vocab_file)

        # add elmo embedding offline
        # DataUtils.load_elmo_embedding(args.context_elmo_embedding, args.question_elmo_embedding)

    train_data_input = chainer.datasets.TransformDataset(train_data, DataUtils.convert_item)
    # dev_data = chainer.datasets.TransformDataset(dev_data, DataUtils.convert_item_dev)

    # because of memory
    # args.batch_size = 32
    # args.batch_size = 16
    # args.batch_size = 4
    args.num_features = 4
    args.num_epochs = 100

    # cg
    args.dot_file = "cg_f__.dot"

    """test start"""
    """
    model = MReader_V6(args)

    if args.fine_tune:
        if args.gpu >= 0:
            chainer.cuda.get_device(args.gpu).use()
            model.to_gpu(args.gpu)
        f = open('result/model_t.pkl', 'rb')
        model = pickle.load(f)
        chainer.serializers.load_npz('result/best_model_0.005_0.05', model)
        if args.predict:
            with chainer.using_config('train', False):
                predictor = MReaderEvaluatorPred(
                    model, dev_data, device=args.gpu,
                    f1_key='validation/main/f1', em_key='validation/main/em', batch_size=args.batch_size,
                    dot_file='cg_n.dot'
                )
                predictor()
            return

    """
    """test end"""

    args.backup_fine_tune = False
    if args.fine_tune:
        args.backup_fine_tune = True
        args.fine_tune = False

    # model = MReader_V3(args)
    model = MReader_V6(args)

    if args.fine_tune:
        chainer.serializers.load_npz('result/best_model', model)
        # chainer.serializers.load_npz('result/snapshot_iter_547', model, path='updater/model:main/')

    if args.gpu >= 0:
        chainer.cuda.get_device(args.gpu).use()
        model.to_gpu(args.gpu)

    # optimizer = chainer.optimizers.Adam(alpha=args.learning_rate)
    optimizer = chainer.optimizers.Adam(alpha=args.reader_initial_learning_rate)
    optimizer.setup(model)

    train_iter = chainer.iterators.SerialIterator(train_data_input, args.batch_size)
    # validation_iter = chainer.iterators.SerialIterator(dev_data, args.batch_size, repeat=False, shuffle=False)

    updater = training.StandardUpdater(
        train_iter, optimizer, loss_func=model.get_loss_function(),
        device=args.gpu
    )

    monitor = "validation/main/f1" if args.fine_tune else "validation/main/em"

    earlystop_trigger = triggers.EarlyStoppingTrigger(monitor=monitor, patients=5, mode="max",
                                                      max_trigger=(args.num_epochs, 'epoch'))

    # trainer = training.Trainer(updater, (args.num_epochs, 'epoch'))
    trainer = training.Trainer(updater, earlystop_trigger)

    # test load trainer
    # chainer.serializers.load_npz('result/snapshot_iter_547', trainer)

    save_model_file = "best_model_rl_" + str(args.train_ratio) + "_" + str(
        args.dev_ratio) if args.fine_tune else "best_model_" + str(args.train_ratio) + "_" + str(args.dev_ratio)

    trainer.extend(
        # extensions.snapshot_object(model, save_model_file + "_{.updater.epoch}"),
        extensions.snapshot_object(model, save_model_file),
        trigger=chainer.training.triggers.MaxValueTrigger(monitor)
    )

    """
    trainer.extend(
        extensions.snapshot(),
        trigger=chainer.training.triggers.MaxValueTrigger(monitor)
    )
    """

    # computational graph 2nd way
    trainer.extend(extensions.dump_graph(root_name="main/loss", out_name="cg.dot"))

    trainer.extend(
        MReaderEvaluator(
            model, dev_data, device=args.gpu,
            f1_key='validation/main/f1', em_key='validation/main/em', batch_size=args.batch_size, dot_file='cg_n.dot'
        )
    )

    trainer.extend(
        extensions.LogReport()
    )

    trainer.extend(
        extensions.PrintReport(
            ['epoch', 'main/loss', 'main/mle_loss', 'main/rl_loss', 'validation/main/f1', 'validation/main/em',
             'elapsed_time']
        )
    )

    # trainer.extend(extensions.ProgressBar())

    print('start training')
    trainer.run()

    """test start"""
    """
    of = open('result/model_t.pkl', 'wb')
    pickle.dump(model, of)
    of.close()
    """
    """test end"""

    if args.backup_fine_tune:
        args.fine_tune = True
        model.args.fine_tune = True

    if args.fine_tune:
        chainer.serializers.load_npz('result/best_model_' + str(args.train_ratio) + "_" + str(args.dev_ratio), model)

        if args.gpu >= 0:
            chainer.cuda.get_device(args.gpu).use()
            model.to_gpu(args.gpu)

        """
        if args.predict:
            with chainer.using_config('train', False):
                predictor = MReaderEvaluatorPred(
                    model, dev_data, device=args.gpu,
                    f1_key='validation/main/f1', em_key='validation/main/em', batch_size=args.batch_size,
                    dot_file='cg_n.dot'
                )
                predictor()
            return
        """
        args.fine_tune = True
        model.args.fine_tune = True
        # optimizer = chainer.optimizers.Adam(alpha=args.learning_rate)
        optimizer_rl = chainer.optimizers.Adam(alpha=args.rl_initial_learning_rate)
        optimizer_rl.setup(model)

        train_iter_rl = chainer.iterators.SerialIterator(train_data_input, args.batch_size)
        # validation_iter = chainer.iterators.SerialIterator(dev_data, args.batch_size, repeat=False, shuffle=False)

        updater_rl = training.StandardUpdater(
            train_iter_rl, optimizer_rl, loss_func=model.get_loss_function(),
            device=args.gpu
        )

        monitor_rl = "validation/main/f1" if args.fine_tune else "validation/main/em"

        earlystop_trigger_rl = triggers.EarlyStoppingTrigger(monitor=monitor_rl, patients=10, mode="max",
                                                             max_trigger=(args.num_epochs, 'epoch'))

        trainer_rl = training.Trainer(updater_rl, earlystop_trigger_rl)

        save_model_file_rl = "best_model_rl_" + str(args.train_ratio) + "_" + str(
            args.dev_ratio) if args.fine_tune else "best_model_" + str(args.train_ratio) + "_" + str(args.dev_ratio)
        # "best_model_rl" if args.fine_tune else "best_model"

        trainer_rl.extend(
            # extensions.snapshot_object(model, save_model_file_rl + "_{.updater.epoch}"),
            extensions.snapshot_object(model, save_model_file_rl),
            trigger=chainer.training.triggers.MaxValueTrigger(monitor_rl)
        )

        # computational graph 2nd way
        trainer_rl.extend(extensions.dump_graph(root_name="main/loss", out_name="cg.dot"))

        trainer_rl.extend(
            MReaderEvaluator(
                model, dev_data, device=args.gpu,
                f1_key='validation/main/f1', em_key='validation/main/em', batch_size=args.batch_size,
                dot_file='cg_n.dot'
            )
        )

        trainer_rl.extend(
            extensions.LogReport()
        )
        trainer_rl.extend(
            extensions.PrintReport(
                ['epoch', 'main/loss', 'main/mle_loss', 'main/rl_loss', 'validation/main/f1', 'validation/main/em',
                 'elapsed_time']
            )
        )

        print("rl start running...")
        trainer_rl.run()

        if args.predict:
            saved_model_file = "result/best_model_rl_" + str(args.train_ratio) + "_" + str(
                args.dev_ratio) if args.fine_tune else "result/best_model_" + str(args.train_ratio) + "_" + str(
                args.dev_ratio)

            chainer.serializers.load_npz(saved_model_file, model)
            import time
            saved_result_file = "result_" + str(args.train_ratio) + "_" + str(args.dev_ratio) + "_" + str(time.time())
            if args.use_dict:
                saved_result_file += "_dict"

            with chainer.using_config('train', False):
                predictor = MReaderEvaluatorPred(
                    model, dev_data, device=args.gpu,
                    f1_key='validation/main/f1', em_key='validation/main/em', batch_size=args.batch_size,
                    dot_file='cg_n.dot', file_p=saved_result_file
                )
                predictor()

            return


if __name__ == '__main__':
    main()
