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
import os
from time import time
from itertools import cycle, chain
from collections import namedtuple

from pyglui import ui
from pyglui.cygl import utils as cygl_utils

import background_helper as bh
from calibration_routines.finish_calibration import select_calibration_method
from calibration_routines import gaze_mapping_plugins
from file_methods import load_object, save_object

logger = logging.getLogger(__name__)
gaze_mapping_plugins_by_name = {p.__name__: p for p in gaze_mapping_plugins}
Task_Result = namedtuple('Task_Result', ['topic', 'status', 'value'])

CALIBRATION_FILE_VERSION = 1
CREATE_CALIBRATION = 'Create calibration'
IMPORT_CALIBRATION = 'Import calibration'
TEST_CALIBRATION = 'Test calibration'

colors = cycle(((0.66015625, 0.859375, 0.4609375, 0.8),
                (0.99609375, 0.84375, 0.3984375, 0.8),
                (0.46875, 0.859375, 0.90625, 0.8),
                (0.984375, 0.59375, 0.40234375, 0.8),
                (0.66796875, 0.61328125, 0.9453125, 0.8),
                (0.99609375, 0.37890625, 0.53125, 0.8)))


class Empty(object):
        pass


def setup_fake_pool(frame_size, intrinsics, detection_mode, rec_dir, min_calibration_confidence):
    cap = Empty()
    cap.frame_size = frame_size
    cap.intrinsics = intrinsics
    pool = Empty()
    pool.capture = cap
    pool.get_timestamp = time
    pool.detection_mapping_mode = detection_mode
    pool.min_calibration_confidence = min_calibration_confidence
    pool.rec_dir = rec_dir
    pool.app = 'player'
    return pool


def calibrate_in_background(g_pool, section_name, ref_pos, calib_pos, map_pos, x_offset, y_offset):
    yield Task_Result('calibration', 'Calibrating...', None)
    method, calib_result = select_calibration_method(g_pool, calib_pos, ref_pos)
    if calib_result['subject'] != 'calibration.failed':
        mapper = {'name': calib_result['name'], 'args': calib_result['args']}
        yield Task_Result('calibration', 'Calibration successful', mapper)
        for map_result in map_in_background(g_pool, section_name, mapper,
                                            map_pos, x_offset, y_offset):
            yield map_result
    else:
        yield Task_Result('calibration', 'Calibration failed!', None)


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


def make_section_label(existing_labels=()):
    counter = 1
    while True:
        label = 'Unnamed section {}'.format(counter)
        if label in existing_labels:
            counter += 1
        else:
            return label


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
        self.update_ui()

    def update_ui(self):
        del self.menu[:]

        self.menu.append(ui.Text_Input('label', self.cache, label='Label',
                                       setter=self.validate_label))

        self.menu.append(ui.Selector('type', self.cache,
                                     label="Section Type",
                                     selection=self.types,
                                     setter=self.set_type))

        if self['type'] == CREATE_CALIBRATION:
            self.append_create_calib_ui()
        elif self['type'] == IMPORT_CALIBRATION:
            self.append_import_calib_ui()
        elif self['type'] == TEST_CALIBRATION:
            self.append_test_calib_ui()

        # manual gaze correction menu
        offset_menu = ui.Growing_Menu('Manual Correction')
        offset_menu.append(ui.Info_Text('The manual correction feature allows you to apply' +
                                        ' a fixed offset to your gaze data.'))
        offset_menu.append(ui.Slider('x_offset', self.cache, min=-.5, step=0.01, max=.5))
        offset_menu.append(ui.Slider('y_offset', self.cache, min=-.5, step=0.01, max=.5))
        offset_menu.collapsed = True
        self.menu.append(offset_menu)

        self.menu.append(ui.Button('Remove section', self.remove))

    def append_create_calib_ui(self):
        self.menu.append(ui.Selector('calibration_method', self.cache,
                                     label="Calibration Method",
                                     labels=['Circle Marker', 'Natural Features'],
                                     selection=['circle_marker', 'natural_features']))
        self.menu.append(ui.Selector('mapping_method', self.cache,
                                     label='Calibration Mode',
                                     selection=['2d', '3d']))
        self.menu.append(ui.Info_Text('This section is calibrated using reference markers found in a user set range "Calibration". The calibration is used to map pupil to gaze positions within a user set range "Mapping". Drag trim marks in the timeline to set a range and apply it.'))

        for range_key in ('calibration_range', 'mapping_range'):
            button = ui.Button('Set from trim marks', None)
            self.set_trim_fn(button, self.cache, range_key)
            button.function(format_only=True)  # set initial label
            self.menu.append(button)

        self.menu.append(ui.Button('Recalibrate', self.calibrate))
        self.menu.append(ui.Text_Input('status', self.cache,
                                       label='Status',
                                       setter=lambda _: None))

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

    def deinit_ui(self):
        self.parent.menu.remove(self.menu)
        self.menu = None

    def cleanup(self):
        pass

    @property
    def menu_title(self):
        return 'Section Settings - {}'.format(self.cache['label'])

    def validate_label(self, input_obj):
        if input_obj == self.cache['label']:
            return
        elif input_obj in (s['label'] for s in self.parent.sections):
            logger.warning('Duplicated section label')
        else:
            self.rename_saved_calibration(new_label=input_obj)
            self.cache['label'] = input_obj
            self.menu.label = self.menu_title

    def set_type(self, type_):
        if type_ == self['type']:
            return
        self['type'] = type_
        self.update_ui()

    def set_trim_fn(self, button, sec, key):
        def trim(format_only=False):
            if format_only:
                left_idx, right_idx = sec[key]
            else:
                right_idx = self.parent.g_pool.seek_control.trim_right
                left_idx = self.parent.g_pool.seek_control.trim_left
                sec[key] = left_idx, right_idx

            time_fmt = key.replace('_', ' ').split(' ')[0].title() + ': '
            min_ts = self.parent.g_pool.timestamps[0]
            for idx in (left_idx, right_idx):
                ts = self.parent.g_pool.timestamps[idx] - min_ts
                minutes = ts // 60
                seconds = ts - (minutes * 60.)
                time_fmt += ' {:02.0f}:{:02.0f} -'.format(abs(minutes), seconds)
            button.outer_label = time_fmt[:-2]  # remove final ' -'
        button.function = trim

    def remove(self):
        self.deinit_ui()
        try:
            os.remove(self.calibration_path())
        except FileNotFoundError:
            pass  # no successful calibration saved yet
        # TODO: catch unknown exception on Windows if file is in use
        self.parent.sections.remove(self)
        self.parent.correlate_and_publish()
        self.cleanup()

    def calibrate(self):
        if self.bg_task:
            self.bg_task.cancel()

        self.cache['status'] = 'Starting calibration'  # This will be overwritten on success
        self.gaze_positions = []  # reset interim buffer for given section

        calib_list = list(chain.from_iterable(self.parent.g_pool.pupil_positions_by_frame[slice(*self.cache['calibration_range'])]))
        map_list = list(chain.from_iterable(self.parent.g_pool.pupil_positions_by_frame[slice(*self.cache['mapping_range'])]))

        if self.cache['calibration_method'] == 'circle_marker':
            ref_list = self.parent.circle_marker_positions
        elif self.cache['calibration_method'] == 'natural_features':
            ref_list = self.parent.manual_ref_positions

        start = self.cache['calibration_range'][0]
        end = self.cache['calibration_range'][1]
        ref_list = [r for r in ref_list if start <= r['index'] <= end]

        if not calib_list:
            logger.error('No pupil data to calibrate section "{}"'.format(self.cache['label']))
            self.cache['status'] = 'Calibration failed, no pupil data'
            return

        if not ref_list:
            logger.error('No referece marker data to calibrate section "{}"'.format(self.cache['label']))
            self.cache['status'] = 'Calibration failed, no reference data'
            return

        if self.cache["mapping_method"] == '3d' and '2d' in calib_list[len(calib_list)//2]['method']:
            # select median pupil datum from calibration list and use its detection method as mapping method
            logger.warning("Pupil data is 2d, calibration and mapping mode forced to 2d.")
            self.cache["mapping_method"] = '2d'

        fake = setup_fake_pool(self.parent.g_pool.capture.frame_size,
                               self.parent.g_pool.capture.intrinsics,
                               self.cache["mapping_method"],
                               self.parent.g_pool.rec_dir,
                               self.parent.g_pool.min_calibration_confidence)
        generator_args = (fake, self.cache['label'], ref_list, calib_list,
                          map_list, self.cache['x_offset'], self.cache['y_offset'])
        logger.info('Calibrating section {} in {} mode...'.format(self.cache['label'], self.cache["mapping_method"]))
        self.bg_task = bh.Task_Proxy(self.cache['label'], calibrate_in_background, args=generator_args)

    def recent_events(self):
        if self.bg_task:
            recent = [d for d in self.bg_task.fetch()]
            for result in recent:
                self.handle_task_result(result)
            if self.bg_task.completed:
                self.parent.correlate_and_publish()
                self.bg_task = None

    def handle_task_result(self, result):
        self['status'] = result.status
        if result.topic == 'calibration' and result.value:
            self.calibration = result.value
            self.save_calibration()
        elif result.topic == 'mapping':
            self.gaze_positions.extend(result.value)

    def calibration_path(self, label=None):
        label = label or self.cache['label']
        file_name = label + '.plcalibration'
        rec_dir = self.parent.g_pool.rec_dir
        return os.path.join(rec_dir, 'offline_data', file_name)

    def save_calibration(self):
        target_path = self.calibration_path()
        self.calibration['version'] = CALIBRATION_FILE_VERSION
        save_object(self.calibration, target_path)

    def rename_saved_calibration(self, new_label):
        old_path = self.calibration_path()
        new_path = self.calibration_path(label=new_label)
        try:
            os.rename(old_path, new_path)
        except FileNotFoundError:
            pass  # no successful calibration saved yet

    def __getitem__(self, key):
        return self.cache[key]

    def __setitem__(self, key, value):
        self.cache[key] = value

    def draw(self, pixel_to_time_fac, scale):
        cal_slc = slice(*self.cache['calibration_range'])
        map_slc = slice(*self.cache['mapping_range'])
        cal_ts = self.parent.g_pool.timestamps[cal_slc]
        map_ts = self.parent.g_pool.timestamps[map_slc]

        color = cygl_utils.RGBA(*self.cache['color'][:3], 1.)
        if len(cal_ts):
            cygl_utils.draw_rounded_rect((cal_ts[0], -4 * scale),
                                         (cal_ts[-1] - cal_ts[0], 8 * scale),
                                         corner_radius=0,
                                         color=color,
                                         sharpness=1.)
        if len(map_ts):
            cygl_utils.draw_rounded_rect((map_ts[0], -scale),
                                         (map_ts[-1] - map_ts[0], 2 * scale),
                                         corner_radius=0,
                                         color=color,
                                         sharpness=1.)

        color = cygl_utils.RGBA(1., 1., 1., .5)
        if self.cache['calibration_method'] == "natural_features":
            cygl_utils.draw_x([(m['timestamp'], 0) for m in self.parent.manual_ref_positions],
                              height=12 * scale,
                              width=3 * pixel_to_time_fac / scale,
                              thickness=scale,
                              color=color)
        else:
            cygl_utils.draw_bars([(m['timestamp'], 0) for m in self.parent.circle_marker_positions],
                                 height=12 * scale,
                                 thickness=scale,
                                 color=color)
