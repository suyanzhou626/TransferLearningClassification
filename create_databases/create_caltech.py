
from datetime import datetime
import os
import random
import sys
import threading
import glob

import numpy as np
import tensorflow as tf

tf.app.flags.DEFINE_integer('train_shards', 12,
                            'Number of shards in training TFRecord files.')
tf.app.flags.DEFINE_integer('test_shards', 4,
                            'Number of shards in test TFRecord files.')
tf.app.flags.DEFINE_integer('rest_shards', 4,
                            'Number of shards in rest TFRecord files.')
tf.app.flags.DEFINE_string('output_directory', './tfRecords-Caltech/',
                           'Output data directory')
tf.app.flags.DEFINE_integer('num_threads', 4,
                            'Number of threads to preprocess the images.')

FLAGS = tf.app.flags.FLAGS


def mapping_name_to_label(image_dir):
    a = dict()
    index = 0
    for name in sorted(glob.glob(image_dir + '/*')):
        a[name.split('/')[-1]] = index
        index += 1

    return a


def mapping_label_to_name(image_dir):
    a = []
    for name in sorted(glob.glob(image_dir + '/*')):
        a.append(name.split('/')[-1])

    return a


def generate_image_filenames_and_label(img_index, image_dir):
    """

    :param img_index: five ints for indicating images.
    :return:
    """

    assert len(img_index) == 5
    map_lable_to_name = mapping_label_to_name(image_dir)
    # print map_lable_to_name
    filenames = []
    lables = []
    for i in range(257):
        index_in_dir = i + 1
        index_str = '%03d'%index_in_dir

        for j in img_index:
            img_j_str = '%04d'%j
            filenames.append(image_dir + '/' + map_lable_to_name[i] + '/' + index_str + '_' + img_j_str + '.jpg')
            lables.append(i)

    assert len(filenames) == len(lables)
    index = range(len(filenames))
    np.random.shuffle(index)

    filenames_output = []
    lables_output = []
    for n in index:
        filenames_output.append(filenames[n])
        lables_output.append(lables[n])

    return filenames_output, lables_output


def all_files_beyond_80(image_dir):
    index = range(81, 900, 1)
    map_lable_to_name = mapping_label_to_name(image_dir)
    filenames = []
    lables = []
    for i in range(257):
        index_in_dir = i + 1
        index_str = '%03d'%index_in_dir

        for j in index:
            img_j_str = '%04d'%j
            filename = image_dir + '/' + map_lable_to_name[i] + '/' + index_str + '_' + img_j_str + '.jpg'
            if os.path.isfile(filename) is False:
                break
            filenames.append(filename)
            lables.append(i)

    return filenames, lables


def generate_lists(image_dir, subdir):
    """
    80 images per class in total and 256 classes. Generate a list of lists. Each list contains 256*5 images.
    :return: a list of lists. Each list contains 256*5 images.
    """

    # last 20 images are for test.
    index = range(1, 81, 1)
    # np.random.shuffle(index)

    list_of_filenames = []
    list_of_lables = []
    if subdir == 'train':
        # for training, 12 lists
        for i in range(12):
            index_for_one_list = index[i*5:(i+1)*5]
            filenames, lables = generate_image_filenames_and_label(index_for_one_list, image_dir)
            list_of_filenames.extend(filenames)
            list_of_lables.extend(lables)
    elif subdir == 'test':
        # for test, 4 lists
        for i in range(12, 16, 1):
            index_for_one_list = index[i*5:(i+1)*5]
            filenames, lables = generate_image_filenames_and_label(index_for_one_list, image_dir)
            list_of_filenames.extend(filenames)
            list_of_lables.extend(lables)
    elif subdir == 'rest':
        return all_files_beyond_80(image_dir)
    else:
        return None

    return list_of_filenames, list_of_lables


def _int64_feature(value):
    """Wrapper for inserting int64 features into Example proto."""
    if not isinstance(value, list):
        value = [value]
    return tf.train.Feature(int64_list=tf.train.Int64List(value=value))


def _float_feature(value):
    """Wrapper for inserting float features into Example proto."""
    if not isinstance(value, list):
        value = [value]
    return tf.train.Feature(float_list=tf.train.FloatList(value=value))


def _bytes_feature(value):
    """Wrapper for inserting bytes features into Example proto."""
    return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))


def _convert_to_example(image_buffer, trainid):
    """Build an Example proto for an example.
    Args:
      filename: string, path to an image file, e.g., '/path/to/example.JPG'
      image_buffer: string, JPEG encoding of RGB image
      label: integer, identifier for the ground truth for the network
      synset: string, unique WordNet ID specifying the label, e.g., 'n02323233'
      human: string, human-readable label, e.g., 'red fox, Vulpes vulpes'
      bbox: list of bounding boxes; each box is a list of integers
        specifying [xmin, ymin, xmax, ymax]. All boxes are assumed to belong to
        the same label as the image label.
      height: integer, image height in pixels
      width: integer, image width in pixels
    Returns:
      Example proto
    """

    example = tf.train.Example(features=tf.train.Features(feature={
        'image/class/trainid': _int64_feature(trainid),
        'image/encoded': _bytes_feature(image_buffer)}))
    return example


class ImageCoder(object):
    def __init__(self):
        # Create a single Session to run all image coding calls.
        self._sess = tf.Session()

        # Initializes function that decodes RGB JPEG data.
        self._decode_jpeg_data = tf.placeholder(dtype=tf.string)
        self._decode_jpeg = tf.image.decode_jpeg(self._decode_jpeg_data, channels=3)

    def decode_jpeg(self, image_data):
        image = self._sess.run(self._decode_jpeg,
                               feed_dict={self._decode_jpeg_data: image_data})
        assert len(image.shape) == 3
        assert image.shape[2] == 3
        return image


def _process_image(filename):
    """Process a single image file.
    Args:
      filename: string, path to an image file e.g., '/path/to/example.JPG'.
      coder: instance of ImageCoder to provide TensorFlow image coding utils.
    Returns:
      image_buffer: string, JPEG encoding of RGB image.
      height: integer, image height in pixels.
      width: integer, image width in pixels.
    """
    # Read the image file.
    with tf.gfile.FastGFile(filename, 'r') as f:
        image_data = f.read()

    return image_data


def _process_image_files_batch(coder, thread_index, ranges, name, filenames, labels, num_shards):
    """Processes and saves list of images as TFRecord in 1 thread.
    Args:
      coder: instance of ImageCoder to provide TensorFlow image coding utils.
      thread_index: integer, unique batch to run index is within [0, len(ranges)).
      ranges: list of pairs of integers specifying ranges of each batches to
        analyze in parallel.
      name: string, unique identifier specifying the data set
      filenames: list of strings; each string is a path to an image file
      labels: list of integer; each integer identifies the ground truth
      num_shards: integer number of shards for this data set.
    """
    # Each thread produces N shards where N = int(num_shards / num_threads).
    # For instance, if num_shards = 128, and the num_threads = 2, then the first
    # thread would produce shards [0, 64).
    num_threads = len(ranges)
    assert not num_shards % num_threads
    num_shards_per_batch = int(num_shards / num_threads)

    shard_ranges = np.linspace(ranges[thread_index][0],
                               ranges[thread_index][1],
                               num_shards_per_batch + 1).astype(int)
    num_files_in_thread = ranges[thread_index][1] - ranges[thread_index][0]

    counter = 0
    for s in range(num_shards_per_batch):
        # Generate a sharded version of the file name, e.g. 'train-00002-of-00010'
        shard = thread_index * num_shards_per_batch + s
        output_filename = '%s-%.3d-of-%.3d' % (name, shard, num_shards)
        output_file = os.path.join(FLAGS.output_directory, output_filename)
        writer = tf.python_io.TFRecordWriter(output_file)

        shard_counter = 0
        files_in_shard = np.arange(shard_ranges[s], shard_ranges[s + 1], dtype=int)
        for i in files_in_shard:
            filename = filenames[i]
            label = labels[i]

            image_buffer = _process_image(filename)

            example = _convert_to_example(image_buffer, label)
            writer.write(example.SerializeToString())
            shard_counter += 1
            counter += 1

            if not counter % 1000:
                print('%s [thread %d]: Processed %d of %d images in thread batch.' %
                      (datetime.now(), thread_index, counter, num_files_in_thread))
                sys.stdout.flush()

        writer.close()
        print('%s [thread %d]: Wrote %d images to %s' %
              (datetime.now(), thread_index, shard_counter, output_file))
        sys.stdout.flush()
        shard_counter = 0
    print('%s [thread %d]: Wrote %d images to %d shards.' %
          (datetime.now(), thread_index, counter, num_files_in_thread))
    sys.stdout.flush()


def _process_image_files(name, filenames, labels, num_shards):
    """Process and save list of images as TFRecord of Example protos.
    Args:
      name: string, unique identifier specifying the data set
      filenames: list of strings; each string is a path to an image file
      labels: list of integer; each integer identifies the ground truth
      num_shards: integer number of shards for this data set.
    """
    assert len(filenames) == len(labels)

    # Break all images into batches with a [ranges[i][0], ranges[i][1]].
    spacing = np.linspace(0, len(filenames), FLAGS.num_threads + 1).astype(np.int)
    ranges = []
    for i in range(len(spacing) - 1):
        ranges.append([spacing[i], spacing[i + 1]])

    # Launch a thread for each batch.
    print('Launching %d threads for spacings: %s' % (FLAGS.num_threads, ranges))
    sys.stdout.flush()

    # Create a mechanism for monitoring when all threads are finished.
    coord = tf.train.Coordinator()

    # Create a generic TensorFlow-based utility for converting all image codings.
    coder = ImageCoder()

    threads = []
    for thread_index in range(len(ranges)):
        args = (coder, thread_index, ranges, name, filenames, labels, num_shards)
        t = threading.Thread(target=_process_image_files_batch, args=args)
        t.start()
        threads.append(t)

    # Wait for all the threads to terminate.
    coord.join(threads)
    print('%s: Finished writing all %d images in data set.' %
          (datetime.now(), len(filenames)))
    sys.stdout.flush()


def _process_dataset(name, directory, num_shards):
    """Process a complete data set and save it as a TFRecord.
    Args:
      name: string, unique identifier specifying the data set.
      directory: string, root path to the data set.
      num_shards: integer number of shards for this data set.
      synset_to_human: dict of synset to human labels, e.g.,
        'n02119022' --> 'red fox, Vulpes vulpes'
      image_to_bboxes: dictionary mapping image file names to a list of
        bounding boxes. This list contains 0+ bounding boxes.
    """
    filenames, labels = generate_lists(directory, name)
    _process_image_files(name, filenames, labels, num_shards)


def main(unused_argv):
    assert not FLAGS.train_shards % FLAGS.num_threads, (
        'Please make the FLAGS.num_threads commensurate with FLAGS.train_shards')
    assert not FLAGS.test_shards % FLAGS.num_threads, (
        'Please make the FLAGS.num_threads commensurate with '
        'FLAGS.validation_shards')

    if os.path.exists(FLAGS.output_directory) is not True:
        os.mkdir(FLAGS.output_directory)

    # Run it!
    # _process_dataset('train', '/home/jacques/workspace/database/Caltech256/256_ObjectCategories', FLAGS.train_shards)
    # _process_dataset('test', '/home/jacques/workspace/database/Caltech256/256_ObjectCategories', FLAGS.test_shards)
    _process_dataset('rest', '/home/jacques/workspace/database/Caltech256/256_ObjectCategories', FLAGS.rest_shards)


if __name__ == '__main__':
    tf.app.run()