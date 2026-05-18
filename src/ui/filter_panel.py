"""Left-side panel: scan & deletion filter options."""

from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.utils.config import Config


class FilterPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Scan filters ──────────────────────────────────────────────────
        scan_group = QGroupBox("스캔 필터")
        form = QFormLayout(scan_group)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self._min_size = QSpinBox()
        self._min_size.setRange(0, 999_999)
        self._min_size.setSuffix(" MB")
        self._min_size.setSpecialValueText("제한 없음")
        self._min_size.setToolTip("이 크기 미만의 파일은 무시합니다")
        form.addRow("최소 크기:", self._min_size)

        self._max_size = QSpinBox()
        self._max_size.setRange(0, 999_999)
        self._max_size.setSuffix(" MB")
        self._max_size.setSpecialValueText("제한 없음")
        self._max_size.setToolTip("이 크기 초과의 파일은 무시합니다")
        form.addRow("최대 크기:", self._max_size)

        self._extensions = QLineEdit()
        self._extensions.setPlaceholderText(".jpg .png .mp4  (비우면 전체)")
        self._extensions.setToolTip("공백으로 구분. 비우면 모든 확장자 검색")
        form.addRow("포함 확장자:", self._extensions)

        self._excl_ext = QLineEdit()
        self._excl_ext.setPlaceholderText(".tmp .log")
        self._excl_ext.setToolTip("공백으로 구분. 해당 확장자는 건너뜁니다")
        form.addRow("제외 확장자:", self._excl_ext)

        self._include_hidden = QCheckBox("숨김 파일 포함")
        form.addRow("", self._include_hidden)

        outer.addWidget(scan_group)

        # ── Deletion options ──────────────────────────────────────────────
        del_group = QGroupBox("삭제 옵션")
        dform = QFormLayout(del_group)
        dform.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self._use_trash = QCheckBox("휴지통으로 이동 (권장)")
        self._use_trash.setChecked(True)
        self._use_trash.setToolTip("체크 해제 시 영구 삭제 (복구 불가)")
        dform.addRow("", self._use_trash)

        self._dry_run = QCheckBox("드라이 런 — 삭제하지 않고 미리보기")
        self._dry_run.setToolTip("실제로 파일을 삭제하지 않고 결과만 확인합니다")
        dform.addRow("", self._dry_run)

        outer.addWidget(del_group)
        outer.addStretch()

    # ── Accessors ─────────────────────────────────────────────────────────

    def min_size_bytes(self) -> int:
        v = self._min_size.value()
        return v * 1_048_576 if v > 0 else 0

    def max_size_bytes(self) -> int:
        v = self._max_size.value()
        return v * 1_048_576 if v > 0 else 0

    def extensions(self) -> Optional[frozenset[str]]:
        text = self._extensions.text().strip()
        if not text:
            return None
        return frozenset(t.strip().lower() for t in text.split())

    def excluded_extensions(self) -> frozenset[str]:
        text = self._excl_ext.text().strip()
        if not text:
            return frozenset()
        return frozenset(t.strip().lower() for t in text.split())

    def include_hidden(self) -> bool:
        return self._include_hidden.isChecked()

    def use_trash(self) -> bool:
        return self._use_trash.isChecked()

    def dry_run(self) -> bool:
        return self._dry_run.isChecked()

    # ── Config persistence ────────────────────────────────────────────────

    def apply_config(self, config: Config) -> None:
        self._min_size.setValue(config.get("min_size_bytes", 0) // 1_048_576)
        self._max_size.setValue(config.get("max_size_bytes", 0) // 1_048_576)
        self._extensions.setText(" ".join(config.get("extensions", [])))
        self._excl_ext.setText(" ".join(config.get("excluded_extensions", [])))
        self._include_hidden.setChecked(config.get("include_hidden", False))
        self._use_trash.setChecked(config.get("use_trash", True))
        self._dry_run.setChecked(config.get("dry_run", False))

    def save_to_config(self, config: Config) -> None:
        config.set("min_size_bytes", self.min_size_bytes())
        config.set("max_size_bytes", self.max_size_bytes())
        config.set("extensions", list(self.extensions() or []))
        config.set("excluded_extensions", list(self.excluded_extensions()))
        config.set("include_hidden", self.include_hidden())
        config.set("use_trash", self.use_trash())
        config.set("dry_run", self.dry_run())
