'''
(*)~---------------------------------------------------------------------------
Pupil - eye tracking platform
Copyright (C) 2012-2017  Pupil Labs

Distributed under the terms of the GNU
Lesser General Public License (LGPL v3.0).
See COPYING and COPYING.LESSER for license details.
---------------------------------------------------------------------------~(*)
'''

from pyglui.cygl.utils import draw_polyline, draw_points, RGBA

from plugin import Plugin
from pyglui import ui
from collections import deque
from itertools import islice
import numpy as np
import math
import logging
logger = logging.getLogger(__name__)


class Blink_Detection(Plugin):
    """
    This plugin implements a blink detection algorithm, based on sudden drops in the
    pupil detection confidence.
    """
    order = .8

    def __init__(self, g_pool):
        super(Blink_Detection, self).__init__(g_pool)
        self.history_length = .3  # unit: seconds

        # self.minimum_change = 0.7  # minimum difference between min and max confidence value in history
        self.minimum_onset_response = 0.3
        self.minimum_offset_response = 0.3

        self.history = deque()
        self.menu = None
        self.recent_act = None

    def init_gui(self):
        self.menu = ui.Growing_Menu('Blink Detector')
        self.g_pool.sidebar.append(self.menu)
        self.menu.append(ui.Info_Text('This plugin detects blinks based on binocular confidence drops.'))
        self.menu.append(ui.Button('Close', self.close))

    def deinit_gui(self):
        if self.menu:
            self.g_pool.sidebar.remove(self.menu)
            self.menu = None

    def close(self):
        self.alive = False

    def cleanup(self):
        self.deinit_gui()

    def recent_events(self, events={}):
        events['blinks'] = []
        self.history.extend(events.get('pupil_positions', []))

        try:  # use newest gaze point to determine age threshold
            age_threshold = self.history[-1]['timestamp'] - self.history_length
            while self.history[1]['timestamp'] < age_threshold:
                self.history.popleft()  # remove outdated gaze points
        except IndexError:
            pass

        filter_size = len(self.history)
        if filter_size < 2 or self.history[-1]['timestamp'] - self.history[0]['timestamp'] < self.history_length:
            return

        activity = np.fromiter((pp['confidence'] for pp in self.history), dtype=float)
        act_freq = np.fft.rfft(activity)
        self.recent_act = np.abs(act_freq)

    def gen_hist_points(self, x=0, y=0, binwidth=10, scale=100.):
        if self.recent_act is not None:
            cs = np.cumsum(self.recent_act[1:])
            idx25 = np.argmax(cs > cs[-1]*.25)
            idx50 = np.argmax(cs > cs[-1]*.5)
            draw_points([(x+idx25*binwidth, y), (x+idx50*binwidth, y)], color=RGBA(1.,0.5,0.5,1.))

            for idx, val in enumerate(self.recent_act[1:]):
                yield x+idx*binwidth, y+val*scale
                # yield x+idx*binwidth+binwidth, y+val*scale

    def gl_display(self):
        points = list(self.gen_hist_points(x=200, y=200, scale=30., binwidth=20.))
        draw_polyline(points, thickness=5, color=RGBA(1.,0.5,0.5,1.))

    def get_init_dict(self):
        return {}
