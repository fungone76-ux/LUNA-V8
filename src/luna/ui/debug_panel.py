"""Debug Panel — Affinity, Personality, Events.

Real-time editor for testing quest triggers, personality changes, and
force-activating NPC events / global events without waiting for RNG.
"""
from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QScrollArea,
    QFrame, QGroupBox, QSpinBox, QSlider, QTabWidget,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Affinity / Trait control widget
# ─────────────────────────────────────────────────────────────────────────────

class ValueControlWidget(QWidget):
    """Label + progress bar + ±5 buttons + spinbox + slider."""

    value_changed = Signal(str, str, int)  # npc_name, trait_name, new_value

    def __init__(
        self,
        npc_name: str,
        trait_name: str,
        label_text: str,
        initial_value: int = 50,
        min_val: int = 0,
        max_val: int = 100,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.npc_name  = npc_name
        self.trait_name = trait_name
        self.min_val   = min_val
        self.max_val   = max_val

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        self.label = QLabel(f"{label_text}:")
        self.label.setMinimumWidth(110)
        layout.addWidget(self.label)

        self.bar = QProgressBar()
        self.bar.setRange(min_val, max_val)
        self.bar.setValue(initial_value)
        self.bar.setTextVisible(True)
        self.bar.setFormat("%v")
        self.bar.setMinimumWidth(100)
        layout.addWidget(self.bar, stretch=1)

        self.btn_minus = QPushButton("−")
        self.btn_minus.setFixedSize(28, 28)
        self.btn_minus.clicked.connect(self._on_decrease)
        layout.addWidget(self.btn_minus)

        self.spin = QSpinBox()
        self.spin.setRange(min_val, max_val)
        self.spin.setValue(initial_value)
        self.spin.setFixedWidth(60)
        self.spin.valueChanged.connect(self._on_spin_changed)
        layout.addWidget(self.spin)

        self.btn_plus = QPushButton("+")
        self.btn_plus.setFixedSize(28, 28)
        self.btn_plus.clicked.connect(self._on_increase)
        layout.addWidget(self.btn_plus)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(min_val, max_val)
        self.slider.setValue(initial_value)
        self.slider.setMaximumWidth(100)
        self.slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.slider)

    def _on_decrease(self) -> None:
        self.set_value(max(self.min_val, self.spin.value() - 5))

    def _on_increase(self) -> None:
        self.set_value(min(self.max_val, self.spin.value() + 5))

    def _on_spin_changed(self, value: int) -> None:
        self._update_widgets(value)
        self.value_changed.emit(self.npc_name, self.trait_name, value)

    def _on_slider_changed(self, value: int) -> None:
        self.set_value(value)

    def set_value(self, value: int) -> None:
        if value != self.spin.value():
            self.spin.setValue(value)
        self._update_widgets(value)

    def _update_widgets(self, value: int) -> None:
        self.bar.setValue(value)
        if self.slider.value() != value:
            self.slider.setValue(value)

    def get_value(self) -> int:
        return self.spin.value()


# ─────────────────────────────────────────────────────────────────────────────
# Per-NPC panel (affinity + personality)
# ─────────────────────────────────────────────────────────────────────────────

class NPCDebugPanel(QWidget):
    affinity_changed = Signal(str, int)   # npc_name, new_affinity
    trait_changed    = Signal(str, str, int)  # npc_name, trait_name, new_value

    def __init__(self, npc_name: str, parent=None) -> None:
        super().__init__(parent)
        self.npc_name = npc_name
        self.trait_controls: Dict[str, ValueControlWidget] = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # Affinity
        aff_group = QGroupBox("❤️ Affinity")
        aff_layout = QVBoxLayout(aff_group)
        self.affinity_control = ValueControlWidget(
            npc_name=npc_name, trait_name="affinity",
            label_text="Affinity", initial_value=0,
        )
        self.affinity_control.value_changed.connect(self._on_affinity_changed)
        aff_layout.addWidget(self.affinity_control)
        self.quest_info = QLabel("Quest triggers: affinity ≥ 60")
        self.quest_info.setStyleSheet("color: gray; font-size: 11px;")
        aff_layout.addWidget(self.quest_info)
        layout.addWidget(aff_group)

        # Personality
        pers_group = QGroupBox("🎭 Personality Traits")
        pers_layout = QVBoxLayout(pers_group)
        for trait_id, trait_label in [
            ("romantic",   "Attraction"),
            ("playful",    "Curiosity"),
            ("trust",      "Trust"),
            ("dominance",  "Dominance Balance"),
            ("openness",   "Openness"),
        ]:
            ctrl = ValueControlWidget(
                npc_name=npc_name, trait_name=trait_id,
                label_text=trait_label, initial_value=0,
                min_val=-100, max_val=100,
            )
            ctrl.value_changed.connect(self._on_trait_changed)
            self.trait_controls[trait_id] = ctrl
            pers_layout.addWidget(ctrl)
        layout.addWidget(pers_group)
        layout.addStretch()

    def _on_affinity_changed(self, npc: str, trait: str, value: int) -> None:
        self.affinity_changed.emit(npc, value)
        self._update_quest_indicator(value)

    def _update_quest_indicator(self, affinity: int) -> None:
        if affinity >= 60:
            self.quest_info.setText("✅ Quest 'Lezione Privata' ATTIVA!")
            self.quest_info.setStyleSheet("color: green; font-weight: bold; font-size: 11px;")
        elif affinity >= 40:
            self.quest_info.setText("🔄 Quest 'Confessione' attiva a 60")
            self.quest_info.setStyleSheet("color: orange; font-size: 11px;")
        else:
            self.quest_info.setText("Quest triggers: affinity ≥ 60")
            self.quest_info.setStyleSheet("color: gray; font-size: 11px;")

    def _on_trait_changed(self, npc: str, trait: str, value: int) -> None:
        self.trait_changed.emit(npc, trait, value)

    def set_affinity(self, value: int) -> None:
        self.affinity_control.set_value(value)
        self._update_quest_indicator(value)

    def set_trait(self, trait_name: str, value: int) -> None:
        if trait_name in self.trait_controls:
            self.trait_controls[trait_name].set_value(value)

    def get_values(self) -> Dict[str, Any]:
        return {
            "affinity": self.affinity_control.get_value(),
            "traits": {n: c.get_value() for n, c in self.trait_controls.items()},
        }


# ─────────────────────────────────────────────────────────────────────────────
# Events tab
# ─────────────────────────────────────────────────────────────────────────────

class EventsDebugPanel(QWidget):
    """Lists NPC events and global events with force-activate buttons."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._engine = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        self._content = QWidget()
        self._layout  = QVBoxLayout(self._content)
        self._layout.setSpacing(4)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.addStretch()
        scroll.setWidget(self._content)

        # Refresh button
        btn_refresh = QPushButton("🔄 Refresh event list")
        btn_refresh.clicked.connect(self.populate)
        outer.addWidget(btn_refresh)

    def set_engine(self, engine) -> None:
        self._engine = engine
        self.populate()

    def populate(self) -> None:
        """Rebuild the event list from the engine."""
        # Clear existing rows (keep the stretch at end)
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._engine:
            return

        # ── NPC events (quests with type npc_event) ──────────────────────────
        npc_quests = {}
        if self._engine.world and self._engine.world.quests:
            for qid, qdef in self._engine.world.quests.items():
                qtype = getattr(qdef, "quest_type", "") or ""
                if qtype == "npc_event" or "npc_" in qid:
                    npc_quests[qid] = qdef

        if npc_quests:
            grp = QGroupBox("👤 NPC Events")
            grp_layout = QVBoxLayout(grp)
            grp_layout.setSpacing(3)
            for qid, qdef in sorted(npc_quests.items()):
                title = getattr(qdef, "title", qid)
                row = self._make_event_row(
                    label=f"{title}  [{qid}]",
                    on_activate=lambda checked=False, q=qid: self._force_npc_event(q),
                    status=self._npc_event_status(qid),
                )
                grp_layout.addWidget(row)
            self._layout.insertWidget(self._layout.count() - 1, grp)

        # ── Global events ─────────────────────────────────────────────────────
        global_events = {}
        if self._engine.event_manager:
            global_events = getattr(self._engine.event_manager, "event_definitions", {}) or {}

        if global_events:
            grp2 = QGroupBox("🌍 Global Events")
            grp2_layout = QVBoxLayout(grp2)
            grp2_layout.setSpacing(3)
            for eid in sorted(global_events.keys()):
                edef = global_events[eid]
                if isinstance(edef, dict):
                    title = edef.get("meta", {}).get("title", eid)
                else:
                    title = getattr(getattr(edef, "meta", None), "title", eid)
                active = eid in getattr(self._engine.event_manager, "active_events", {})
                row = self._make_event_row(
                    label=f"{title}  [{eid}]",
                    on_activate=lambda checked=False, e=eid: self._force_global_event(e),
                    status="🟢 ACTIVE" if active else "",
                )
                grp2_layout.addWidget(row)
            self._layout.insertWidget(self._layout.count() - 1, grp2)

        if not npc_quests and not global_events:
            lbl = QLabel("Nessun evento trovato. Avvia prima una partita.")
            lbl.setStyleSheet("color: gray; padding: 20px;")
            self._layout.insertWidget(0, lbl)

    def _npc_event_status(self, quest_id: str) -> str:
        if not self._engine:
            return ""
        gs = self._engine.state if hasattr(self._engine, "state") else None
        if not gs:
            return ""
        if quest_id in getattr(gs, "completed_quests", []):
            return "✅ done"
        if quest_id in getattr(gs, "active_quests", []):
            return "🟢 ACTIVE"
        return ""

    def _make_event_row(self, label: str, on_activate, status: str) -> QWidget:
        row = QWidget()
        hl  = QHBoxLayout(row)
        hl.setContentsMargins(2, 2, 2, 2)
        hl.setSpacing(6)

        lbl = QLabel(label)
        lbl.setWordWrap(False)
        hl.addWidget(lbl, stretch=1)

        if status:
            slbl = QLabel(status)
            slbl.setStyleSheet("color: #4CAF50; font-size: 11px;")
            hl.addWidget(slbl)

        btn = QPushButton("▶ Force")
        btn.setFixedWidth(80)
        btn.setFixedHeight(26)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800; color: white;
                font-size: 11px; font-weight: bold;
                border: none; border-radius: 4px;
            }
            QPushButton:hover { background-color: #F57C00; }
        """)
        btn.clicked.connect(on_activate)
        hl.addWidget(btn)

        return row

    def _force_npc_event(self, quest_id: str) -> None:
        if not self._engine:
            QMessageBox.warning(self, "Debug", "Engine non disponibile.")
            return

        gs = getattr(self._engine, "state", None)
        qe = getattr(self._engine, "quest_engine", None)
        world = getattr(self._engine, "world", None)

        if not gs or not qe or not world:
            QMessageBox.warning(self, "Debug", "Engine non inizializzato.")
            return

        if quest_id in getattr(gs, "active_quests", []):
            QMessageBox.information(self, "Debug", f"'{quest_id}' è già attivo.")
            return

        quest_def = world.quests.get(quest_id)
        if not quest_def:
            QMessageBox.warning(self, "Debug", f"Quest '{quest_id}' non trovata.")
            return

        # Remove from completed so it can re-activate
        completed = getattr(gs, "completed_quests", [])
        if quest_id in completed:
            completed.remove(quest_id)

        try:
            qe._activate_quest(quest_def, gs)
            logger.info("[DebugPanel] Force-activated NPC event: %s", quest_id)
            self.populate()
            QMessageBox.information(self, "Debug", f"✅ '{quest_def.title}' attivato!")
        except Exception as e:
            logger.error("[DebugPanel] Force-activate failed for %s: %s", quest_id, e)
            QMessageBox.critical(self, "Debug", f"Errore: {e}")

    def _force_global_event(self, event_id: str) -> None:
        if not self._engine or not self._engine.event_manager:
            QMessageBox.warning(self, "Debug", "EventManager non disponibile.")
            return
        ok = self._engine.event_manager.force_activate_event(event_id)
        self.populate()
        if ok:
            QMessageBox.information(self, "Debug", f"✅ Global event '{event_id}' attivato!")
        else:
            QMessageBox.warning(self, "Debug", f"'{event_id}' non attivabile (già attivo o non trovato).")


# ─────────────────────────────────────────────────────────────────────────────
# Main debug window
# ─────────────────────────────────────────────────────────────────────────────

class DebugPanelWindow(QDialog):
    """Debug window — Affinity, Personality, Events."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("🔧 Debug Panel")
        self.setMinimumSize(560, 640)
        self.resize(600, 720)

        self.npc_panels:  Dict[str, NPCDebugPanel] = {}
        self._engine      = None
        self._events_panel: Optional[EventsDebugPanel] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)

        hdr = QLabel("🎮 Debug — Real-time Editor")
        hdr.setStyleSheet("font-size: 15px; font-weight: bold; padding: 6px;")
        hdr.setAlignment(Qt.AlignCenter)
        layout.addWidget(hdr)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, stretch=1)

        # Events tab (always present)
        self._events_panel = EventsDebugPanel()
        self.tabs.addTab(self._events_panel, "📅 Events")

        # Buttons
        btn_row = QHBoxLayout()
        btn_refresh = QPushButton("🔄 Refresh")
        btn_refresh.clicked.connect(self.refresh_values)
        btn_row.addWidget(btn_refresh)

        btn_reset = QPushButton("⚠️ Reset All Affinity")
        btn_reset.clicked.connect(self._on_reset)
        btn_row.addWidget(btn_reset)

        btn_row.addStretch()
        btn_close = QPushButton("Chiudi")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def set_engine(self, engine) -> None:
        """Connect to the game engine and populate all panels."""
        self._engine = engine
        self._populate_npc_tabs()
        if self._events_panel:
            self._events_panel.set_engine(engine)
        self.refresh_values()

    def _populate_npc_tabs(self) -> None:
        # Remove old NPC tabs (keep Events tab at index 0)
        while self.tabs.count() > 1:
            self.tabs.removeTab(1)
        self.npc_panels.clear()

        if not self._engine or not self._engine.world:
            return

        for npc_name in sorted(self._engine.world.companions.keys()):
            panel = NPCDebugPanel(npc_name)
            panel.affinity_changed.connect(self._on_affinity_changed)
            panel.trait_changed.connect(self._on_trait_changed)
            self.npc_panels[npc_name] = panel
            self.tabs.addTab(panel, npc_name)

    # ── Affinity ──────────────────────────────────────────────────────────────

    def _on_affinity_changed(self, npc_name: str, value: int) -> None:
        if not self._engine:
            return
        gs = getattr(self._engine, "state", None)
        if gs is None:
            return
        # GameState.affinity is Dict[str, int]
        gs.affinity[npc_name] = max(0, min(100, value))
        logger.debug("[DebugPanel] %s affinity → %d", npc_name, value)

    # ── Personality traits ────────────────────────────────────────────────────

    def _on_trait_changed(self, npc_name: str, trait: str, value: int) -> None:
        if not self._engine or not self._engine.personality_engine:
            return
        _TRAIT_MAP = {
            "romantic":  "attraction",
            "playful":   "curiosity",
            "trust":     "trust",
            "dominance": "dominance_balance",
            "openness":  "curiosity",
        }
        impression_field = _TRAIT_MAP.get(trait)
        if not impression_field:
            return
        try:
            state = self._engine.personality_engine._ensure_state(npc_name)
            if hasattr(state.impression, impression_field):
                setattr(state.impression, impression_field, max(-100, min(100, value)))
                logger.debug("[DebugPanel] %s.%s → %d", npc_name, impression_field, value)
        except Exception as e:
            logger.error("[DebugPanel] trait update failed: %s", e)

    # ── Refresh / Reset ───────────────────────────────────────────────────────

    def refresh_values(self) -> None:
        if not self._engine:
            return

        gs = getattr(self._engine, "state", None)

        for npc_name, panel in self.npc_panels.items():
            # Read affinity directly from GameState
            affinity = 0
            if gs is not None:
                affinity = gs.affinity.get(npc_name, 0)
            panel.set_affinity(affinity)

            # Read impression values
            if self._engine.personality_engine:
                try:
                    state = self._engine.personality_engine._ensure_state(npc_name)
                    imp = state.impression
                    for trait_id, field_name in [
                        ("romantic",  "attraction"),
                        ("playful",   "curiosity"),
                        ("trust",     "trust"),
                        ("dominance", "dominance_balance"),
                        ("openness",  "curiosity"),
                    ]:
                        panel.set_trait(trait_id, int(getattr(imp, field_name, 0)))
                except Exception as e:
                    logger.debug("[DebugPanel] refresh trait error for %s: %s", npc_name, e)

        if self._events_panel:
            self._events_panel.populate()

    def _on_reset(self) -> None:
        if not self._engine:
            return
        gs = getattr(self._engine, "state", None)
        for npc_name, panel in self.npc_panels.items():
            panel.set_affinity(0)
            if gs is not None:
                gs.affinity[npc_name] = 0
            self._on_affinity_changed(npc_name, 0)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_values()
