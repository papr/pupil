'''
(*)~---------------------------------------------------------------------------
Pupil - eye tracking platform
Copyright (C) 2012-2018 Pupil Labs

Distributed under the terms of the GNU
Lesser General Public License (LGPL v3.0).
See COPYING and COPYING.LESSER for license details.
---------------------------------------------------------------------------~(*)
'''
import os
import logging
from itertools import chain

from pyglui import ui
from pyglui.cygl import utils as cygl_utils

import background_helper as bh
from gaze_sections import _setup_fake_pool, serialization_format_version, colors
from gaze_sections.base_sections import Base_Section
from calibration_routines.finish_calibration import select_calibration_method
from file_methods import save_object

logger = logging.getLogger(__name__)


def calibrate_in_background(g_pool, reference_locations, pupil_positions):
    yield None, 'Calibrating...'
    method, calib_result = select_calibration_method(g_pool, pupil_positions,
                                                     reference_locations)
    if calib_result['subject'] != 'calibration.failed':
        mapper = {'name': calib_result['name'], 'args': calib_result['args']}
        yield mapper, 'Calibration successful'
    else:
        yield None, 'Calibration failed! '+calib_result['reason']


def median_pupil_datum_is_2d(pupil_positions):
    return '2d' in pupil_positions[len(pupil_positions)//2]['method']


class Calibration_Section(Base_Section):
    order = .3
    timeline_color = colors['cyan']

    def __init__(self, g_pool,
                 calibrated_mapper={},
                 reference_method='circle_marker',
                 calibration_method='3d',
                 *args, **kwargs):
        super().__init__(g_pool, *args, **kwargs)
        self.reference_method = reference_method
        self.calibration_method = calibration_method
        self.calibrated_mapper = calibrated_mapper
        self.status = 'Not yet calibrated'
        self.save_calibration()

    def get_init_dict(self):
        init_dict = super().get_init_dict()
        init_dict['reference_method'] = self.reference_method
        init_dict['calibration_method'] = self.calibration_method
        init_dict['calibrated_mapper'] = self.calibrated_mapper
        return init_dict

    def append_section_specific_menu(self):
        self.menu.append(ui.Selector('reference_method', self,
                                     label="Reference Method",
                                     labels=['Circle Marker', 'Natural Features'],
                                     selection=['circle_marker', 'natural_features']))
        self.menu.append(ui.Selector('calibration_method', self,
                                     label='Calibration Mode',
                                     selection=['2d', '3d']))
        self.menu.append(ui.Info_Text('This section is calibrated using reference markers found in a user set range "Calibration". Drag the trim marks in the timeline to set a range and apply it.'))

        self.append_set_from_trim_marks_button()

        self.menu.append(ui.Button('Calibrate', self.slice_data_and_start_calibration))
        self.menu.append(ui.Text_Input('status', self, label='Status',
                                       setter=lambda _: None))

    def slice_data_and_start_calibration(self):
        self.status = 'Starting calibration'
        try:
            reference_data = self.sliced_reference_data()
            pupil_data = self.sliced_pupil_data()
        except AssertionError as assertion:
            self.status = assertion.args[0]
            logger.error(self.status)
            return
        self.correct_3d_to_2d_mode_if_required(pupil_data)
        self.start_calibration(reference_data, pupil_data)

    def start_calibration(self, reference_data, pupil_data):
        if self.bg_task:
            self.bg_task.cancel()

        logger.info('Calibrating section {} in {} mode...'.format(self.label, self.calibration_method))

        bg_task_arguments = (self.setup_fake_pool(), reference_data, pupil_data)
        self.bg_task = bh.Task_Proxy(self.label, calibrate_in_background,
                                     args=bg_task_arguments)

    def sliced_pupil_data(self):
        calibration_slice = slice(*self.range)
        pupil_data = self.g_pool.pupil_positions_by_frame[calibration_slice]
        pupil_data = list(chain.from_iterable(pupil_data))
        assert pupil_data, 'Calibration failed, no pupil data'
        return pupil_data

    def sliced_reference_data(self):
        start, end = self.range
        ref_list = [r for r in self.complete_reference_data()
                    if start <= r['index'] <= end]
        assert ref_list, 'Calibration failed, no reference data'
        return ref_list

    def complete_reference_data(self):
        if self.reference_method == 'circle_marker':
            return self.g_pool.gaze_manager.circle_marker_positions
        elif self.reference_method == 'natural_features':
            return self.g_pool.gaze_manager.manual_ref_positions
        else:
            raise RuntimeError('Unknown reference method: '+self.reference_method)

    def correct_3d_to_2d_mode_if_required(self, pupil_data):
        if self.calibration_method == '3d' and median_pupil_datum_is_2d(pupil_data):
            logger.warning("Pupil data is 2d, setting calibration mode to 2d as well.")
            self.calibration_method = '2d'

    def handle_task_result(self, result):
        mapper, self.status = result
        self.calibrated_mapper = mapper or self.calibrated_mapper
        self.save_calibration()

    def on_task_completed(self):
        self.notify_all({'subject': 'gaze_section.calibrated',
                         'label': self.label})

    def serialized_calibration_path(self):
        file_name = self.label + '.plcalibration'
        return os.path.join(self.g_pool.rec_dir, 'offline_data', file_name)

    def save_calibration(self):
        target_path = self.serialized_calibration_path()
        self.calibrated_mapper['version'] = serialization_format_version
        save_object(self.calibration, target_path)

    def setup_fake_pool(self):
        return _setup_fake_pool(self.g_pool.capture.frame_size,
                                self.g_pool.capture.intrinsics,
                                self.calibration_method,
                                self.g_pool.rec_dir,
                                self.g_pool.min_calibration_confidence)

    def draw_range(self, pixel_to_time_factor, scale):
        super().draw_range(pixel_to_time_factor, scale)
        color = cygl_utils.RGBA(1., 1., 1., .5)
        reference_data = [(m['timestamp'], 0) for m in self.complete_reference_data()]

        if self.calibration_method == "natural_features":
            cygl_utils.draw_x(reference_data, height=12 * scale,
                              width=3 * pixel_to_time_factor / scale,
                              thickness=scale, color=color)
        else:
            cygl_utils.draw_bars(reference_data, height=12 * scale,
                                 thickness=scale, color=color)
