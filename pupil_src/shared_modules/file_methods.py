'''
(*)~---------------------------------------------------------------------------
Pupil - eye tracking platform
Copyright (C) 2012-2017  Pupil Labs

Distributed under the terms of the GNU
Lesser General Public License (LGPL v3.0).
See COPYING and COPYING.LESSER for license details.
---------------------------------------------------------------------------~(*)
'''

try:
    import cPickle as pickle
except ImportError:
    import pickle

UnpicklingError = pickle.UnpicklingError
from collections import namedtuple, Mapping
import msgpack
import os
import traceback as tb
import logging
logger = logging.getLogger(__name__)


class Persistent_Dict(dict):
    """a dict class that uses pickle to save inself to file"""
    def __init__(self, file_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.file_path = os.path.expanduser(file_path)
        try:
            self.update(**load_object(self.file_path))
        except IOError:
            logger.debug("Session settings file '{}' not found. Will make new one on exit.".format(self.file_path))
        except:  # KeyError, EOFError
            logger.warning("Session settings file '{}'could not be read. Will overwrite on exit.".format(self.file_path))
            logger.debug(tb.format_exc())

    def save(self):
        d = {}
        d.update(self)
        try:
            save_object(d, self.file_path)
        except IOError:
            logger.warning("Could not save session settings to '{}'".format(self.file_path))

    def close(self):
        self.save()


def load_legacy_object(file_path):
    file_path = os.path.expanduser(file_path)
    with open(file_path, 'rb') as fh:
        data = pickle.load(fh, encoding='bytes')
    return data


def save_legacy_object(object_, file_path):
    file_path = os.path.expanduser(file_path)
    with open(file_path, 'wb') as fh:
        pickle.dump(object_, fh, -1)


_Immutable_Dict_class_cache = {}


def _create_Immutable_Dict_class(field_names):
    class Immutable_Dict(namedtuple('Immutable_Dict', field_names)):
        def __getitem__(self, key):
            return getattr(self, key) if isinstance(key, str) else super().__getitem__(key)

        def __repr__(self):
            return self._asdict_strict().__repr__()

        def _asdict_strict(self):
            return dict(zip(self._fields, self))

        def keys(self):
            return self._fields

        def get(self, key, default=None):
            return self.__getitem__(key) if key in self._fields else default

        def extend_copy(self, **extensions):
            '''
            Does not allow for duplicate of existing keys!
            Create new immutable dict instance but with extended list of fieldnames
            '''
            return create_Immutable_Dict(zip(self._fields + tuple(extensions.keys()),
                                             self + tuple(extensions.values())))

        def update_copy(self, **updates):
            copy = list(self)
            for key in updates.keys():
                copy[self._fields.index(key)] = updates[key]
            return type(self)(*copy)

    return Immutable_Dict


def create_Immutable_Dict(obj_pairs):
    field_names, vals = zip(*obj_pairs) if obj_pairs else ((), ())
    field_names = tuple(field_names)
    try:
        if field_names in _Immutable_Dict_class_cache:
            Immutable_Dict = _Immutable_Dict_class_cache[field_names]
        else:
            Immutable_Dict = _create_Immutable_Dict_class(field_names)
            _Immutable_Dict_class_cache[field_names] = Immutable_Dict
        return Immutable_Dict(*vals)
    except ValueError:
        # Fallback to normal dictionaries for invalid namedtuple fieldnames
        # e.g. fieldnames including spaces as generated by pylgui
        return dict(obj_pairs)


def _serialize_Immutable_Dict(obj):
    if isinstance(obj, tuple) and hasattr(obj, '_asdict_strict'):
        return obj._asdict_strict()
    elif isinstance(obj, tuple):
        return list(obj)
    elif isinstance(obj, float):
        # obj did not pass msgpack.PyFloat_CheckExact
        # therefore it is a float-subclass (e.g. np.float64)
        return float(obj)
    return obj


def load_object(file_path):
    file_path = os.path.expanduser(file_path)
    with open(file_path, 'rb') as fh:
        try:
            data = msgpack.unpack(fh, encoding='utf-8', use_list=False,
                                  object_pairs_hook=create_Immutable_Dict)
        except Exception as e:
            logger.info('{} has a deprecated format. It will be upgraded automatically.'.format(os.path.split(file_path)[1]))
            data = load_legacy_object(file_path)
    return data


def save_object(object_, file_path):
    file_path = os.path.expanduser(file_path)
    with open(file_path, 'wb') as fh:
        msgpack.pack(object_, fh, use_bin_type=True, strict_types=True,
                     default=_serialize_Immutable_Dict)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    # settings = Persistent_Dict("~/Desktop/test")
    # settings['f'] = "this is a test"
    # settings['list'] = ["list 1","list2"]
    # settings.close()

    # save_object("string",'test')
    # print load_object('test')
    # settings = Persistent_Dict('~/Desktop/pupil_settings/user_settings_eye')
    # print settings['roi']


    # example. Write out pupil data into csv file.
    from time import time
    t = time()
    l = load_object('/Users/mkassner/Downloads/data/pupil_data')
    print(l['notifications'])
    print(t-time())
    # t = time()
    # save_object(l,'/Users/mkassner/Downloads/data/pupil_data2')
    # print(t-time())
    import csv
    with open(os.path.join('/Users/mkassner/Pupil/pupil_code/pupil_src/capture/pupil_postions.csv'), 'w') as csvfile:
        csv_writer = csv.writer(csvfile, delimiter=',')
        csv_writer.writerow(('timestamp',
                             'id',
                             'confidence',
                             'norm_pos_x',
                             'norm_pos_y',
                             'diameter',
                             'method',
                             'ellipse_center_x',
                             'ellipse_center_y',
                             'ellipse_axis_a',
                             'ellipse_axis_b',
                             'ellipse_angle'))
        for p in l['pupil_positions']:
            data_2d = [str(p['timestamp']),  # use str to be consitant with csv lib.
                       p['id'],
                       p['confidence'],
                       p['norm_pos'][0],
                       p['norm_pos'][1],
                       p['diameter'],
                       p['method']]
            try:
                ellipse_data = [p['ellipse']['center'][0],
                                p['ellipse']['center'][1],
                                p['ellipse']['axes'][0],
                                p['ellipse']['axes'][1],
                                p['ellipse']['angle']]
            except KeyError:
                ellipse_data = [None]*5

            row = data_2d + ellipse_data
            csv_writer.writerow(row)

