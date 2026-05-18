"""Main application window.

Orchestrates the scan → hash → detect → delete pipeline by wiring
the worker threads (signals/slots) to the UI panels.

Pipeline overview
-----------------
[스캔 시작] → ScanWorker
                 ↓ finished
             HashWorker
                 ↓ finished
             DuplicateDetector.detect()
                 ↓
             ResultPanel.load_groups()
                 ↓ user reviews & clicks [선택 삭제]
             CleanWorker
                 ↓ finished
             Result dialog
"""

import csv
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.core.cleaner import CleanWorker
from src.core.detector import DuplicateDetector
from src.core.hasher import HashWorker
from src.core.scanner import ScanWorker
from src.models.file_info import DuplicateGroup, FileInfo, fmt_size
from src.ui.filter_panel import FilterPanel
from src.ui.folder_panel import FolderPanel
from src.ui.progress_panel import ProgressPanel
from src.ui.result_panel import ResultPanel
from src.utils.cache import HashCache
from src.utils.config import Config

# Overall pipeline stage weights (must sum to 100)
_W_SCAN   = 20
_W_HASH   = 60
_W_DETECT = 5
_W_DELETE = 15

_LOG_PATH = Path.home() / ".garden_tools_doubledown" / "delete_log.json"


class MainWindow(QMainWindow):
    def __init__(self, config: Config, cache: HashCache) -> None:
        super().__init__()
        self._config = config
        self._cache  = cache

        # Active workers (None when idle)
        self._scan_worker:  Optional[ScanWorker]  = None
        self._hash_worker:  Optional[HashWorker]  = None
        self._clean_worker: Optional[CleanWorker] = None

        # Runtime state
        self._scanned_files: list[FileInfo]     = []
        self._groups:        list[DuplicateGroup] = []

        self._setup_ui()
        self._restore_config()

    # ═════════════════════════════════════════════════════════════════════
    #  UI construction
    # ═════════════════════════════════════════════════════════════════════

    def _setup_ui(self) -> None:
        self.setWindowTitle("Garden Tools DoubleDown — 중복 파일 제거")
        self.setMinimumSize(1_050, 700)
        self.resize(1_280, 800)

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()

    def _build_toolbar(self) -> None:
        tb = QToolBar("메인 도구 모음")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)

        self._act_scan = QAction("▶  스캔 시작", self)
        self._act_scan.setToolTip("선택한 폴더에서 중복 파일을 검색합니다 (Ctrl+R)")
        self._act_scan.setShortcut("Ctrl+R")
        self._act_scan.triggered.connect(self._start_scan)
        tb.addAction(self._act_scan)

        self._act_pause = QAction("⏸  일시정지", self)
        self._act_pause.setToolTip("현재 해시 계산을 일시정지/재개합니다")
        self._act_pause.setEnabled(False)
        self._act_pause.setCheckable(True)
        self._act_pause.toggled.connect(self._toggle_pause)
        tb.addAction(self._act_pause)

        self._act_stop = QAction("■  중지", self)
        self._act_stop.setToolTip("진행 중인 작업을 중단합니다")
        self._act_stop.setEnabled(False)
        self._act_stop.triggered.connect(self._stop_all)
        tb.addAction(self._act_stop)

        tb.addSeparator()

        self._act_delete = QAction("🗑  선택 파일 삭제", self)
        self._act_delete.setToolTip("체크된 파일을 삭제합니다 (Ctrl+D)")
        self._act_delete.setShortcut("Ctrl+D")
        self._act_delete.setEnabled(False)
        self._act_delete.triggered.connect(self._start_delete)
        tb.addAction(self._act_delete)

        tb.addSeparator()

        self._act_export = QAction("📄  CSV 내보내기", self)
        self._act_export.setToolTip("중복 파일 목록을 CSV 파일로 저장합니다")
        self._act_export.setEnabled(False)
        self._act_export.triggered.connect(self._export_csv)
        tb.addAction(self._act_export)

        # Spacer label showing quick stats
        self._lbl_toolbar = QLabel("   폴더를 추가하고 스캔을 시작하세요")
        tb.addWidget(self._lbl_toolbar)

    def _build_central(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(6, 6, 6, 4)
        root_layout.setSpacing(4)

        # Horizontal splitter: left (settings) | right (results)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self._folder_panel = FolderPanel()
        left_layout.addWidget(self._folder_panel)

        self._filter_panel = FilterPanel()
        left_layout.addWidget(self._filter_panel)

        splitter.addWidget(left)

        self._result_panel = ResultPanel()
        self._result_panel.selection_changed.connect(self._on_selection_changed)
        splitter.addWidget(self._result_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([290, 990])

        root_layout.addWidget(splitter, stretch=1)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root_layout.addWidget(line)

        # Progress panel
        self._progress = ProgressPanel()
        root_layout.addWidget(self._progress)

    def _build_statusbar(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._lbl_status = QLabel("준비")
        sb.addWidget(self._lbl_status, 1)
        self._lbl_sel_info = QLabel("")
        sb.addPermanentWidget(self._lbl_sel_info)

    # ═════════════════════════════════════════════════════════════════════
    #  Config persistence
    # ═════════════════════════════════════════════════════════════════════

    def _restore_config(self) -> None:
        self._folder_panel.set_folders(self._config.get("last_folders", []))
        self._filter_panel.apply_config(self._config)

    def closeEvent(self, event) -> None:
        self._stop_all()
        self._filter_panel.save_to_config(self._config)
        self._config.set("last_folders", [str(p) for p in self._folder_panel.folders()])
        self._config.save()
        self._cache.close()
        super().closeEvent(event)

    # ═════════════════════════════════════════════════════════════════════
    #  Scan pipeline
    # ═════════════════════════════════════════════════════════════════════

    def _start_scan(self) -> None:
        folders = self._folder_panel.folders()
        if not folders:
            QMessageBox.warning(self, "폴더 없음", "먼저 검색할 폴더를 추가하세요.")
            return

        # Disconnect and stop any workers left over from a previous run.
        # This covers the race where a naturally-completing scan queued its
        # 'finished' signal just as the user clicked Stop; that queued callback
        # can leave a HashWorker running even though _set_busy(False) fired.
        self._stop_all()

        self._result_panel.clear()
        self._groups = []
        self._scanned_files = []
        self._set_busy(True)
        self._progress.start_pipeline()
        self._progress.set_stage("파일 탐색 중...")
        self._status("파일 탐색 중...")

        self._scan_worker = ScanWorker(
            folders             = folders,
            min_size            = self._filter_panel.min_size_bytes(),
            max_size            = self._filter_panel.max_size_bytes(),
            extensions          = self._filter_panel.extensions(),
            excluded_extensions = self._filter_panel.excluded_extensions(),
            include_hidden      = self._filter_panel.include_hidden(),
        )
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_worker.error_occurred.connect(self._on_error)
        self._scan_worker.start()

    def _on_scan_progress(self, count: int, path: str) -> None:
        self._progress.update_stage(count % 100, 100, path)
        self._status(f"파일 탐색 중... {count:,}개 발견")

    def _on_scan_done(self, files: list[FileInfo]) -> None:
        self._scanned_files = files
        self._progress.set_overall(_W_SCAN)
        self._status(f"탐색 완료: {len(files):,}개 파일")

        if not files:
            QMessageBox.information(self, "결과 없음", "필터 조건에 맞는 파일이 없습니다.")
            self._set_busy(False)
            self._progress.reset()
            return

        self._progress.set_stage(f"해시 계산 중... ({len(files):,}개)")
        self._status(f"해시 계산 중... ({len(files):,}개 파일)")
        self._act_pause.setEnabled(True)

        self._hash_worker = HashWorker(
            files       = files,
            cache       = self._cache,
            max_workers = self._config.get("max_workers", 4),
        )
        self._hash_worker.stage_changed.connect(self._progress.set_stage)
        self._hash_worker.progress.connect(self._on_hash_progress)
        self._hash_worker.finished.connect(self._on_hash_done)
        self._hash_worker.error_occurred.connect(self._on_error)
        self._hash_worker.start()

    def _on_hash_progress(self, done: int, total: int, path: str) -> None:
        self._progress.update_stage(done, total, path)
        overall = _W_SCAN + int(done / total * _W_HASH) if total else _W_SCAN
        self._progress.set_overall(overall)
        self._status(f"해시 계산 중... {done:,} / {total:,}")

    def _on_hash_done(self, hashed: list[FileInfo]) -> None:
        self._act_pause.setEnabled(False)
        self._act_pause.setChecked(False)

        self._progress.set_overall(_W_SCAN + _W_HASH)
        self._progress.set_stage("중복 분석 중...")

        detector = DuplicateDetector(
            prefer_folders=[
                Path(p) for p in self._config.get("prefer_folders", [])
            ]
        )
        self._groups = detector.detect(hashed)
        self._progress.set_overall(_W_SCAN + _W_HASH + _W_DETECT)

        if not self._groups:
            QMessageBox.information(
                self, "중복 없음",
                "선택한 폴더에 중복 파일이 없습니다.\n디스크가 이미 깨끗합니다!"
            )
            self._set_busy(False)
            self._progress.finish()
            return

        self._result_panel.load_groups(self._groups)
        self._act_export.setEnabled(True)
        self._progress.finish()
        self._set_busy(False)

        total_waste = sum(g.wasted_size for g in self._groups)
        self._lbl_toolbar.setText(
            f"   스캔 완료 — {len(self._groups):,}개 그룹 발견  |  "
            f"절약 가능: {fmt_size(total_waste)}"
        )
        self._status(
            f"완료: {len(self._groups):,}개 중복 그룹  "
            f"({fmt_size(total_waste)} 절약 가능)"
        )

    # ═════════════════════════════════════════════════════════════════════
    #  Delete pipeline
    # ═════════════════════════════════════════════════════════════════════

    def _start_delete(self) -> None:
        to_delete = self._result_panel.get_files_to_delete()
        if not to_delete:
            QMessageBox.information(self, "선택 없음", "삭제할 파일이 선택되지 않았습니다.")
            return

        total_bytes = sum(f.size for f in to_delete)
        use_trash   = self._filter_panel.use_trash()
        dry_run     = self._filter_panel.dry_run()

        method_str = "휴지통으로 이동" if use_trash else "영구 삭제 (복구 불가!)"
        dry_note   = "\n\n[드라이 런 모드 — 실제로 삭제하지 않습니다]" if dry_run else ""

        answer = QMessageBox.question(
            self,
            "삭제 확인",
            f"선택한 파일 {len(to_delete):,}개 ({fmt_size(total_bytes)})을\n"
            f"{method_str}하겠습니까?{dry_note}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._set_busy(True)
        self._progress.start_pipeline()
        self._progress.set_stage("파일 삭제 중...")

        self._clean_worker = CleanWorker(
            to_delete = to_delete,
            use_trash = use_trash,
            dry_run   = dry_run,
            log_path  = _LOG_PATH,
        )
        self._clean_worker.progress.connect(self._on_clean_progress)
        self._clean_worker.finished.connect(self._on_clean_done)
        self._clean_worker.error_occurred.connect(self._on_error)
        self._clean_worker.start()

    def _on_clean_progress(self, done: int, total: int, path: str) -> None:
        self._progress.update_stage(done, total, path)
        self._progress.set_overall(int(done / total * 100) if total else 0)

    def _on_clean_done(self, deleted: int, freed: int) -> None:
        self._progress.finish()
        self._set_busy(False)
        dry_note = " (드라이 런)" if self._filter_panel.dry_run() else ""

        QMessageBox.information(
            self,
            f"삭제 완료{dry_note}",
            f"삭제된 파일 수: {deleted:,}개\n"
            f"확보된 디스크 용량: {fmt_size(freed)}"
            + (f"\n\n삭제 로그: {_LOG_PATH}" if not self._filter_panel.dry_run() else ""),
        )
        self._status(f"삭제 완료{dry_note}: {deleted:,}개  |  {fmt_size(freed)} 확보")

        if not self._filter_panel.dry_run():
            self._result_panel.clear()
            self._groups = []
            self._act_delete.setEnabled(False)
            self._act_export.setEnabled(False)

    # ═════════════════════════════════════════════════════════════════════
    #  Toolbar / state helpers
    # ═════════════════════════════════════════════════════════════════════

    def _set_busy(self, busy: bool) -> None:
        self._act_scan.setEnabled(not busy)
        self._act_stop.setEnabled(busy)
        if not busy:
            self._act_pause.setEnabled(False)
            self._act_pause.setChecked(False)
        self._act_delete.setEnabled(not busy and bool(self._groups))

    def _toggle_pause(self, checked: bool) -> None:
        if self._hash_worker and self._hash_worker.isRunning():
            self._hash_worker.set_paused(checked)
            self._act_pause.setText("▶  재개" if checked else "⏸  일시정지")
            self._status("일시정지됨" if checked else "재개 중...")

    def _stop_all(self) -> None:
        workers = (self._scan_worker, self._hash_worker, self._clean_worker)

        # Pass 1: request stop and wait — thread must be fully joined before we
        # touch the signal connections.  Disconnecting while a worker thread is
        # still inside emit() creates a race; waiting first avoids it.
        for w in workers:
            if w is not None and w.isRunning():
                w.stop()
                w.wait()   # no timeout — _full_hash is now cancellable per-chunk

        # Pass 2: disconnect signals.  At this point no worker thread is running,
        # so no concurrent emit() can race with disconnect().  Removing connections
        # also invalidates any already-queued cross-thread signal events so stale
        # callbacks (e.g. a 'finished' that fired just before stop) are dropped.
        for w in workers:
            if w is None:
                continue
            for sig_name in ("progress", "finished", "error_occurred", "stage_changed"):
                sig = getattr(w, sig_name, None)
                if sig is not None:
                    try:
                        sig.disconnect()
                    except (TypeError, RuntimeError):
                        pass

        # Nullify references so GC never deletes a QThread whose OS thread is
        # still alive (would raise "bad parameter or other API misuse").
        self._scan_worker  = None
        self._hash_worker  = None
        self._clean_worker = None
        self._set_busy(False)
        self._progress.reset()
        self._status("중지됨")

    def _on_selection_changed(self, count: int, total_bytes: int) -> None:
        if count > 0:
            self._lbl_sel_info.setText(
                f"선택: {count:,}개  ({fmt_size(total_bytes)} 절약 가능)"
            )
            self._act_delete.setEnabled(True)
        else:
            self._lbl_sel_info.setText("")
            self._act_delete.setEnabled(False)

    def _on_error(self, msg: str) -> None:
        self._set_busy(False)
        self._progress.reset()
        QMessageBox.critical(self, "오류", msg)

    def _status(self, text: str) -> None:
        self._lbl_status.setText(text)

    def _set_overall(self, pct: int) -> None:
        self._progress.set_overall(pct)

    # ═════════════════════════════════════════════════════════════════════
    #  CSV export
    # ═════════════════════════════════════════════════════════════════════

    def _export_csv(self) -> None:
        if not self._groups:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "CSV 저장", "duplicate_report.csv", "CSV 파일 (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["그룹", "상태", "파일명", "크기(bytes)", "경로", "SHA-256"])
                for i, g in enumerate(self._groups, 1):
                    for j, fi in enumerate(g.files):
                        status = "보존" if j == g.keep_index else "삭제"
                        w.writerow([i, status, fi.name, fi.size, str(fi.path), fi.full_hash or ""])
            QMessageBox.information(self, "내보내기 완료", f"저장됨:\n{path}")
        except OSError as exc:
            QMessageBox.critical(self, "저장 실패", str(exc))
