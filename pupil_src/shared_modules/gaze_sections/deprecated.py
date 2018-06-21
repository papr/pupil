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
from collections import namedtuple

from pyglui import ui

from calibration_routines import gaze_mapping_plugins


logger = logging.getLogger(__name__)
gaze_mapping_plugins_by_name = {p.__name__: p for p in gaze_mapping_plugins}
Task_Result = namedtuple('Task_Result', ['topic', 'status', 'value'])

CALIBRATION_FILE_VERSION = 1
CREATE_CALIBRATION = 'Create calibration'
IMPORT_CALIBRATION = 'Import calibration'
TEST_CALIBRATION = 'Test calibration'

colors = {'green': (0.66015625, 0.859375, 0.4609375, 0.8),
          'yellow': (0.99609375, 0.84375, 0.3984375, 0.8),
          'cyan': (0.46875, 0.859375, 0.90625, 0.8),
          'orange': (0.984375, 0.59375, 0.40234375, 0.8),
          'purple': (0.66796875, 0.61328125, 0.9453125, 0.8),
          'red': (0.99609375, 0.37890625, 0.53125, 0.8)}


def map_in_background(g_pool, section_name, mapper, map_list, x_offset, y_offset):
    gaze_mapper_cls = gaze_mapping_plugins_by_name[mapper['name']]
    gaze_mapper = gaze_mapper_cls(g_pool, **mapper['args'])
    for idx, datum in enumerate(map_list):
        mapped_gaze = gaze_mapper.on_pupil_datum(datum)

        # apply manual correction
        for gp in mapped_gaze:
            # gp['norm_pos'] is a tuple by default
            gp_norm_pos = list(gp['norm_pos'])
            gp_norm_pos[1] += y_offset
            gp_norm_pos[0] += x_offset
            gp['norm_pos'] = gp_norm_pos
            gp['section'] = section_name

        if mapped_gaze:
            progress = (100 * (idx+1)/len(map_list))
            progress = "Mapping..{}%".format(int(progress))
            yield Task_Result('mapping', progress, mapped_gaze)
    progress = "Mapping complete."
    yield Task_Result('mapping', progress, [])


def construct_cache(label, calib_range, map_range):
        return {'label': label,
                'type': CREATE_CALIBRATION,
                'calibration': None,
                'calibration_range': calib_range,
                'mapping_range': map_range,
                'mapping_method': '3d',
                'calibration_method': "circle_marker",
                'status': 'Not mapped',
                'color': next(colors),
                'vis_mapping_error': True,
                'outlier_threshold': 5.,
                'x_offset': 0.,
                'y_offset': 0.}


class Section(object):
    types = [CREATE_CALIBRATION, IMPORT_CALIBRATION, TEST_CALIBRATION]

    def __init__(self, parent, cache=None, label=None, calib_range=None, map_range=None):
        self.parent = parent
        self.cache = cache or construct_cache(label, calib_range, map_range)
        self.bg_task = None
        self.error_lines = None
        self.calibration = None
        self.accuracy = 'Not available'
        self.precision = 'Not available'
        self.gaze_positions = []

    def init_ui(self):
        self.menu = ui.Growing_Menu(self.menu_title)
        self.parent.menu.append(self.menu)

        # manual gaze correction menu
        offset_menu = ui.Growing_Menu('Manual Correction')
        offset_menu.append(ui.Info_Text('The manual correction feature allows you to apply' +
                                        ' a fixed offset to your gaze data.'))
        offset_menu.append(ui.Slider('x_offset', self.cache, min=-.5, step=0.01, max=.5))
        offset_menu.append(ui.Slider('y_offset', self.cache, min=-.5, step=0.01, max=.5))
        offset_menu.collapsed = True
        self.menu.append(offset_menu)

        self.menu.append(ui.Button('Remove section', self.remove))

    def append_import_calib_ui(self):
        self.menu.append(ui.Info_Text(IMPORT_CALIBRATION.upper()))

    def append_test_calib_ui(self):
        self.menu.append(ui.Text_Input('outlier_threshold', self.sec,
                                          label='Outlier Threshold [degrees]'))

        self.menu.append(ui.Switch('vis_mapping_error', self.sec,
                                   label='Visualize mapping error'))
        self.menu.append(ui.Text_Input('accuracy', self,
                                       label='Angular Accuracy',
                                       setter=lambda _: _))
        self.menu.append(ui.Text_Input('precision', self,
                                       label='Angular Precision',
                                       setter=lambda _: _))

    def remove(self):
        self.deinit_ui()
        self.parent.correlate_and_publish()
        self.cleanup()
