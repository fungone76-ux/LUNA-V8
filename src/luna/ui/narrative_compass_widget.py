"""Luna RPG v7 — Narrative Compass Widget.

Shows the player the current narrative state without spoilering:
  - Arc phase per companion (ARMOR, CRACKS, CONFLICT...)
  - Active tension axis + phase + trend
  - Climate whisper text (updated every 3 turns or on phase change)
  - Active quest info (title, stage, player hint, next quest)

This widget is read-only — it never modifies game state.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout,
    QLabel, QProgressBar, QWidget, QFrame,
)
from PySide6.QtCore import Qt


# ---------------------------------------------------------------------------
# Phase → display color (dark theme)
# ---------------------------------------------------------------------------

_PHASE_COLORS: dict[str, str] = {
    "UNKNOWN":   "#888888",
    "ARMOR":     "#7B9AB2",
    "CRACKS":    "#E8A040",
    "CONFLICT":  "#E06030",
    "SURRENDER": "#D080A0",
    "DEVOTED":   "#D4AF37",
}

_TENSION_COLORS: dict[str, str] = {
    "calm":          "#4CAF50",
    "foreshadowing": "#FFC107",
    "buildup":       "#FF9800",
    "trigger":       "#F44336",
}

_TENSION_LABELS: dict[str, str] = {
    "calm":          "calma",
    "foreshadowing": "presagio",
    "buildup":       "accumulo",
    "trigger":       "esplosione",
}

# Compass refresh: climate text stays this many turns before updating
_CLIMATE_TTL = 3


class NarrativeCompassWidget(QGroupBox):
    """Narrative Compass — player-facing narrative state panel.

    Updated each turn from TurnResult.narrative_compass.
    Never modifies game state.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("STORIA", parent)
        self.setMaximumHeight(320)  # Increased to fit quest section
        self.setMinimumHeight(220)

        self._climate_ttl: int = 0
        self._last_tension_phase: str = ""
        self._current_climate: str = ""

        self._setup_ui()

    # -------------------------------------------------------------------------
    # UI setup
    # -------------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 12, 8, 6)

        self.setStyleSheet("""
            QGroupBox {
                color: #ccc;
                font-size: 10px;
                font-weight: bold;
                border: 1px solid #444;
                border-radius: 4px;
                margin-top: 6px;
                padding-top: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
        """)

        # --- Arc phases container ---
        self._arc_container = QWidget()
        self._arc_layout = QVBoxLayout(self._arc_container)
        self._arc_layout.setSpacing(2)
        self._arc_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._arc_container)

        # Placeholder when no companions
        self._lbl_no_companions = QLabel("Nessun companion attivo")
        self._lbl_no_companions.setStyleSheet("color: #666; font-size: 10px;")
        self._arc_layout.addWidget(self._lbl_no_companions)

        # --- Separator ---
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #444;")
        layout.addWidget(sep)

        # --- Tension bar ---
        tension_widget = QWidget()
        tension_layout = QHBoxLayout(tension_widget)
        tension_layout.setSpacing(6)
        tension_layout.setContentsMargins(0, 0, 0, 0)

        self._lbl_tension_axis = QLabel("—")
        self._lbl_tension_axis.setStyleSheet("color: #aaa; font-size: 10px; min-width: 60px;")
        tension_layout.addWidget(self._lbl_tension_axis)

        self._tension_bar = QProgressBar()
        self._tension_bar.setRange(0, 100)
        self._tension_bar.setValue(0)
        self._tension_bar.setTextVisible(False)
        self._tension_bar.setMaximumHeight(8)
        self._tension_bar.setStyleSheet(self._tension_bar_style("#4CAF50"))
        tension_layout.addWidget(self._tension_bar, stretch=1)

        self._lbl_tension_phase = QLabel("calma")
        self._lbl_tension_phase.setStyleSheet("color: #4CAF50; font-size: 10px; min-width: 64px;")
        tension_layout.addWidget(self._lbl_tension_phase)

        self._lbl_trend = QLabel("")
        self._lbl_trend.setStyleSheet("color: #888; font-size: 11px; min-width: 12px;")
        tension_layout.addWidget(self._lbl_trend)

        layout.addWidget(tension_widget)

        # --- Climate whisper ---
        self._lbl_climate = QLabel("")
        self._lbl_climate.setWordWrap(True)
        self._lbl_climate.setStyleSheet(
            "color: #999; font-size: 10px; font-style: italic; padding: 2px 0;"
        )
        self._lbl_climate.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self._lbl_climate)

        # --- Quest section separator ---
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #444;")
        layout.addWidget(sep2)

        # --- Quest section ---
        self._quest_section = QWidget()
        quest_layout = QVBoxLayout(self._quest_section)
        quest_layout.setSpacing(3)
        quest_layout.setContentsMargins(0, 0, 0, 0)

        # Active quest header
        lbl_missione = QLabel("MISSIONE ATTIVA")
        lbl_missione.setStyleSheet(
            "color: #888; font-size: 9px; font-weight: bold; letter-spacing: 1px;"
        )
        quest_layout.addWidget(lbl_missione)

        # Active quest title
        self._lbl_quest_title = QLabel("(nessuna missione attiva)")
        self._lbl_quest_title.setStyleSheet(
            "color: #555; font-size: 12px; font-weight: bold; font-style: italic;"
        )
        self._lbl_quest_title.setWordWrap(True)
        quest_layout.addWidget(self._lbl_quest_title)

        # Stage title
        self._lbl_quest_stage = QLabel("")
        self._lbl_quest_stage.setStyleSheet(
            "color: #777; font-size: 9px; padding-left: 8px;"
        )
        self._lbl_quest_stage.setWordWrap(True)
        quest_layout.addWidget(self._lbl_quest_stage)

        # Player hint
        self._lbl_quest_hint = QLabel("")
        self._lbl_quest_hint.setStyleSheet(
            "color: #4CAF50; font-size: 10px; font-style: italic; padding-left: 8px;"
        )
        self._lbl_quest_hint.setWordWrap(True)
        quest_layout.addWidget(self._lbl_quest_hint)

        # Separator before next quest
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.HLine)
        sep3.setStyleSheet("color: #333; margin-top: 4px;")
        quest_layout.addWidget(sep3)

        # Next quest row
        next_row = QWidget()
        next_layout = QHBoxLayout(next_row)
        next_layout.setContentsMargins(0, 0, 0, 0)
        next_layout.setSpacing(6)

        lbl_prefix = QLabel("PROSSIMA")
        lbl_prefix.setStyleSheet(
            "color: #666; font-size: 9px; font-weight: bold; letter-spacing: 1px; min-width: 60px;"
        )
        next_layout.addWidget(lbl_prefix)

        self._lbl_next_quest = QLabel("—")
        self._lbl_next_quest.setStyleSheet("color: #666; font-size: 10px;")
        self._lbl_next_quest.setWordWrap(True)
        next_layout.addWidget(self._lbl_next_quest, stretch=1)

        quest_layout.addWidget(next_row)
        layout.addWidget(self._quest_section)

    # -------------------------------------------------------------------------
    # Update API
    # -------------------------------------------------------------------------

    def update_compass(self, compass) -> None:
        """Update all compass sections from a NarrativeCompassData object.

        Args:
            compass: NarrativeCompassData instance (or None to clear)
        """
        if compass is None:
            return

        self._update_arc_phases(compass.arc_phases)
        self._update_tension(
            compass.active_tension_axis,
            compass.tension_phase,
            compass.tension_level,
            trend=getattr(compass, "trend", ""),
        )
        self._update_climate(
            compass.climate_text,
            compass.tension_phase,
            ttl_hint=getattr(compass, "climate_ttl", 0),
        )
        # Quest data is updated separately via update_quest()

    def update_quest(
        self,
        active_quest_title: str,
        active_stage_title: str,
        player_hint: str,
        next_quest_title: str,
        is_hidden: bool = False,
    ) -> None:
        """Update the quest section of the compass.

        Args:
            active_quest_title: Title of the active quest (empty if none)
            active_stage_title: Current stage title
            player_hint: What the player should do (shown in green)
            next_quest_title: Title of the next quest to unlock
            is_hidden: If True, don't show quest title (only hint if any)
        """
        if active_quest_title and not is_hidden:
            self._lbl_quest_title.setText(f"📜 {active_quest_title}")
            self._lbl_quest_title.setStyleSheet(
                "color: #ccc; font-size: 12px; font-weight: bold;"
            )
        elif is_hidden and player_hint:
            # Hidden quest: show only hint, no title
            self._lbl_quest_title.setText("📜 Missione segreta...")
            self._lbl_quest_title.setStyleSheet(
                "color: #888; font-size: 12px; font-weight: bold; font-style: italic;"
            )
        else:
            self._lbl_quest_title.setText("(nessuna missione attiva)")
            self._lbl_quest_title.setStyleSheet(
                "color: #555; font-size: 12px; font-weight: bold; font-style: italic;"
            )

        # Stage title
        if active_stage_title:
            self._lbl_quest_stage.setText(f"Fase: {active_stage_title}")
        else:
            self._lbl_quest_stage.setText("")

        # Player hint (green arrow)
        if player_hint:
            self._lbl_quest_hint.setText(f"→ {player_hint}")
        else:
            self._lbl_quest_hint.setText("")

        # Next quest
        if next_quest_title:
            self._lbl_next_quest.setText(next_quest_title)
            self._lbl_next_quest.setStyleSheet("color: #888; font-size: 10px;")
        else:
            self._lbl_next_quest.setText("—")
            self._lbl_next_quest.setStyleSheet("color: #555; font-size: 10px;")

    def clear(self) -> None:
        """Reset to empty state."""
        self._clear_arc_phases()
        self._tension_bar.setValue(0)
        self._lbl_tension_phase.setText("—")
        self._lbl_trend.setText("")
        self._lbl_climate.setText("")
        self._climate_ttl = 0
        self._last_tension_phase = ""
        self.update_quest("", "", "", "")  # Clear quest section

    # -------------------------------------------------------------------------
    # Internal update helpers
    # -------------------------------------------------------------------------

    def _update_arc_phases(self, arc_phases: dict[str, str]) -> None:
        """Rebuild companion arc phase rows."""
        self._clear_arc_phases()

        if not arc_phases:
            self._lbl_no_companions.setVisible(True)
            return

        self._lbl_no_companions.setVisible(False)

        for companion_name, phase in arc_phases.items():
            row = self._make_arc_row(companion_name, phase)
            self._arc_layout.addWidget(row)

    def _make_arc_row(self, name: str, phase: str) -> QWidget:
        """Create a single companion arc phase row."""
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setSpacing(6)
        rl.setContentsMargins(0, 0, 0, 0)

        color = _PHASE_COLORS.get(phase, "#888")

        # Companion name (truncated)
        lbl_name = QLabel(name[:10])
        lbl_name.setStyleSheet("color: #ccc; font-size: 10px; min-width: 52px;")
        rl.addWidget(lbl_name)

        # Phase badge
        lbl_phase = QLabel(phase)
        lbl_phase.setStyleSheet(
            f"color: {color}; font-size: 9px; font-weight: bold;"
            f" background: #1e1e1e; border: 1px solid {color};"
            f" border-radius: 3px; padding: 0 4px;"
        )
        lbl_phase.setAlignment(Qt.AlignCenter)
        rl.addWidget(lbl_phase, stretch=1)

        return row

    def _clear_arc_phases(self) -> None:
        """Remove all companion rows from the arc container."""
        while self._arc_layout.count() > 0:
            item = self._arc_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        # Re-add the placeholder (hidden by default)
        self._lbl_no_companions = QLabel("Nessun companion attivo")
        self._lbl_no_companions.setStyleSheet("color: #666; font-size: 10px;")
        self._lbl_no_companions.setVisible(False)
        self._arc_layout.addWidget(self._lbl_no_companions)

    def _update_tension(
        self, axis: str, phase: str, level: float, trend: str = ""
    ) -> None:
        """Update tension bar, phase label, and trend arrow.

        If `trend` is provided by NarrativeCompassData (canonical source), use it.
        Otherwise fall back to local delta computation for backward compatibility.
        """
        color = _TENSION_COLORS.get(phase, "#4CAF50")
        label = _TENSION_LABELS.get(phase, phase)
        axis_label = axis.replace("_", " ").title() if axis else "—"
        new_value = int(level * 100)

        if trend in ("^", "v", "="):
            # Use authoritative trend from data model
            display_trend = trend
        else:
            # Local fallback: compute from bar delta
            prev_value = self._tension_bar.value()
            if new_value > prev_value + 2:
                display_trend = "^"
            elif new_value < prev_value - 2:
                display_trend = "v"
            else:
                display_trend = "="

        trend_color = {"^": "#FF9800", "v": "#4CAF50"}.get(display_trend, "#888")

        self._lbl_tension_axis.setText(axis_label[:10])
        self._tension_bar.setValue(new_value)
        self._tension_bar.setStyleSheet(self._tension_bar_style(color))
        self._lbl_tension_phase.setText(label)
        self._lbl_tension_phase.setStyleSheet(f"color: {color}; font-size: 10px; min-width: 64px;")
        self._lbl_trend.setText(display_trend)
        self._lbl_trend.setStyleSheet(f"color: {trend_color}; font-size: 11px; min-width: 12px;")

    def _update_climate(self, climate_text: str, tension_phase: str,
                        ttl_hint: int = 0) -> None:
        """Update climate whisper with TTL-based refresh.

        `ttl_hint` is the suggested TTL from NarrativeCompassData (from TensionTracker).
        When > 0 and climate_text is new, it resets the TTL to that value.
        Falls back to _CLIMATE_TTL constant when not provided.
        """
        phase_changed = tension_phase != self._last_tension_phase
        ttl_expired = self._climate_ttl <= 0

        if (ttl_expired or phase_changed) and climate_text:
            self._current_climate = climate_text
            self._climate_ttl = ttl_hint if ttl_hint > 0 else _CLIMATE_TTL
            self._last_tension_phase = tension_phase
        elif self._climate_ttl > 0:
            self._climate_ttl -= 1

        if self._current_climate:
            # Truncate to keep widget compact
            display = self._current_climate[:80]
            if len(self._current_climate) > 80:
                display += "..."
            self._lbl_climate.setText(f'"{display}"')
        else:
            self._lbl_climate.setText("")

    @staticmethod
    def _tension_bar_style(color: str) -> str:
        return f"""
            QProgressBar {{
                background-color: #1e1e1e;
                border: 1px solid #444;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 2px;
            }}
        """
