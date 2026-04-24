"""Quest Journal Widget — dynamic HUD showing mission, event, or macro-event state.

Priority (highest first): MACRO_EVENT > EVENT > MISSION
State dict: {type, title, description, objective, status}
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

_STYLES = {
    "mission": {
        "border": "#665500",
        "bg": "#1a1600",
        "title_color": "#FFA500",
        "icon": "🎯",
        "label": "MISSIONE ATTIVA",
        "title_text_color": "#FFD700",
        "hint_color": "#4CAF50",
    },
    "event": {
        "border": "#004466",
        "bg": "#001a26",
        "title_color": "#00BFFF",
        "icon": "⚡",
        "label": "EVENTO SPECIALE",
        "title_text_color": "#87CEEB",
        "hint_color": "#4DD0E1",
    },
    "macro_event": {
        "border": "#660044",
        "bg": "#1a0011",
        "title_color": "#FF69B4",
        "icon": "🎭",
        "label": "EVENTO MACRO",
        "title_text_color": "#FFB6C1",
        "hint_color": "#FF69B4",
    },
}

_POPUP_DURATION_MS = 3000


class QuestJournalWidget(QGroupBox):
    """Dynamic HUD: shows mission / event / macro_event with priority logic."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("MISSIONE ATTIVA", parent)
        self.setMaximumHeight(160)
        self.setMinimumHeight(100)
        self._current_state: Optional[Dict[str, Any]] = None
        self._popup_timer = QTimer(self)
        self._popup_timer.setSingleShot(True)
        self._popup_timer.timeout.connect(self._hide_popup)
        self._setup_ui()
        self._apply_style("mission")

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 12, 8, 6)

        # Active title
        self._lbl_title = QLabel("(nessuna missione attiva)")
        self._lbl_title.setStyleSheet(
            "color: #666; font-size: 11px; font-style: italic;"
        )
        self._lbl_title.setWordWrap(True)
        layout.addWidget(self._lbl_title)

        # Hint / description
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
        self._sep = sep

        # Next-quest row (mission mode only)
        next_row = QWidget()
        next_layout = QHBoxLayout(next_row)
        next_layout.setContentsMargins(0, 0, 0, 0)
        next_layout.setSpacing(6)

        self._lbl_next_prefix = QLabel("PROSSIMA")
        self._lbl_next_prefix.setStyleSheet(
            "color: #665500; font-size: 9px; font-weight: bold; letter-spacing: 1px; min-width: 60px;"
        )
        next_layout.addWidget(self._lbl_next_prefix)

        self._lbl_next = QLabel("—")
        self._lbl_next.setStyleSheet("color: #887700; font-size: 10px;")
        self._lbl_next.setWordWrap(True)
        next_layout.addWidget(self._lbl_next, stretch=1)

        layout.addWidget(next_row)
        self._next_row = next_row

        # Popup notification (hidden by default)
        self._popup = QLabel("")
        self._popup.setAlignment(Qt.AlignCenter)
        self._popup.setStyleSheet(
            "background-color: #222; color: #FFD700; font-size: 10px; "
            "font-weight: bold; border: 1px solid #555; border-radius: 3px; padding: 2px 6px;"
        )
        self._popup.setWordWrap(True)
        self._popup.hide()
        layout.addWidget(self._popup)

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------

    def _apply_style(self, state_type: str) -> None:
        s = _STYLES.get(state_type, _STYLES["mission"])
        self.setTitle(s["label"])
        self.setStyleSheet(f"""
            QGroupBox {{
                color: {s['title_color']};
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 1px;
                border: 1px solid {s['border']};
                border-radius: 4px;
                margin-top: 6px;
                padding-top: 4px;
                background-color: {s['bg']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                background-color: {s['bg']};
            }}
        """)
        self._lbl_hint.setStyleSheet(
            f"color: {s['hint_color']}; font-size: 11px; font-style: italic; padding-left: 6px;"
        )

    # ------------------------------------------------------------------
    # Public API — original signature preserved (backward compat)
    # ------------------------------------------------------------------

    def update_quest(
        self,
        active_quest_title: str,
        active_stage_hint: str,
        next_quest_title: str,
    ) -> None:
        """Update from quest engine data (mission state)."""
        new_state: Dict[str, Any] = {
            "type": "mission",
            "title": active_quest_title,
            "description": active_stage_hint,
            "next": next_quest_title,
        }
        self._apply_state(new_state)

    def update_hud(self, state: Optional[Dict[str, Any]]) -> None:
        """Update from any state dict: {type, title, description, objective, status, next?}.

        Priority: macro_event > event > mission.
        Pass None to clear.
        """
        if state is None:
            self._apply_state(None)
            return

        current_type = (self._current_state or {}).get("type", "mission")
        new_type = state.get("type", "mission")

        priority = {"macro_event": 3, "event": 2, "mission": 1}
        if priority.get(new_type, 1) >= priority.get(current_type, 1):
            self._apply_state(state)

    # ------------------------------------------------------------------
    # Internal state application
    # ------------------------------------------------------------------

    def _apply_state(self, state: Optional[Dict[str, Any]]) -> None:
        prev_title = (self._current_state or {}).get("title", "")
        self._current_state = state

        if not state or not state.get("title"):
            self._apply_style("mission")
            self._lbl_title.setText("(nessuna missione attiva)")
            self._lbl_title.setStyleSheet(
                "color: #666; font-size: 11px; font-style: italic;"
            )
            self._lbl_hint.setText("")
            self._lbl_next.setText("—")
            self._next_row.setVisible(True)
            return

        state_type = state.get("type", "mission")
        s = _STYLES.get(state_type, _STYLES["mission"])
        self._apply_style(state_type)

        title = state.get("title", "")
        description = state.get("description", "") or state.get("objective", "")
        next_q = state.get("next", "")

        self._lbl_title.setText(f"{s['icon']} {title}")
        self._lbl_title.setStyleSheet(
            f"color: {s['title_text_color']}; font-size: 11px; font-weight: bold;"
        )
        self._lbl_hint.setText(f"→ {description}" if description else "")

        is_mission = state_type == "mission"
        self._next_row.setVisible(is_mission)
        if is_mission:
            self._lbl_next.setText(next_q if next_q else "—")
            self._lbl_next.setStyleSheet(
                f"color: {'#AA8800' if next_q else '#665500'}; font-size: 10px;"
            )

        # Popup notification when title changes
        if title and title != prev_title:
            self._show_popup(f"{s['icon']} {state_type.replace('_', ' ').upper()}: {title}")

    def _show_popup(self, text: str) -> None:
        self._popup.setText(text)
        self._popup.show()
        self._popup_timer.start(_POPUP_DURATION_MS)

    def _hide_popup(self) -> None:
        self._popup.hide()
