'''
(*)~---------------------------------------------------------------------------
Pupil - eye tracking platform
Copyright (C) 2012-2018 Pupil Labs

Distributed under the terms of the GNU
Lesser General Public License (LGPL v3.0).
See COPYING and COPYING.LESSER for license details.
---------------------------------------------------------------------------~(*)
'''
import logging
from time import time
from collections import OrderedDict

from plugin import Plugin_List
logger = logging.getLogger(__name__)


class _Empty(object):
        pass


def _setup_fake_pool(frame_size, intrinsics, detection_mode, rec_dir,
                     min_calibration_confidence):
    cap = _Empty()
    cap.frame_size = frame_size
    cap.intrinsics = intrinsics
    pool = _Empty()
    pool.capture = cap
    pool.get_timestamp = time
    pool.detection_mapping_mode = detection_mode
    pool.min_calibration_confidence = min_calibration_confidence
    pool.rec_dir = rec_dir
    pool.app = 'player'
    return pool


serialization_format_version = 1
colors = {'green': (0.66015625, 0.859375, 0.4609375, 0.8),
          'yellow': (0.99609375, 0.84375, 0.3984375, 0.8),
          'cyan': (0.46875, 0.859375, 0.90625, 0.8),
          'orange': (0.984375, 0.59375, 0.40234375, 0.8),
          'purple': (0.66796875, 0.61328125, 0.9453125, 0.8),
          'red': (0.99609375, 0.37890625, 0.53125, 0.8)}

from gaze_sections.calibration_section import Calibration_Section
from gaze_sections.mapping_section import Mapping_Section
from gaze_sections.validation_section import Validation_Section


class Section_List(Plugin_List):
    def __init__(self, g_pool, plugin_initializers):
        self._plugins = []
        self.g_pool = g_pool
        classes = [Calibration_Section, Mapping_Section, Validation_Section]
        plugin_by_name = OrderedDict(((cls.__name__, cls) for cls in classes))

        # now add plugins to plugin list.
        for initializer in plugin_initializers:
            name, args = initializer
            logger.debug("Loading section: {} with settings {}".format(name, args))
            try:
                plugin_by_name[name]
            except KeyError:
                logger.debug("Plugin '{}' failed to load. Not available for import." .format(name))
            else:
                self.add(plugin_by_name[name], args)
