'''
(*)~---------------------------------------------------------------------------
Pupil - eye tracking platform
Copyright (C) 2012-2018 Pupil Labs

Distributed under the terms of the GNU
Lesser General Public License (LGPL v3.0).
See COPYING and COPYING.LESSER for license details.
---------------------------------------------------------------------------~(*)
'''
from pyglui.cygl import utils as cygl_utils
import OpenGL.GL as gl

from gaze_sections import colors
from gaze_sections.base_sections import Importing_Section


class Validation_Section(Importing_Section):
    order = .7
    timeline_color = colors['red']

    def __init__(self, g_pool, vis_mapping_error=True,
                 outlier_threshold=5., *args, **kwargs):
        super().__init__(g_pool, *args, **kwargs)
        self.vis_mapping_error = vis_mapping_error
        self.outlier_threshold = outlier_threshold
        self.error_lines = None

    def get_init_dict(self):
        init_dict = super().get_init_dict()
        init_dict['vis_mapping_error'] = self.vis_mapping_error
        init_dict['outlier_threshold'] = self.outlier_threshold
        return init_dict

    def gl_display(self):
        if self.vis_mapping_error and self.error_lines is not None:
            color = cygl_utils.RGBA(*self.timeline_color)
            cygl_utils.draw_polyline_norm(self.error_lines,
                                          color=color,
                                          line_type=gl.GL_LINES)
