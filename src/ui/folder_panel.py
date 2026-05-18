"""Left-side panel: manage the list of root folders to scan."""

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class FolderPanel(QWidget):
    """Emits `folders_changed` whenever the folder list is modified."""

    folders_changed = pyqtSignal(list)   # list[Path]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("검색 폴더")
        inner = QVBoxLayout(group)

        self._list = QListWidget()
        self._list.setMinimumHeight(130)
        self._list.setToolTip("검색할 폴더 목록입니다.\n폴더를 끌어다 놓거나 [+ 추가] 버튼을 사용하세요.")
        inner.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("+ 추가")
        self._btn_add.setToolTip("새 폴더 추가")
        self._btn_add.clicked.connect(self._add_folder)

        self._btn_remove = QPushButton("- 제거")
        self._btn_remove.setToolTip("선택한 폴더 제거")
        self._btn_remove.clicked.connect(self._remove_selected)

        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_remove)
        btn_row.addStretch()
        inner.addLayout(btn_row)

        outer.addWidget(group)

    # ── public API ────────────────────────────────────────────────────────

    def folders(self) -> list[Path]:
        return [Path(self._list.item(i).text()) for i in range(self._list.count())]

    def set_folders(self, paths: list[str]) -> None:
        self._list.clear()
        for p in paths:
            self._list.addItem(QListWidgetItem(p))

    # ── slots ─────────────────────────────────────────────────────────────

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "검색할 폴더 선택")
        if not folder:
            return
        existing = [self._list.item(i).text() for i in range(self._list.count())]
        if folder not in existing:
            self._list.addItem(QListWidgetItem(folder))
            self.folders_changed.emit(self.folders())

    def _remove_selected(self) -> None:
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))
        self.folders_changed.emit(self.folders())
