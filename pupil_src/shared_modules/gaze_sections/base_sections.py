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

from pyglui import ui
from pyglui.cygl import utils as cygl_utils

from plugin import System_Plugin_Base

logger = logging.getLogger(__name__)


class Base_Section(System_Plugin_Base):
    def __init__(self, g_pool, label=None, application_range=None, *args, **kwargs):
        super().__init__(g_pool)
        self.bg_task = None
        self.label = label or self.make_section_label()
        self.range = application_range

    def get_init_dict(self):
        return {'label': self.label, 'application_range': self.range}

    def init_ui(self):
        self.add_menu()
        self.menu.label = self.pretty_class_name
        self.menu_icon.tooltip = self.class_name.split('_')[0] + self.label
        self.menu.append(ui.Text_Input('label', self.cache, label='Label',
                                       setter=self.validate_label))
        self.append_section_specific_menu()

    def deinit_ui(self):
        del self.menu[:]
        self.remove_menu()

    def make_section_label(self):
        existing_labels = (s.label for s in self.g_pool.gaze_manager.sections)
        counter = 1
        while True:
            label = 'Unnamed section {}'.format(counter)
            if label in existing_labels:
                counter += 1
            else:
                return label

    def validate_label(self, new_label):
        if new_label == self.label:
            return
        elif new_label in (s.label for s in self.g_pool.gaze_manager.sections):
            logger.warning('Duplicated section label')
        else:
            self.label = new_label
            self.menu_icon.tooltip = self.class_name.split('_')[0] + self.label

    def cleanup(self):
        if self.bg_task:
            self.bg_task.cancel()

    def recent_events(self):
        if self.bg_task:
            recent = [d for d in self.bg_task.fetch()]
            for result in recent:
                self.handle_task_result(result)
            if self.bg_task.completed:
                self.on_task_completed()
                self.bg_task = None

    def handle_task_result(self, result):
        pass

    def on_task_completed(self):
        pass

    def append_set_from_trim_marks_button(self):
        button = ui.Button('Set from trim marks', None)

        def set_from_trim_marks(format_only=False):
            if format_only:
                left_idx, right_idx = self.range
            else:
                right_idx = self.g_pool.seek_control.trim_right
                left_idx = self.g_pool.seek_control.trim_left
                self.range = left_idx, right_idx

            time_fmt = self.pretty_class_name.split(' ')[0]
            min_ts = self.g_pool.timestamps[0]
            for idx in (left_idx, right_idx):
                ts = self.parent.g_pool.timestamps[idx] - min_ts
                minutes = ts // 60
                seconds = ts - (minutes * 60.)
                time_fmt += ' {:02.0f}:{:02.0f} -'.format(abs(minutes), seconds)
            button.outer_label = time_fmt[:-2]  # remove final ' -'
        button.function = set_from_trim_marks
        set_from_trim_marks(format_only=True)
        self.menu.append(button)

    def draw_range(self, pixel_to_time_factor, scale):
        timestamps = self.g_pool.timestamps[slice(*self.range)]

        color = cygl_utils.RGBA(*self.timeline_color)
        if len(timestamps):
            cygl_utils.draw_rounded_rect((timestamps[0], -4 * scale),
                                         (timestamps[-1] - timestamps[0], 8 * scale),
                                         corner_radius=0,
                                         color=color,
                                         sharpness=1.)


class Importing_Section(Base_Section):
    def __init__(self, g_pool, import_section=None, *args, **kwargs):
        super().__init__(g_pool, *args, **kwargs)
        self.import_section = import_section

    def get_init_dict(self):
        init_dict = super().get_init_dict()
        init_dict['import_section'] = self.import_section
        return init_dict
