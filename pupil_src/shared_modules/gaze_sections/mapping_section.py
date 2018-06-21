'''
(*)~---------------------------------------------------------------------------
Pupil - eye tracking platform
Copyright (C) 2012-2018 Pupil Labs

Distributed under the terms of the GNU
Lesser General Public License (LGPL v3.0).
See COPYING and COPYING.LESSER for license details.
---------------------------------------------------------------------------~(*)
'''
from gaze_sections import colors
from gaze_sections.base_sections import Importing_Section


class Mapping_Section(Importing_Section):
    order = .5
    timeline_color = colors['purple']

    def __init__(self, g_pool, x_offset=0., y_offset=0., *args, **kwargs):
        super().__init__(g_pool, *args, **kwargs)
        self.x_offset = x_offset
        self.y_offset = y_offset

    def get_init_dict(self):
        init_dict = super().get_init_dict()
        init_dict['x_offset'] = self.x_offset
        init_dict['y_offset'] = self.y_offset
        return init_dict

