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
from copy import deepcopy
from itertools import chain

import numpy as np
import OpenGL.GL as gl
from pyglui import ui
from pyglui.cygl import utils as cygl_utils
from pyglui.pyfontstash import fontstash

import gl_utils
import zmq_tools
from accuracy_visualizer import Accuracy_Visualizer
from file_methods import load_object, save_object
from glfw import *
from methods import normalize
from player_methods import correlate_data
from plugin import Producer_Plugin_Base
from gaze_sections import Section, make_section_label

logger = logging.getLogger(__name__)


class Gaze_Producer_Base(Producer_Plugin_Base):
    uniqueness = 'by_base_class'
    order = .02
    icon_chr = chr(0xec14)
    icon_font = 'pupil_icons'

    def init_ui(self):
        self.add_menu()

        gaze_producer_plugins = [p for p in self.g_pool.plugin_by_name.values() if issubclass(p, Gaze_Producer_Base)]
        gaze_producer_plugins.sort(key=lambda p: p.__name__)

        self.menu_icon.order = 0.3

        def open_plugin(p):
            self.notify_all({'subject': 'start_plugin', 'name': p.__name__})

        # We add the capture selection menu
        self.menu.append(ui.Selector(
                                'gaze_producer',
                                setter=open_plugin,
                                getter=lambda: self.__class__,
                                selection=gaze_producer_plugins,
                                labels=[p.__name__.replace('_', ' ') for p in gaze_producer_plugins],
                                label='Gaze Producers'
                            ))

    def deinit_ui(self):
        self.remove_menu()

    def recent_events(self, events):
        if 'frame' in events:
            frm_idx = events['frame'].index
            events['gaze_positions'] = self.g_pool.gaze_positions_by_frame[frm_idx]


class Gaze_From_Recording(Gaze_Producer_Base):
    def __init__(self, g_pool):
        super().__init__(g_pool)
        self.result_dir = os.path.join(g_pool.rec_dir, 'offline_data')
        os.makedirs(self.result_dir, exist_ok=True)
        try:
            session_data = load_object(os.path.join(self.result_dir, 'manual_gaze_correction'))
        except OSError:
            session_data = {'dx': 0., 'dy': 0.}
        self.x_offset = session_data['dx']
        self.y_offset = session_data['dy']
        self.load_data_with_offset()

    def load_data_with_offset(self):
        self.g_pool.gaze_positions = deepcopy(self.g_pool.pupil_data['gaze_positions'])
        for gp in self.g_pool.gaze_positions:
            gp['norm_pos'][0] += self.x_offset
            gp['norm_pos'][1] += self.y_offset
        self.g_pool.gaze_positions_by_frame = correlate_data(self.g_pool.gaze_positions, self.g_pool.timestamps)
        self.notify_all({'subject': 'gaze_positions_changed'})
        logger.debug('gaze positions changed')

    def _set_offset_x(self, offset_x):
        self.x_offset = offset_x
        self.notify_all({'subject': 'manual_gaze_correction.offset_changed', 'delay': 1.})

    def _set_offset_y(self, offset_y):
        self.y_offset = offset_y
        self.notify_all({'subject': 'manual_gaze_correction.offset_changed', 'delay': 1.})

    def on_notify(self, notification):
        if notification['subject'] == 'manual_gaze_correction.offset_changed':
            self.load_data_with_offset()

    def init_ui(self):
        super().init_ui()
        self.menu.label = "Gaze Data  From Recording"
        self.menu.append(ui.Info_Text('Currently, gaze positions are loaded from the recording.'))
        offset_menu = ui.Growing_Menu('Manual Correction')
        offset_menu.append(ui.Info_Text('The manual correction feature allows you to apply' +
                                        ' a fixed offset to your gaze data.'))
        offset_menu.append(ui.Slider('x_offset', self, min=-.5, step=0.01,
                                     max=.5, setter=self._set_offset_x))
        offset_menu.append(ui.Slider('y_offset', self, min=-.5, step=0.01,
                                     max=.5, setter=self._set_offset_y))
        offset_menu.collapsed = True
        self.menu.append(offset_menu)

    def deinit_ui(self):
        super().deinit_ui()

    def cleanup(self):
        session_data = {'dx': self.x_offset, 'dy': self.y_offset, 'version': 0}
        save_object(session_data, os.path.join(self.result_dir, 'manual_gaze_correction'))


class Offline_Calibration(Gaze_Producer_Base):
    session_data_version = 10
    calibration_version = 1

    def __init__(self, g_pool, manual_ref_edit_mode=False):
        super().__init__(g_pool)
        self.timeline_line_height = 16
        self.manual_ref_edit_mode = manual_ref_edit_mode
        self.menu = None
        self.process_pipe = None

        self.cache_path = os.path.join(g_pool.rec_dir, 'offline_data')
        os.makedirs(self.cache_path, exist_ok=True)
        try:
            session_data = load_object(os.path.join(self.cache_path, 'offline_calibration_cache'))
            if session_data['version'] != self.session_data_version:
                logger.warning("Session data from old version. Cache will be discarded.")
                assert False
            self.sections = [Section(self, cache=cache) for cache in session_data['sections']]
        except (AssertionError, FileNotFoundError):
            max_idx = len(self.g_pool.timestamps) - 1
            self.sections = [Section(self, label=make_section_label(),
                             calib_range=(0, max_idx), map_range=(0, max_idx))]
            session_data = {}
            session_data['circle_marker_positions'] = []
            session_data['manual_ref_positions'] = []
        self.circle_marker_positions = session_data['circle_marker_positions']
        self.manual_ref_positions = session_data['manual_ref_positions']
        if self.circle_marker_positions:
            self.detection_progress = 100.0
            for section in self.sections:
                section.calibrate()
            self.correlate_and_publish()
        else:
            self.detection_progress = 0.0

    def append_section(self):
        max_idx = len(self.g_pool.timestamps) - 1
        existing_labels = [sec['label'] for sec in self.sections]
        new_label = make_section_label(existing_labels)
        sec = Section(self, label=new_label,
                      calib_range=(0, max_idx),
                      map_range=(0, max_idx))
        self.sections.append(sec)
        if self.menu is not None:
            sec.init_ui()

    def init_ui(self):
        super().init_ui()
        self.menu.label = "Offline Calibration"

        self.glfont = fontstash.Context()
        self.glfont.add_font('opensans', ui.get_opensans_font_path())
        self.glfont.set_color_float((1., 1., 1., 1.))
        self.glfont.set_align_string(v_align='right', h_align='top')

        def use_as_natural_features():
            self.manual_ref_positions.extend(self.circle_marker_positions)
            self.manual_ref_positions.sort(key=lambda mr: mr['index'])

        def jump_next_natural_feature():
            self.manual_ref_positions.sort(key=lambda mr: mr['index'])
            current = self.g_pool.capture.get_frame_index()
            for nf in self.manual_ref_positions:
                if nf['index'] > current:
                    self.notify_all({'subject': 'seek_control.should_seek',
                                     'index': nf['index']})
                    return
            logger.error('No further natural feature available')

        def clear_natural_features():
            self.manual_ref_positions = []

        self.menu.append(ui.Info_Text('"Detection" searches for circle markers in the world video.'))
        # self.menu.append(ui.Button('Redetect', self.start_marker_detection))
        slider = ui.Slider('detection_progress', self, label='Detection Progress', setter=lambda _: _)
        slider.display_format = '%3.0f%%'
        self.menu.append(slider)

        toggle_label = 'Cancel circle marker detection' if self.process_pipe else 'Start circle marker detection'
        self.toggle_detection_button = ui.Button(toggle_label, self.toggle_marker_detection)
        self.menu.append(self.toggle_detection_button)

        self.menu.append(ui.Separator())

        self.menu.append(ui.Button('Use calibration markers as natural features', use_as_natural_features))
        self.menu.append(ui.Button('Jump to next natural feature', jump_next_natural_feature))
        self.menu.append(ui.Switch('manual_ref_edit_mode', self, label="Natural feature edit mode"))
        self.menu.append(ui.Button('Clear natural features', clear_natural_features))

        self.menu.append(ui.Info_Text('Calibration only considers pupil data that has an equal or higher confidence than the minimum calibration confidence.'))
        self.menu.append(ui.Slider('min_calibration_confidence', self.g_pool,
                                   step=.01, min=0.0, max=1.0,
                                   label='Minimum calibration confidence'))

        self.menu.append(ui.Button('Add section', self.append_section))

        # set to minimum height
        self.timeline = ui.Timeline('Calibration Sections', self.draw_sections, self.draw_labels, 1)
        self.g_pool.user_timelines.append(self.timeline)

        for sec in self.sections:
            sec.init_ui()

        self.on_window_resize(glfwGetCurrentContext(), *glfwGetWindowSize(glfwGetCurrentContext()))

    def deinit_ui(self):
        # needs to be called here since makes calls to the ui:
        self.cancel_marker_detection()
        super().deinit_ui()
        self.g_pool.user_timelines.remove(self.timeline)
        self.timeline = None
        self.glfont = None

    def get_init_dict(self):
        return {'manual_ref_edit_mode': self.manual_ref_edit_mode}

    def on_notify(self, notification):
        subject = notification['subject']
        if subject == 'pupil_positions_changed':
            for s in self.sections:
                s.calibrate()
        elif subject == 'gaze_positions_changed':
            self.save_cache()

    def on_click(self, pos, button, action):
        if action == GLFW_PRESS and self.manual_ref_edit_mode:
            manual_refs_in_frame = [r for r in self.manual_ref_positions
                                    if self.g_pool.capture.get_frame_index() == r['index']]
            for ref in manual_refs_in_frame:
                if np.sqrt((pos[0]-ref['screen_pos'][0])**2 + (pos[1]-ref['screen_pos'][1])**2) < 15:  # img pixels
                    del self.manual_ref_positions[self.manual_ref_positions.index(ref)]
                    return
            new_ref = { 'screen_pos': pos,
                        'norm_pos': normalize(pos, self.g_pool.capture.frame_size, flip_y=True),
                        'index': self.g_pool.capture.get_frame_index(),
                        'index_range': tuple(range(self.g_pool.capture.get_frame_index()-5,self.g_pool.capture.get_frame_index()+5)),
                        'timestamp': self.g_pool.timestamps[self.g_pool.capture.get_frame_index()]
                        }
            self.manual_ref_positions.append(new_ref)

    def recent_events(self, events):
        super().recent_events(events)

        if self.process_pipe and self.process_pipe.new_data:
            topic, msg = self.process_pipe.recv()
            if topic == 'progress':
                recent = msg.get('data', [])
                progress, data = zip(*recent)
                self.circle_marker_positions.extend([d for d in data if d])
                self.detection_progress = progress[-1]
            elif topic == 'finished':
                self.detection_progress = 100.
                self.process_pipe = None
                for s in self.sections:
                    s.calibrate()
            elif topic == 'exception':
                logger.warning('Calibration marker detection raised exception:\n{}'.format(msg['reason']))
                self.process_pipe = None
                self.detection_progress = 0.
                logger.info('Marker detection was interrupted')
                logger.debug('Reason: {}'.format(msg.get('reason', 'n/a')))
            self.menu_icon.indicator_stop = self.detection_progress / 100.

        for sec in self.sections:
            sec.recent_events()

    def correlate_and_publish(self):
        all_gaze = list(chain.from_iterable((s.gaze_positions for s in self.sections)))
        self.g_pool.gaze_positions = sorted(all_gaze, key=lambda d: d['timestamp'])
        self.g_pool.gaze_positions_by_frame = correlate_data(self.g_pool.gaze_positions, self.g_pool.timestamps)
        self.notify_all({'subject': 'gaze_positions_changed', 'delay':1})

    def calc_accuracy(self, section):
        predictions = section['gaze_positions']

        start = section['mapping_range'][0]
        end = section['mapping_range'][1]

        if section['calibration_method'] == 'circle_marker':
            ref_list = self.circle_marker_positions
        elif section['calibration_method'] == 'natural_features':
            ref_list = self.manual_ref_positions
        labels = [r for r in ref_list if start <= r['index'] <= end]

        if not labels or not predictions:
            return

        acc_calc = Accuracy_Visualizer(self.g_pool, outlier_threshold=section['outlier_threshold'])
        results = acc_calc.calc_acc_prec_errlines(predictions, labels, self.g_pool.capture.intrinsics)

        logger.info('Angular accuracy for {}: {}. Used {} of {} samples.'
                    .format(section['label'], *results[0]))
        logger.info("Angular precision for {}: {}. Used {} of {} samples."
                    .format(section['label'], *results[1]))
        section['accuracy'] = results[0].result
        section['precision'] = results[1].result
        section['error_lines'] = results[2]
        acc_calc.alive = False

    def gl_display(self):
        # normalize coordinate system, no need this step in utility functions
        with gl_utils.Coord_System(0, 1, 0, 1):
            ref_point_norm = [r['norm_pos'] for r in self.circle_marker_positions
                              if self.g_pool.capture.get_frame_index() == r['index']]
            cygl_utils.draw_points(ref_point_norm, size=35,
                                   color=cygl_utils.RGBA(0, .5, 0.5, .7))
            cygl_utils.draw_points(ref_point_norm, size=5,
                                   color=cygl_utils.RGBA(.0, .9, 0.0, 1.0))

            manual_refs_in_frame = [r for r in self.manual_ref_positions
                                    if self.g_pool.capture.get_frame_index() in r['index_range']]
            current = self.g_pool.capture.get_frame_index()
            for mr in manual_refs_in_frame:
                if mr['index'] == current:
                    cygl_utils.draw_points([mr['norm_pos']], size=35,
                                           color=cygl_utils.RGBA(.0, .0, 0.9, .8))
                    cygl_utils.draw_points([mr['norm_pos']], size=5,
                                           color=cygl_utils.RGBA(.0, .9, 0.0, 1.0))
                else:
                    distance = abs(current - mr['index'])
                    range_radius = (mr['index_range'][-1] - mr['index_range'][0]) // 2
                    # scale alpha [.1, .9] depending on distance to current frame
                    alpha = distance / range_radius
                    alpha = 0.1 * alpha + 0.9 * (1. - alpha)
                    # Use draw_progress instead of draw_circle. draw_circle breaks
                    # because of the normalized coord-system.
                    cygl_utils.draw_progress(mr['norm_pos'], 0., 0.999,
                                             inner_radius=20.,
                                             outer_radius=35.,
                                             color=cygl_utils.RGBA(.0, .0, 0.9, alpha))
                    cygl_utils.draw_points([mr['norm_pos']], size=5,
                                           color=cygl_utils.RGBA(.0, .9, 0.0, alpha))

        for sec in self.sections:
            if sec['vis_mapping_error'] and sec.error_lines is not None:
                cygl_utils.draw_polyline_norm(sec.error_lines,
                                              color=cygl_utils.RGBA(*sec['color']),
                                              line_type=gl.GL_LINES)

        # calculate correct timeline height. Triggers timeline redraw only if changed
        self.timeline.content_height = max(0.001, self.timeline_line_height * len(self.sections))

    def draw_sections(self, width, height, scale):
        t0, t1 = self.g_pool.timestamps[0], self.g_pool.timestamps[-1]
        pixel_to_time_fac = height / (t1 - t0)
        with gl_utils.Coord_System(t0, t1, height, 0):
            gl.glTranslatef(0, 0.001 + scale * self.timeline_line_height / 2, 0)
            for section in self.sections:
                section.draw(pixel_to_time_fac, scale)
                gl.glTranslatef(0, scale * self.timeline_line_height, 0)

    def draw_labels(self, width, height, scale):
        self.glfont.set_size(self.timeline_line_height * scale)
        for idx, section in enumerate(self.sections):
            self.glfont.draw_text(width, 0, section['label'])
            gl.glTranslatef(0, self.timeline_line_height * scale, 0)

    def toggle_marker_detection(self):
        if self.process_pipe:
            self.cancel_marker_detection()
        else:
            self.start_marker_detection()

    def start_marker_detection(self):
        self.circle_marker_positions = []
        source_path = self.g_pool.capture.source_path
        self.process_pipe = zmq_tools.Msg_Pair_Server(self.g_pool.zmq_ctx)
        self.notify_all({'subject': 'circle_detector_process.should_start',
                         'source_path': source_path, "pair_url": self.process_pipe.url})

        self.detection_progress = 0.
        self.menu_icon.indicator_stop = 0.
        self.toggle_detection_button.label = 'Cancel circle marker detection'

    def cancel_marker_detection(self):
        if self.process_pipe:
            self.process_pipe.send(topic='terminate', payload={})
            self.process_pipe.socket.close()
            self.process_pipe = None

            self.detection_progress = 0.
            self.menu_icon.indicator_stop = 0.
            self.toggle_detection_button.label = 'Start circle marker detection'

    def cleanup(self):
        for sec in self.sections:
            if sec.bg_task:
                sec.bg_task.cancel()
        self.save_cache()

    def save_cache(self):
        session_data = {}
        session_data['sections'] = [sec.cache for sec in self.sections]
        session_data['version'] = self.session_data_version
        session_data['manual_ref_positions'] = self.manual_ref_positions
        if self.detection_progress == 100.0:
            session_data['circle_marker_positions'] = self.circle_marker_positions
        else:
            session_data['circle_marker_positions'] = []
        cache_path = os.path.join(self.cache_path, 'offline_calibration_cache')
        save_object(session_data, cache_path)
        logger.info('Cached offline calibration data to {}'.format(cache_path))
