"""Bottom progress panel.

Shows:
  - A stage label (e.g. "부분 해시 계산 중...")
  - Overall pipeline progress bar (scan→hash→detect→delete)
  - Per-stage progress bar with ETA
  - Current file path and throughput
"""

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


def _fmt_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}초"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}분 {s:02d}초"


class ProgressPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._start_time: float = 0.0
        self._last_done: int    = 0
        self._last_time: float  = 0.0
        self._speed_window: list[float] = []   # recent samples (files/sec)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        # Stage label
        self._lbl_stage = QLabel("대기 중")
        self._lbl_stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._lbl_stage)

        # Overall bar
        row1 = QHBoxLayout()
        lbl1 = QLabel("전체:")
        lbl1.setFixedWidth(36)
        self._bar_overall = QProgressBar()
        self._bar_overall.setRange(0, 100)
        self._bar_overall.setTextVisible(True)
        row1.addWidget(lbl1)
        row1.addWidget(self._bar_overall)
        layout.addLayout(row1)

        # Stage bar
        row2 = QHBoxLayout()
        lbl2 = QLabel("단계:")
        lbl2.setFixedWidth(36)
        self._bar_stage = QProgressBar()
        self._bar_stage.setRange(0, 100)
        self._bar_stage.setTextVisible(True)
        row2.addWidget(lbl2)
        row2.addWidget(self._bar_stage)
        layout.addLayout(row2)

        # Current file + ETA row
        info_row = QHBoxLayout()
        self._lbl_file = QLabel("")
        self._lbl_file.setWordWrap(False)
        self._lbl_eta  = QLabel("")
        self._lbl_eta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_eta.setFixedWidth(220)
        info_row.addWidget(self._lbl_file, stretch=3)
        info_row.addWidget(self._lbl_eta,  stretch=0)
        layout.addLayout(info_row)

    # ── public interface ──────────────────────────────────────────────────

    def start_pipeline(self) -> None:
        """Call once at the beginning of a full scan+delete pipeline."""
        self._bar_overall.setValue(0)
        self._bar_stage.setValue(0)
        self._lbl_file.setText("")
        self._lbl_eta.setText("")
        self._timer.start()

    def set_stage(self, name: str) -> None:
        """Called when moving to a new processing stage."""
        self._lbl_stage.setText(name)
        self._bar_stage.setValue(0)
        self._reset_speed()

    def update_stage(self, done: int, total: int, path: str = "") -> None:
        """Granular progress within the current stage."""
        if total > 0:
            pct = int(done / total * 100)
            self._bar_stage.setValue(pct)
        # Trim path to avoid layout thrash
        self._lbl_file.setText(path[-90:] if len(path) > 90 else path)
        self._sample_speed(done)

    def set_overall(self, pct: int) -> None:
        self._bar_overall.setValue(max(0, min(100, pct)))

    def finish(self) -> None:
        self._timer.stop()
        self._bar_overall.setValue(100)
        self._bar_stage.setValue(100)
        elapsed = time.monotonic() - self._start_time if self._start_time else 0
        self._lbl_stage.setText("완료")
        self._lbl_eta.setText(f"소요 시간: {_fmt_eta(elapsed)}")
        self._lbl_file.setText("")

    def reset(self) -> None:
        self._timer.stop()
        self._bar_overall.setValue(0)
        self._bar_stage.setValue(0)
        self._lbl_stage.setText("대기 중")
        self._lbl_file.setText("")
        self._lbl_eta.setText("")
        self._reset_speed()

    # ── internals ─────────────────────────────────────────────────────────

    def _reset_speed(self) -> None:
        self._start_time = time.monotonic()
        self._last_done  = 0
        self._last_time  = self._start_time
        self._speed_window.clear()

    def _sample_speed(self, done: int) -> None:
        now = time.monotonic()
        dt  = now - self._last_time
        if dt >= 0.3:
            speed = (done - self._last_done) / dt
            self._speed_window.append(speed)
            if len(self._speed_window) > 8:
                self._speed_window.pop(0)
            self._last_done = done
            self._last_time = now

    def _tick(self) -> None:
        if not self._speed_window:
            return
        avg_speed = sum(self._speed_window) / len(self._speed_window)
        pct_done  = self._bar_stage.value()
        pct_left  = 100 - pct_done
        if avg_speed > 0 and pct_left > 0:
            # Rough ETA: remaining pct units / rate-of-pct-change
            elapsed = time.monotonic() - self._start_time
            if pct_done > 0:
                eta = elapsed / pct_done * pct_left
                self._lbl_eta.setText(
                    f"{avg_speed:.0f} 파일/초  |  ETA: {_fmt_eta(eta)}"
                )
