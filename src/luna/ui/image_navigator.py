"""Luna RPG v6 - Image Navigator Widget.

Wraps ImageDisplayWidget adding ← → arrows to browse
the image history generated during the session.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)


class ImageNavigator(QWidget):
    """Image display with prev/next navigation arrows.

    Keeps an internal history of image paths and lets the
    player browse backwards and forward without leaving the
    current game state.

    Usage in main_window.py:
        # Replace ImageDisplayWidget with ImageNavigator
        from luna.ui.image_navigator import ImageNavigator
        self.image_display = ImageNavigator()
        center_layout.addWidget(self.image_display)

    The existing  self.image_display.set_image(path)  calls
    keep working unchanged — they add to history automatically.
    """

    image_changed = Signal(str)   # emitted when displayed image changes

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._history: List[str] = []   # all image paths seen
        self._index:   int       = -1   # current position in history

        self._build_ui()

    # =========================================================================
    # UI
    # =========================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        # ── Image viewer ────────────────────────────────────────────────────
        from luna.ui.image_viewer import ImageViewer
        self.image_viewer = ImageViewer()
        root.addWidget(self.image_viewer)

        # ── Navigation bar ──────────────────────────────────────────────────
        nav = QHBoxLayout()
        nav.setContentsMargins(4, 2, 4, 2)

        # Prev button
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedWidth(36)
        self.btn_prev.setFixedHeight(28)
        self.btn_prev.setToolTip("Immagine precedente")
        self.btn_prev.setEnabled(False)
        self.btn_prev.clicked.connect(self._go_prev)
        self.btn_prev.setStyleSheet(self._btn_style())
        nav.addWidget(self.btn_prev)

        # Counter label  e.g. "3 / 7"
        self.lbl_counter = QLabel("—")
        self.lbl_counter.setAlignment(Qt.AlignCenter)
        self.lbl_counter.setStyleSheet("color: #888; font-size: 10px;")
        nav.addWidget(self.lbl_counter, 1)

        # Next button
        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedWidth(36)
        self.btn_next.setFixedHeight(28)
        self.btn_next.setToolTip("Immagine successiva")
        self.btn_next.setEnabled(False)
        self.btn_next.clicked.connect(self._go_next)
        self.btn_next.setStyleSheet(self._btn_style())
        nav.addWidget(self.btn_next)

        root.addLayout(nav)

    @staticmethod
    def _btn_style() -> str:
        return """
            QPushButton {
                background-color: #2a2a2a;
                color: #ccc;
                border: 1px solid #444;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton:pressed { background-color: #1a1a1a; }
            QPushButton:disabled { color: #555; border-color: #333; }
        """

    # =========================================================================
    # Public API  (drop-in replacement for ImageDisplayWidget)
    # =========================================================================

    def set_image(self, image_path: str) -> None:
        """Add image to history and display it.

        This is the same signature as ImageDisplayWidget.set_image()
        so existing calls in main_window.py need no changes.
        """
        if not image_path:
            return
        p = str(Path(image_path).resolve())

        # Avoid duplicates of the very last entry
        if self._history and self._history[-1] == p:
            return

        # If we navigated back and now a new image arrives,
        # discard the "future" entries (same as most video players)
        if self._index < len(self._history) - 1:
            self._history = self._history[: self._index + 1]

        self._history.append(p)
        self._index = len(self._history) - 1

        self._show_current()

    def clear(self) -> None:
        """Clear history and display."""
        self._history.clear()
        self._index = -1
        self.image_viewer.clear()
        self._refresh_controls()

    # =========================================================================
    # Navigation
    # =========================================================================

    def _go_prev(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._show_current()

    def _go_next(self) -> None:
        if self._index < len(self._history) - 1:
            self._index += 1
            self._show_current()

    def _show_current(self) -> None:
        if 0 <= self._index < len(self._history):
            path = self._history[self._index]
            self.image_viewer.set_image(path)
            self.image_changed.emit(path)
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        total = len(self._history)
        pos   = self._index + 1 if self._index >= 0 else 0

        self.lbl_counter.setText(f"{pos} / {total}" if total else "—")
        self.btn_prev.setEnabled(self._index > 0)
        self.btn_next.setEnabled(self._index < total - 1)

    # =========================================================================
    # Convenience
    # =========================================================================

    @property
    def current_image_path(self) -> Optional[str]:
        """Return path of the currently displayed image."""
        if 0 <= self._index < len(self._history):
            return self._history[self._index]
        return None

    @property
    def history(self) -> List[str]:
        return list(self._history)
