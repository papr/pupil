"""
(*)~---------------------------------------------------------------------------
Pupil - eye tracking platform
Copyright (C) 2012-2020 Pupil Labs

Distributed under the terms of the GNU
Lesser General Public License (LGPL v3.0).
See COPYING and COPYING.LESSER for license details.
---------------------------------------------------------------------------~(*)
"""
import os
import abc
import logging

import numpy as np

from observable import Observable
from plugin import Plugin

from .scan_path_preprocessing_task import ScanPathPreprocessingTask
from .scan_path_background_task import ScanPathBackgroundTask
from .scan_path_storage import ScanPathStorage


logger = logging.getLogger(__name__)


class ScanPathController(Observable):

    min_timeframe = 0.0
    max_timeframe = 5.0
    timeframe_step = 0.05

    def __init__(self, g_pool, timeframe=None):
        self.g_pool = g_pool

        self.timeframe = timeframe if timeframe is not None else self.min_timeframe
        assert self.min_timeframe <= self.timeframe <= self.max_timeframe

        self._status_str = ""

        self._preproc = ScanPathPreprocessingTask(g_pool)
        self._preproc.add_observer("on_started", self._on_preproc_started)
        self._preproc.add_observer("on_updated", self._on_preproc_updated)
        self._preproc.add_observer("on_failed", self._on_preproc_failed)
        self._preproc.add_observer("on_canceled", self._on_preproc_canceled)
        self._preproc.add_observer("on_completed", self._on_preproc_completed)

        self._bg_task = ScanPathBackgroundTask(g_pool)
        self._bg_task.add_observer("on_started", self._on_bg_task_started)
        self._bg_task.add_observer("on_updated", self._on_bg_task_updated)
        self._bg_task.add_observer("on_failed", self._on_bg_task_failed)
        self._preproc.add_observer("on_canceled", self._on_bg_task_canceled)
        self._bg_task.add_observer("on_completed", self._on_bg_task_completed)

        self._gaze_data_store = ScanPathStorage(g_pool.rec_dir)
        self._trigger_delayed_loading_from_disk()

    def get_init_dict(self):
        return {}  # Don't save the current timeframe; always set to 0.0 on startup.

    @property
    def is_active(self) -> bool:
        return self._preproc.is_active or self._bg_task.is_active

    @property
    def progress(self) -> float:
        if self.is_active:
            ratio = 0.85
            return (
                1.0 - ratio
            ) * self._preproc.progress + ratio * self._bg_task.progress
        else:
            return 0.0  # idle

    @property
    def status_string(self) -> str:
        return self._status_str

    def process(self):
        self._preproc.process()
        self._bg_task.process()

    def scan_path_gaze_for_frame(self, frame):
        if self.timeframe == 0.0:
            return self._gaze_data_store.empty_gaze_data()

        if not self._gaze_data_store.is_valid or not self._gaze_data_store.is_complete:
            if not self.is_active:
                self._trigger_immediate_scan_path_calculation()
            return None

        timestamp_cutoff = frame.timestamp - self.timeframe

        gaze_data = self._gaze_data_store.gaze_data
        gaze_data = gaze_data[gaze_data.frame_index == frame.index]
        gaze_data = gaze_data[gaze_data.timestamp > timestamp_cutoff]

        return gaze_data

    def cleanup(self):
        self._preproc.cleanup()
        self._bg_task.cleanup()

    def on_notify(self, notification):
        if notification["subject"] == self._recalculate_scan_path_notification_subject:
            self._trigger_immediate_scan_path_calculation()
        elif (
            notification["subject"]
            == self._load_from_disk_scan_path_notification_subject
        ):
            self._gaze_data_store.load_from_disk()
        elif notification["subject"] == "gaze_positions_changed":
            self._gaze_data_store.mark_invalid()

    def on_update_ui(self):
        pass

    # Private - helpers

    _recalculate_scan_path_notification_subject = "scan_path.should_recalculate"

    _load_from_disk_scan_path_notification_subject = "scan_path.should_load_from_disk"

    def _trigger_delayed_loading_from_disk(self, delay=0.5):
        Plugin.notify_all(
            self,
            {
                "subject": self._load_from_disk_scan_path_notification_subject,
                "delay": delay,
            },
        )

    def _trigger_delayed_scan_path_calculation(self, delay=1.0):
        Plugin.notify_all(
            self,
            {
                "subject": self._recalculate_scan_path_notification_subject,
                "delay": delay,
            },
        )

    def _trigger_immediate_scan_path_calculation(self):
        # Cancel old tasks
        self._preproc.cancel()
        self._bg_task.cancel()
        # Start new tasks
        self._preproc.start()

    # Private - preprocessing callbacks

    def _on_preproc_started(self):
        logger.debug("ScanPathController._on_preproc_started")
        self._status_str = "Preprocessing started..."
        self.on_update_ui()

    def _on_preproc_updated(self, gaze_datum):
        logger.debug("ScanPathController._on_preproc_updated")
        self._status_str = f"Preprocessing {int(self._preproc.progress * 100)}%..."
        self.on_update_ui()

    def _on_preproc_failed(self, error):
        logger.debug("ScanPathController._on_preproc_failed")
        logger.error(f"Scan path preprocessing failed: {error}")
        self._status_str = "Preprocessing failed"
        self.on_update_ui()

    def _on_preproc_canceled(self):
        logger.debug("ScanPathController._on_preproc_canceled")
        self._status_str = "Preprocessing canceled"
        self.on_update_ui()

    def _on_preproc_completed(self, gaze_data):
        logger.debug("ScanPathController._on_preproc_completed")
        self._status_str = "Preprocessing completed"
        # Start the background task with max_timeframe
        # The current timeframe will be used only for visualization
        self._bg_task.start(self.max_timeframe, gaze_data)
        self.on_update_ui()

    # Private - calculation callbacks

    def _on_bg_task_started(self):
        logger.debug("ScanPathController._on_bg_task_started")
        self._status_str = "Calculation started..."
        self.on_update_ui()

    def _on_bg_task_updated(self, update_data):
        logger.debug("ScanPathController._on_bg_task_updated")
        self._status_str = f"Calculation {int(self._bg_task.progress * 100)}%..."
        # TODO: Save intermediary data
        self.on_update_ui()

    def _on_bg_task_failed(self, error):
        logger.debug("ScanPathController._on_bg_task_failed")
        logger.error(f"Scan path calculation failed: {error}")
        self._status_str = "Calculation failed"
        self.on_update_ui()

    def _on_bg_task_canceled(self):
        logger.debug("ScanPathController._on_bg_task_canceled")
        self._status_str = "Calculation canceled"
        self.on_update_ui()

    def _on_bg_task_completed(self, complete_data):
        logger.debug("ScanPathController._on_bg_task_completed")
        self._gaze_data_store.gaze_data = complete_data
        self._gaze_data_store.mark_complete()
        self._status_str = "Calculation completed"
        self.on_update_ui()
