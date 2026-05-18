"""Center panel: tree view of duplicate groups.

Each top-level item represents one duplicate group.
Each child item represents a file in that group, with a checkbox indicating
whether it will be deleted. The "keep" file has no checkbox.

Context menu (right-click on a file row):
  - Switch keep ← makes this file the one that survives
  - Open in Explorer
"""

import datetime
import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.models.file_info import DuplicateGroup, FileInfo
from src.models.file_info import fmt_size


# Column indices
_C_NAME   = 0
_C_SIZE   = 1
_C_DATE   = 2
_C_PATH   = 3
_C_STATUS = 4

_ROLE = Qt.ItemDataRole.UserRole

_KEEP_COLOR   = QColor("#1b5e20")   # dark green
_DELETE_COLOR = QColor("#b71c1c")   # dark red
_GROUP_BG     = QColor("#e8f0fe")   # light blue


def _fmt_date(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


class ResultPanel(QWidget):
    """Emits `selection_changed(count, bytes)` whenever the deletion selection changes."""

    selection_changed = pyqtSignal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._groups: list[DuplicateGroup] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Summary bar
        top_row = QHBoxLayout()
        self._lbl_summary = QLabel("스캔 결과가 없습니다")
        top_row.addWidget(self._lbl_summary, stretch=1)

        self._btn_check_all   = QPushButton("전체 선택")
        self._btn_uncheck_all = QPushButton("전체 해제")
        self._btn_check_all.clicked.connect(self._check_all)
        self._btn_uncheck_all.clicked.connect(self._uncheck_all)
        top_row.addWidget(self._btn_check_all)
        top_row.addWidget(self._btn_uncheck_all)
        layout.addLayout(top_row)

        # Tree
        self._tree = QTreeWidget()
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels(["파일명", "크기", "수정일", "경로", "상태"])
        hdr = self._tree.header()
        hdr.setSectionResizeMode(_C_PATH,   QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_C_NAME,   QHeaderView.ResizeMode.Interactive)
        hdr.resizeSection(_C_NAME,   200)
        hdr.resizeSection(_C_SIZE,    80)
        hdr.resizeSection(_C_DATE,   130)
        hdr.resizeSection(_C_STATUS,  60)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        self._tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._tree)

    # ── public API ────────────────────────────────────────────────────────

    def load_groups(self, groups: list[DuplicateGroup]) -> None:
        self._groups = groups
        self._tree.blockSignals(True)
        self._tree.clear()

        total_groups = len(groups)
        total_files  = sum(g.file_count for g in groups)
        total_waste  = sum(g.wasted_size for g in groups)
        self._lbl_summary.setText(
            f"중복 그룹: {total_groups:,}개  |  "
            f"중복 파일: {total_files:,}개  |  "
            f"확보 가능: {fmt_size(total_waste)}"
        )

        bold = QFont()
        bold.setBold(True)

        for g_idx, group in enumerate(groups):
            g_item = QTreeWidgetItem(self._tree)
            g_item.setText(
                _C_NAME,
                f"[그룹 {g_idx + 1}]  파일 {group.file_count}개"
                f"  —  절약 가능: {group.wasted_size_str}",
            )
            g_item.setData(_C_NAME, _ROLE, ("group", g_idx))
            g_item.setFont(_C_NAME, bold)
            for col in range(5):
                g_item.setBackground(col, QBrush(_GROUP_BG))
            g_item.setExpanded(True)
            g_item.setFlags(g_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)

            for f_idx, fi in enumerate(group.files):
                self._add_file_item(g_item, g_idx, f_idx, fi, group.keep_index)

        self._tree.blockSignals(False)
        self._emit_selection()

    def get_files_to_delete(self) -> list[FileInfo]:
        result: list[FileInfo] = []
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            g_item = root.child(i)
            for j in range(g_item.childCount()):
                child = g_item.child(j)
                if child.checkState(_C_NAME) == Qt.CheckState.Checked:
                    data = child.data(_C_NAME, _ROLE)
                    if data and data[0] == "file":
                        g_idx, f_idx = data[1], data[2]
                        result.append(self._groups[g_idx].files[f_idx])
        return result

    def clear(self) -> None:
        self._groups = []
        self._tree.clear()
        self._lbl_summary.setText("스캔 결과가 없습니다")
        self.selection_changed.emit(0, 0)

    # ── internals ─────────────────────────────────────────────────────────

    def _add_file_item(
        self,
        parent: QTreeWidgetItem,
        g_idx: int,
        f_idx: int,
        fi: FileInfo,
        keep_index: int,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent)
        item.setText(_C_NAME,   fi.name)
        item.setText(_C_SIZE,   fi.size_str)
        item.setText(_C_DATE,   _fmt_date(fi.mtime))
        item.setText(_C_PATH,   str(fi.path.parent))
        item.setData(_C_NAME,   _ROLE, ("file", g_idx, f_idx))

        if f_idx == keep_index:
            item.setText(_C_STATUS, "보존")
            item.setForeground(_C_STATUS, QBrush(_KEEP_COLOR))
            # No checkbox for the keep file
        else:
            item.setText(_C_STATUS, "삭제")
            item.setForeground(_C_STATUS, QBrush(_DELETE_COLOR))
            item.setCheckState(_C_NAME, Qt.CheckState.Checked)

        return item

    def _on_item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        if col != _C_NAME:
            return
        data = item.data(_C_NAME, _ROLE)
        if data and data[0] == "file":
            self._emit_selection()

    def _emit_selection(self) -> None:
        files = self.get_files_to_delete()
        self.selection_changed.emit(len(files), sum(f.size for f in files))

    # ── bulk check/uncheck ────────────────────────────────────────────────

    def _set_all_checked(self, state: Qt.CheckState) -> None:
        self._tree.blockSignals(True)
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            g_item = root.child(i)
            for j in range(g_item.childCount()):
                child = g_item.child(j)
                # Only items that have a checkbox (delete candidates)
                if child.data(_C_NAME, _ROLE) and child.data(_C_NAME, _ROLE)[0] == "file":
                    # Keep file has no check state — skip it
                    flags = child.flags()
                    if flags & Qt.ItemFlag.ItemIsUserCheckable:
                        child.setCheckState(_C_NAME, state)
        self._tree.blockSignals(False)
        self._emit_selection()

    def _check_all(self) -> None:
        self._set_all_checked(Qt.CheckState.Checked)

    def _uncheck_all(self) -> None:
        self._set_all_checked(Qt.CheckState.Unchecked)

    # ── context menu ──────────────────────────────────────────────────────

    def _context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if not item:
            return
        data = item.data(_C_NAME, _ROLE)
        if not data or data[0] != "file":
            return
        g_idx, f_idx = data[1], data[2]
        group = self._groups[g_idx]

        menu = QMenu(self)
        act_keep  = menu.addAction("이 파일을 보존으로 변경")
        act_open  = menu.addAction("탐색기에서 열기")
        action = menu.exec(self._tree.viewport().mapToGlobal(pos))

        if action == act_keep and f_idx != group.keep_index:
            group.keep_index = f_idx
            self.load_groups(self._groups)
        elif action == act_open:
            fi = group.files[f_idx]
            subprocess.Popen(f'explorer /select,"{fi.path}"')
