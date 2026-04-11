"""Luna RPG — Poker Window.

Finestra dedicata al mini-gioco poker con:
  1. Tavolo da gioco  (pannello principale, immagine aggiornata ogni turno)
  2. Anteprima strip  (ultima immagine generata, sostituita ad ogni strip event)
  3. Chat log         (stile identico alla story log del gioco principale)
  4. Barra di input   (comandi + pulsanti rapidi)
"""
from __future__ import annotations

import logging
import re
from typing import Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices

from qasync import asyncSlot

if TYPE_CHECKING:
    from luna.core.engine import GameEngine

logger = logging.getLogger(__name__)

# ─── Palette ──────────────────────────────────────────────────────────────────
_BG            = "#1a1a1a"
_PANEL_BG      = "#222222"
_FELT_GREEN    = "#1b4d2e"
_GOLD          = "#c8a84b"
_BORDER        = "#444444"
_TEXT_MAIN     = "#dddddd"
_TEXT_DIM      = "#888888"

# Chat semantic colors (match story log palette)
_C_USER        = "#4CAF50"   # player actions — green
_C_PLAYER_ACT  = "#81C784"   # "Hai visto / fatto fold" — light green
_C_NPC_ACTION  = "#ffb74d"   # NPC poker action — amber
_C_NPC_SPEECH  = "#4FC3F7"   # NPC dialogue / strip speech — cyan
_C_GAME_EVENT  = "#c8a84b"   # showdown / hand header / wins — gold
_C_STRIP       = "#E91E63"   # strip events — pink/magenta
_C_SYSTEM      = "#888888"   # hints / stack info — grey
_C_DIALOGUE    = "#c8b4f0"   # /d channel replies — lavender
_C_ERROR       = "#ff6b6b"   # error messages — red

# Button styles
_STYLE_BTN_PRIMARY = f"""
    QPushButton {{
        background-color: {_GOLD}; color: #111;
        border: none; border-radius: 4px;
        font-size: 14px; font-weight: bold;
        padding: 8px 20px; min-height: 38px;
    }}
    QPushButton:hover  {{ background-color: #d9b95a; }}
    QPushButton:pressed {{ background-color: #b8942e; }}
    QPushButton:disabled {{ background-color: #555; color: #888; }}
"""
_STYLE_BTN_EXIT = f"""
    QPushButton {{
        background-color: #6b2020; color: #eee;
        border: none; border-radius: 4px;
        font-size: 13px; padding: 8px 16px; min-height: 38px;
    }}
    QPushButton:hover {{ background-color: #8b2020; }}
"""
_STYLE_BTN_QUICK = f"""
    QPushButton {{
        background-color: #2e2e2e; color: {_TEXT_MAIN};
        border: 1px solid {_BORDER}; border-radius: 4px;
        font-size: 12px; padding: 6px 10px; min-height: 30px;
    }}
    QPushButton:hover {{ background-color: #3a3a3a; }}
    QPushButton:disabled {{ color: {_TEXT_DIM}; border-color: #333; }}
"""
_STYLE_INPUT = f"""
    QLineEdit {{
        background-color: {_PANEL_BG}; color: {_TEXT_MAIN};
        border: 1px solid {_BORDER}; border-radius: 4px;
        font-size: 14px; padding: 8px 12px; min-height: 38px;
    }}
    QLineEdit:focus {{ border: 1px solid {_GOLD}; }}
"""
_STYLE_SECTION = f"""
    QLabel {{
        color: {_GOLD}; font-size: 11px; font-weight: bold;
        letter-spacing: 2px; padding: 4px 0px;
    }}
"""
_STYLE_HINT = f"QLabel {{ color: {_TEXT_DIM}; font-size: 11px; padding: 2px 4px; }}"


# ─── Full-image popup ─────────────────────────────────────────────────────────

class _FullImagePopup(QDialog):
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Strip Preview")
        self.setStyleSheet(f"QDialog {{ background: {_BG}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lbl = QLabel()
        px = QPixmap(image_path)
        if not px.isNull():
            from PySide6.QtCore import QSize
            screen = self.screen().availableSize() if self.screen() else QSize(1920, 1080)
            scaled = px.scaled(
                int(screen.width() * 0.75), int(screen.height() * 0.85),
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            lbl.setPixmap(scaled)
        lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl)
        btn = QPushButton("Chiudi")
        btn.setStyleSheet(_STYLE_BTN_PRIMARY)
        btn.clicked.connect(self.close)
        lay.addWidget(btn, alignment=Qt.AlignCenter)
        self.adjustSize()


# ─── Main Poker Window ────────────────────────────────────────────────────────

class PokerWindow(QDialog):
    """Dedicated poker mini-game window."""

    closed = Signal()

    def __init__(self, engine: "GameEngine", parent=None):
        super().__init__(parent, Qt.Window)
        self.engine = engine
        self._known_strip_images: list[str] = []
        self._known_strip_videos: list[str] = []
        self._strip_preview_path: Optional[str] = None
        self._chat_html = ""             # accumulated chat HTML

        self.setWindowTitle("LUNA RPG — Strip Poker")
        self.setMinimumSize(1280, 800)
        self.setStyleSheet(f"""
            QDialog   {{ background-color: {_BG}; color: {_TEXT_MAIN}; }}
            QWidget   {{ background-color: {_BG}; color: {_TEXT_MAIN}; }}
            QSplitter::handle {{ background: {_BORDER}; }}
        """)

        self._build_ui()
        self._post_startup_hint()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addWidget(self._make_title_bar())

        v_split = QSplitter(Qt.Vertical)
        v_split.setHandleWidth(6)

        h_split = QSplitter(Qt.Horizontal)
        h_split.setHandleWidth(6)
        h_split.addWidget(self._make_table_panel())
        h_split.addWidget(self._make_strip_panel())
        h_split.setStretchFactor(0, 3)
        h_split.setStretchFactor(1, 1)

        v_split.addWidget(h_split)
        v_split.addWidget(self._make_chat_panel())
        v_split.setStretchFactor(0, 3)
        v_split.setStretchFactor(1, 2)

        root.addWidget(v_split, stretch=1)
        root.addWidget(self._make_input_bar())

    def _make_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"QWidget {{ background: {_FELT_GREEN}; border-radius: 4px; }}")
        bar.setFixedHeight(42)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        title = QLabel("♠  STRIP POKER — Texas Hold'em  ♠")
        title.setStyleSheet(f"color:{_GOLD}; font-size:16px; font-weight:bold; background:transparent;")
        lay.addWidget(title)
        lay.addStretch()
        self._lbl_status = QLabel("In gioco")
        self._lbl_status.setStyleSheet(f"color:{_TEXT_DIM}; font-size:12px; background:transparent;")
        lay.addWidget(self._lbl_status)
        return bar

    def _make_table_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(4)
        lbl = QLabel("TAVOLO DA GIOCO")
        lbl.setStyleSheet(_STYLE_SECTION)
        lay.addWidget(lbl)
        self._table_display = QLabel()
        self._table_display.setAlignment(Qt.AlignCenter)
        self._table_display.setStyleSheet(f"""
            QLabel {{
                background-color: {_FELT_GREEN};
                border: 2px solid {_BORDER};
                border-radius: 6px;
            }}
        """)
        self._table_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._table_display.setMinimumSize(600, 350)
        lay.addWidget(self._table_display, stretch=1)
        return panel

    def _make_strip_panel(self) -> QWidget:
        """Right panel: shows ONLY the latest strip image (replaces on update)."""
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(4, 0, 0, 0)
        lay.setSpacing(4)

        sec = QLabel("ANTEPRIMA STRIP")
        sec.setStyleSheet(_STYLE_SECTION)
        lay.addWidget(sec)

        # Empty placeholder
        self._strip_empty_lbl = QLabel("Nessuna immagine ancora.\nVinci mani per sbloccarla! 🃏")
        self._strip_empty_lbl.setAlignment(Qt.AlignCenter)
        self._strip_empty_lbl.setWordWrap(True)
        self._strip_empty_lbl.setStyleSheet(f"color:{_TEXT_DIM}; font-size:13px;")
        lay.addWidget(self._strip_empty_lbl, stretch=1)

        # Live preview
        self._strip_lbl = QLabel()
        self._strip_lbl.setAlignment(Qt.AlignCenter)
        self._strip_lbl.setStyleSheet(f"""
            QLabel {{
                background:#111; border:1px solid {_BORDER}; border-radius:4px;
            }}
            QLabel:hover {{ border:1px solid {_GOLD}; }}
        """)
        self._strip_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._strip_lbl.setCursor(Qt.PointingHandCursor)
        self._strip_lbl.setMinimumHeight(80)
        self._strip_lbl.hide()
        lay.addWidget(self._strip_lbl, stretch=1)

        self._strip_cap = QLabel("")
        self._strip_cap.setAlignment(Qt.AlignCenter)
        self._strip_cap.setStyleSheet(f"color:{_GOLD}; font-size:11px; font-weight:bold;")
        self._strip_cap.hide()
        lay.addWidget(self._strip_cap)

        # Store original pixmap for rescaling
        self._strip_px_orig: Optional[QPixmap] = None
        self._strip_lbl.mousePressEvent = self._on_strip_click

        return panel

    def _make_chat_panel(self) -> QWidget:
        """Chat panel styled identically to the main game story log."""
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)

        sec = QLabel("CHAT")
        sec.setStyleSheet(_STYLE_SECTION)
        lay.addWidget(sec)

        self._chat_scroll = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._chat_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._chat_scroll.setStyleSheet(f"""
            QScrollArea {{ background:{_PANEL_BG}; border:1px solid {_BORDER}; border-radius:4px; }}
        """)

        self._chat_lbl = QLabel("")
        self._chat_lbl.setWordWrap(True)
        self._chat_lbl.setTextFormat(Qt.RichText)
        self._chat_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._chat_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._chat_lbl.setStyleSheet(f"""
            QLabel {{
                color: {_TEXT_MAIN};
                font-size: 15px;
                line-height: 1.6;
                padding: 10px;
                background: {_PANEL_BG};
            }}
        """)
        self._chat_scroll.setWidget(self._chat_lbl)
        lay.addWidget(self._chat_scroll, stretch=1)
        return panel

    def _make_input_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(96)
        bar.setStyleSheet(f"QWidget {{ background:{_PANEL_BG}; border-top:1px solid {_BORDER}; }}")
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # Quick action buttons
        quick = QHBoxLayout()
        quick.setSpacing(6)
        self._action_buttons: dict[str, QPushButton] = {}
        for label, key in [
            ("Check", "check"), ("Vedo", "vedo"), ("Fold", "fold"),
            ("Punta BB", "bet_bb"), ("Rilancio Min", "raise_min"), ("All-in", "all-in"),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(_STYLE_BTN_QUICK)
            btn.clicked.connect(lambda _, k=key: self._on_quick_action(k))
            self._action_buttons[key] = btn
            quick.addWidget(btn)
        quick.addStretch()
        lay.addLayout(quick)

        # Input row
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        self._lbl_hint = QLabel(
            "vedo | fold | check | punto X | rilancio X | all-in | esci"
            "   ·   dialogo: /d messaggio   /d @Luna ciao"
        )
        self._lbl_hint.setStyleSheet(_STYLE_HINT)
        bottom.addWidget(self._lbl_hint)
        bottom.addStretch()

        self._txt_input = QLineEdit()
        self._txt_input.setPlaceholderText("Azione poker o /d messaggio...")
        self._txt_input.setStyleSheet(_STYLE_INPUT)
        self._txt_input.setMinimumWidth(380)
        self._txt_input.returnPressed.connect(self._on_send)
        bottom.addWidget(self._txt_input, stretch=1)

        self._btn_send = QPushButton("INVIA  ▶")
        self._btn_send.setStyleSheet(_STYLE_BTN_PRIMARY)
        self._btn_send.clicked.connect(self._on_send)
        bottom.addWidget(self._btn_send)

        self._btn_exit = QPushButton("✕  Esci dal Poker")
        self._btn_exit.setStyleSheet(_STYLE_BTN_EXIT)
        self._btn_exit.clicked.connect(self._on_exit)
        bottom.addWidget(self._btn_exit)

        lay.addLayout(bottom)
        return bar

    # ── Startup hint ──────────────────────────────────────────────────────────

    def _post_startup_hint(self) -> None:
        self._append_system(
            "Benvenuto al tavolo! Usa i pulsanti rapidi o scrivi nella barra in basso. "
            "Dialogo con NPC: /d messaggio  oppure  /d @Luna come stai?"
        )

    # ── Quick actions ─────────────────────────────────────────────────────────

    def _on_quick_action(self, action: str) -> None:
        cmd = self._build_quick_command(action)
        if not cmd:
            self._append_system("Azione non disponibile in questo momento.")
            return
        self._txt_input.setText(cmd)
        self._on_send()

    def _build_quick_command(self, action: str) -> Optional[str]:
        if action in ("check", "vedo", "fold", "all-in"):
            return action
        gs = self.engine.get_game_state()
        poker = gs.flags.get("poker_game", {})
        if not isinstance(poker, dict):
            return None
        bb  = int(poker.get("big_blind", 0) or 0)
        cb  = int(poker.get("current_bet", 0) or 0)
        mrs = int(poker.get("min_raise_size", 0) or 0)
        if action == "bet_bb" and bb > 0:
            return f"punto {bb}"
        if action == "raise_min":
            target = cb + max(mrs, bb)
            return f"rilancio {target}" if target > 0 else None
        return None

    def _refresh_action_buttons(self) -> None:
        gs = self.engine.get_game_state()
        poker = gs.flags.get("poker_game", {})
        legal = poker.get("legal_actions", {}) if isinstance(poker, dict) else {}
        mapping = {
            "check":    bool(legal.get("check")),
            "vedo":     bool(legal.get("call")),
            "fold":     bool(legal.get("fold")),
            "bet_bb":   bool(legal.get("bet")),
            "raise_min":bool(legal.get("raise")),
            "all-in":   bool(legal.get("allin")),
        }
        for key, btn in self._action_buttons.items():
            btn.setEnabled(mapping.get(key, True))

    # ── Send / Exit ───────────────────────────────────────────────────────────

    @asyncSlot()
    async def _on_send(self) -> None:
        text = self._txt_input.text().strip()
        if not text:
            return
        self._ensure_foreground()
        self._txt_input.clear()
        self._set_input_enabled(False)
        self._lbl_status.setText("Elaborazione...")
        self._append_user(text)
        try:
            result = await self.engine.process_turn(text)
            self._apply_result(result)
            self._ensure_foreground()
            gs = self.engine.get_game_state()
            if not gs.flags.get("poker_active"):
                self._append_system("Partita terminata.")
                self._btn_exit.setText("Chiudi")
        except Exception as exc:
            logger.error("[PokerWindow] Turn error: %s", exc)
            self._append_error(f"Errore: {exc}")
        finally:
            self._set_input_enabled(True)
            self._lbl_status.setText("In gioco")
            self._txt_input.setFocus()

    @asyncSlot()
    async def _on_exit(self) -> None:
        gs = self.engine.get_game_state()
        if gs.flags.get("poker_active"):
            self._ensure_foreground()
            self._set_input_enabled(False)
            self._append_user("esci")
            try:
                result = await self.engine.process_turn("esci")
                self._apply_result(result)
            except Exception as exc:
                logger.error("[PokerWindow] Exit error: %s", exc)
            finally:
                self._set_input_enabled(True)
        self.close()

    # ── Result application ────────────────────────────────────────────────────

    def _apply_result(self, result) -> None:
        if result.image_path:
            self._set_table_image(result.image_path)
        if result.text:
            self._append_npc(result.text)
        try:
            gs = self.engine.get_game_state()
            # Strip images — show only the latest
            for entry in gs.flags.get("poker_strip_images", []):
                path = entry.get("path", "") if isinstance(entry, dict) else str(entry)
                npc  = entry.get("npc_name", "NPC") if isinstance(entry, dict) else "NPC"
                lvl  = entry.get("level", 1)  if isinstance(entry, dict) else 1
                if path and path not in self._known_strip_images:
                    self._known_strip_images.append(path)
                    self._set_strip_preview(path, npc, lvl)
            # Strip videos — open-clip button added below preview
            for entry in gs.flags.get("poker_strip_videos", []):
                if not isinstance(entry, dict):
                    continue
                vpath = entry.get("path", "")
                if vpath and vpath not in self._known_strip_videos:
                    self._known_strip_videos.append(vpath)
                    self._add_video_button(vpath, entry.get("npc_name", "NPC"), entry.get("level", 1))
        except Exception as exc:
            logger.debug("[PokerWindow] Gallery update error: %s", exc)
        self._refresh_action_buttons()

    # ── Table image ───────────────────────────────────────────────────────────

    def _set_table_image(self, path: str) -> None:
        self._table_px_orig = QPixmap(path)
        self._rescale_table()

    def _rescale_table(self) -> None:
        if not hasattr(self, "_table_px_orig") or self._table_px_orig.isNull():
            return
        lbl = self._table_display
        scaled = self._table_px_orig.scaled(
            lbl.width(), lbl.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        lbl.setPixmap(scaled)

    # ── Strip preview (single latest image) ───────────────────────────────────

    def _set_strip_preview(self, path: str, npc_name: str, level: int) -> None:
        """Replace strip preview with the latest image."""
        self._strip_preview_path = path
        self._strip_px_orig = QPixmap(path)
        if self._strip_px_orig.isNull():
            return
        self._strip_empty_lbl.hide()
        self._strip_lbl.show()
        self._strip_cap.setText(f"{npc_name}  —  Livello {level}/5")
        self._strip_cap.show()
        self._rescale_strip()

    def _rescale_strip(self) -> None:
        if not self._strip_px_orig or self._strip_px_orig.isNull():
            return
        lbl = self._strip_lbl
        w, h = max(lbl.width(), 100), max(lbl.height(), 100)
        scaled = self._strip_px_orig.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        lbl.setPixmap(scaled)

    def _on_strip_click(self, event) -> None:
        if event.button() == Qt.LeftButton and self._strip_preview_path:
            popup = _FullImagePopup(self._strip_preview_path, parent=self)
            popup.exec()

    def _add_video_button(self, path: str, npc_name: str, level: int) -> None:
        """Append 'open clip' button below the strip preview caption."""
        # We embed the button dynamically into the strip panel layout
        strip_panel = self._strip_cap.parent()
        if strip_panel is None:
            return
        layout = strip_panel.layout()
        btn = QPushButton(f"▶  Apri clip {npc_name} lvl {level}")
        btn.setStyleSheet(_STYLE_BTN_QUICK)
        btn.clicked.connect(lambda _, p=path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))))
        layout.addWidget(btn)

    # ── Resize events ─────────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rescale_table()
        self._rescale_strip()

    # ── Chat — append helpers ─────────────────────────────────────────────────

    def _append_html(self, html: str) -> None:
        self._chat_html += html
        self._chat_lbl.setText(self._chat_html)
        QTimer.singleShot(50, self._scroll_chat_bottom)

    def _scroll_chat_bottom(self) -> None:
        sb = self._chat_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _append_user(self, text: str) -> None:
        esc = self._escape(text)
        html = (
            f'<div style="color:{_C_USER}; font-weight:bold; margin:10px 0 4px 0;">'
            f'♠ Tu: <span style="color:{_TEXT_MAIN}; font-weight:normal;">{esc}</span>'
            f'</div>'
        )
        self._append_html(html)

    def _append_npc(self, text: str) -> None:
        """Parse poker narrative text and apply semantic colors line by line."""
        if text.startswith("[DIALOGO]"):
            return self._append_dialogue_npc(text[len("[DIALOGO]"):].strip())
        self._append_html(self._format_poker_text(text))

    def _append_dialogue_npc(self, text: str) -> None:
        """NPC spoken /d dialogue — lavender with left border."""
        esc = self._escape(text)
        esc = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', esc)
        html = (
            f'<div style="color:{_C_DIALOGUE}; font-style:italic; margin:6px 0; '
            f'padding-left:10px; border-left:3px solid #9b7fe0;">'
            f'💬 {esc}</div>'
        )
        self._append_html(html)

    def _append_system(self, text: str) -> None:
        esc = self._escape(text)
        esc = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', esc)
        html = (
            f'<div style="color:{_C_SYSTEM}; font-style:italic; margin:4px 0;">'
            f'[{esc}]</div>'
        )
        self._append_html(html)

    def _append_error(self, text: str) -> None:
        esc = self._escape(text)
        html = f'<div style="color:{_C_ERROR}; margin:4px 0;">{esc}</div>'
        self._append_html(html)

    def _format_poker_text(self, text: str) -> str:
        """Convert a poker narrative block into semantic-colored HTML."""
        lines = text.split('\n')
        parts: list[str] = []

        for raw in lines:
            line = raw.strip()
            if not line:
                parts.append('<div style="margin:2px 0;"></div>')
                continue

            esc = self._escape(line)
            esc = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', esc)
            esc = re.sub(r'\*(.+?)\*',     r'<i>\1</i>', esc)
            esc = re.sub(r'`(.+?)`',       r'<b>\1</b>', esc)

            # Strip surrounding _ (italic hints)
            if esc.startswith('_') and esc.endswith('_'):
                esc = f'<i>{esc[1:-1]}</i>'
                color, extra = _C_SYSTEM, 'font-size:13px;'

            # Hand divider ────
            elif '─' in line:
                color, extra = '#555', 'font-size:10px; margin-top:10px;'

            # New hand header
            elif re.search(r'Mano #\d+', line):
                color, extra = _C_GAME_EVENT, 'font-weight:bold; margin-top:8px; font-size:15px;'

            # Showdown / game over
            elif any(k in line for k in ('SHOWDOWN', 'GAME OVER', 'Fine della partita', 'Statistiche')):
                color, extra = _C_GAME_EVENT, 'font-weight:bold; font-size:16px;'

            # Win/lose outcome
            elif re.search(r'(vinto|vince)\s+[\d,]+\s+chips', line):
                color, extra = _C_GAME_EVENT, 'font-weight:bold;'

            # Strip events
            elif any(k in line for k in ('STRIP EVENT', 'ELIMINATA', 'nuda!')):
                color, extra = _C_STRIP, 'font-weight:bold; font-size:15px;'

            # Player action result ("Hai visto", "Hai fatto fold", "Sei andato all-in")
            elif re.match(r'^(Hai |Sei )', line):
                color, extra = _C_PLAYER_ACT, ''

            # NPC spoken line (strip dialogue or reaction with quotes)
            elif re.match(r'^(Luna|Maria|Stella):\s*["\*]', line):
                color, extra = _C_NPC_SPEECH, 'font-style:italic;'

            # NPC poker action (fold / vede / check / rilancia / punta / all-in)
            elif re.match(r'^(Luna|Maria|Stella|Player):\s*\*\*', line):
                color, extra = _C_NPC_ACTION, ''

            # Stack lines
            elif re.match(r'^\s*(Player|Luna|Maria|Stella):\s+[\d,]+', line):
                color, extra = _C_SYSTEM, 'font-size:13px;'

            # Board / hole cards / pot info
            elif re.match(r'^(Board|Le tue carte|Pot|SB:|BB:):', line):
                color, extra = '#aaa', ''

            # Legal actions hint
            elif line.startswith('Azioni disponibili'):
                color, extra = _C_SYSTEM, 'font-size:13px;'

            # Stack header
            elif line in ('**Stack:**', 'Stack:'):
                color, extra = _C_SYSTEM, 'font-size:13px; font-weight:bold;'

            else:
                color, extra = _TEXT_MAIN, ''

            parts.append(
                f'<div style="color:{color};{extra};margin:1px 0;">{esc}</div>'
            )

        return ''.join(parts)

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _escape(text: str) -> str:
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

    def _set_input_enabled(self, enabled: bool) -> None:
        self._txt_input.setEnabled(enabled)
        self._btn_send.setEnabled(enabled)

    def _ensure_foreground(self) -> None:
        """Keep poker window visible/focused during long async generation."""
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    # ── Public API ────────────────────────────────────────────────────────────

    def display_startup_result(self, result) -> None:
        """Called from MainWindow right after game starts."""
        self._apply_result(result)

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)
