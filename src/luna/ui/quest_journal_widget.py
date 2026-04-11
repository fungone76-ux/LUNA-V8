"""Quest Journal Widget — standalone panel showing active mission and next.

Read-only, updated each turn from NarrativeCompassData.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QWidget,
)
from PySide6.QtCore import Qt


class QuestJournalWidget(QGroupBox):
    """Mission panel: active quest title + player hint + next quest."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("MISSIONE ATTIVA", parent)
        self.setMaximumHeight(160)
        self.setMinimumHeight(100)
        self.setStyleSheet("""
            QGroupBox {
                color: #FFA500;
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 1px;
                border: 1px solid #665500;
                border-radius: 4px;
                margin-top: 6px;
                padding-top: 4px;
                background-color: #1a1600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                background-color: #1a1600;
            }
        """)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 12, 8, 6)

        # Active quest title
        self._lbl_title = QLabel("(nessuna missione attiva)")
        self._lbl_title.setStyleSheet(
            "color: #666; font-size: 11px; font-style: italic;"
        )
        self._lbl_title.setWordWrap(True)
        layout.addWidget(self._lbl_title)

        # Player hint
        self._lbl_hint = QLabel("")
        self._lbl_hint.setStyleSheet(
            "color: #4CAF50; font-size: 11px; font-style: italic; padding-left: 6px;"
        )
        self._lbl_hint.setWordWrap(True)
        layout.addWidget(self._lbl_hint)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #443300; max-height: 1px; margin: 2px 0;")
        layout.addWidget(sep)

        # Next quest row
        next_row = QWidget()
        next_layout = QHBoxLayout(next_row)
        next_layout.setContentsMargins(0, 0, 0, 0)
        next_layout.setSpacing(6)

        lbl_prefix = QLabel("PROSSIMA")
        lbl_prefix.setStyleSheet(
            "color: #665500; font-size: 9px; font-weight: bold; letter-spacing: 1px; min-width: 60px;"
        )
        next_layout.addWidget(lbl_prefix)

        self._lbl_next = QLabel("—")
        self._lbl_next.setStyleSheet("color: #887700; font-size: 10px;")
        self._lbl_next.setWordWrap(True)
        next_layout.addWidget(self._lbl_next, stretch=1)

        layout.addWidget(next_row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_quest(
        self,
        active_quest_title: str,
        active_stage_hint: str,
        next_quest_title: str,
    ) -> None:
        if active_quest_title:
            self._lbl_title.setText(f"📜 {active_quest_title}")
            self._lbl_title.setStyleSheet(
                "color: #FFD700; font-size: 11px; font-weight: bold;"
            )
            self._lbl_hint.setText(f"→ {active_stage_hint}" if active_stage_hint else "")
        else:
            self._lbl_title.setText("(nessuna missione attiva)")
            self._lbl_title.setStyleSheet(
                "color: #666; font-size: 11px; font-style: italic;"
            )
            self._lbl_hint.setText("")

        self._lbl_next.setText(next_quest_title if next_quest_title else "—")
        self._lbl_next.setStyleSheet(
            f"color: {'#AA8800' if next_quest_title else '#665500'}; font-size: 10px;"
        )
