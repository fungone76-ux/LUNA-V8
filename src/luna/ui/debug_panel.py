"""Debug Panel for Affinity and Personality tweaking.

V4.6: Development tool for testing quest triggers and personality changes.
"""
from __future__ import annotations

import logging
from typing import Optional, Dict, Any
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QScrollArea,
    QFrame, QGroupBox, QSpinBox, QSlider, QTabWidget,
)
from PySide6.QtCore import Qt, Signal

logger = logging.getLogger(__name__)


class ValueControlWidget(QWidget):
    """Widget with label, progress bar, +/- buttons and direct input."""
    
    value_changed = Signal(str, str, int)  # npc_name, trait_name, new_value
    
    def __init__(
        self,
        npc_name: str,
        trait_name: str,
        label_text: str,
        initial_value: int = 50,
        min_val: int = 0,
        max_val: int = 100,
        parent=None
    ) -> None:
        super().__init__(parent)
        
        self.npc_name = npc_name
        self.trait_name = trait_name
        self.min_val = min_val
        self.max_val = max_val
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)
        
        # Label
        self.label = QLabel(f"{label_text}:")
        self.label.setMinimumWidth(100)
        layout.addWidget(self.label)
        
        # Progress bar (visual)
        self.bar = QProgressBar()
        self.bar.setRange(min_val, max_val)
        self.bar.setValue(initial_value)
        self.bar.setTextVisible(True)
        self.bar.setFormat("%v")
        self.bar.setMinimumWidth(120)
        layout.addWidget(self.bar, stretch=1)
        
        # Minus button
        self.btn_minus = QPushButton("−")
        self.btn_minus.setFixedSize(28, 28)
        self.btn_minus.setToolTip(f"Decrease {label_text}")
        self.btn_minus.clicked.connect(self._on_decrease)
        layout.addWidget(self.btn_minus)
        
        # Value display / spin box
        self.spin = QSpinBox()
        self.spin.setRange(min_val, max_val)
        self.spin.setValue(initial_value)
        self.spin.setFixedWidth(60)
        self.spin.valueChanged.connect(self._on_spin_changed)
        layout.addWidget(self.spin)
        
        # Plus button
        self.btn_plus = QPushButton("+")
        self.btn_plus.setFixedSize(28, 28)
        self.btn_plus.setToolTip(f"Increase {label_text}")
        self.btn_plus.clicked.connect(self._on_increase)
        layout.addWidget(self.btn_plus)
        
        # Slider for quick adjustment
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(min_val, max_val)
        self.slider.setValue(initial_value)
        self.slider.setMaximumWidth(100)
        self.slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.slider)
    
    def _on_decrease(self) -> None:
        """Decrease value by 5."""
        new_val = max(self.min_val, self.spin.value() - 5)
        self.set_value(new_val)
    
    def _on_increase(self) -> None:
        """Increase value by 5."""
        new_val = min(self.max_val, self.spin.value() + 5)
        self.set_value(new_val)
    
    def _on_spin_changed(self, value: int) -> None:
        """Handle spin box change."""
        self._update_widgets(value)
        self.value_changed.emit(self.npc_name, self.trait_name, value)
    
    def _on_slider_changed(self, value: int) -> None:
        """Handle slider change."""
        self.set_value(value)
    
    def set_value(self, value: int) -> None:
        """Set value from external source."""
        if value != self.spin.value():
            self.spin.setValue(value)
        self._update_widgets(value)
    
    def _update_widgets(self, value: int) -> None:
        """Update all widgets to show same value."""
        self.bar.setValue(value)
        if self.slider.value() != value:
            self.slider.setValue(value)
    
    def get_value(self) -> int:
        """Get current value."""
        return self.spin.value()


class NPCDebugPanel(QWidget):
    """Debug panel for a single NPC."""
    
    affinity_changed = Signal(str, int)  # npc_name, new_affinity
    trait_changed = Signal(str, str, int)  # npc_name, trait_name, new_value
    
    def __init__(self, npc_name: str, parent=None) -> None:
        super().__init__(parent)
        
        self.npc_name = npc_name
        self.trait_controls: Dict[str, ValueControlWidget] = {}
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # === AFFINITY SECTION ===
        affinity_group = QGroupBox("❤️ Affinity")
        affinity_layout = QVBoxLayout(affinity_group)
        
        self.affinity_control = ValueControlWidget(
            npc_name=npc_name,
            trait_name="affinity",
            label_text="Affinity",
            initial_value=0,
            min_val=0,
            max_val=100
        )
        self.affinity_control.value_changed.connect(self._on_affinity_changed)
        affinity_layout.addWidget(self.affinity_control)
        
        # Quest trigger indicators
        self.quest_info = QLabel("Quest triggers: affinity ≥ 60")
        self.quest_info.setStyleSheet("color: gray; font-size: 11px;")
        affinity_layout.addWidget(self.quest_info)
        
        layout.addWidget(affinity_group)
        
        # === PERSONALITY SECTION ===
        personality_group = QGroupBox("🎭 Personality Traits")
        personality_layout = QVBoxLayout(personality_group)
        
        # Default traits (will be populated from actual data)
        # Note: Personality impression values range from -100 to +100
        self.default_traits = [
            ("romantic", "Attraction"),
            ("playful", "Curiosity"),
            ("trust", "Trust"),
            ("dominance", "Dominance Balance"),
            ("openness", "Openness"),
        ]
        
        for trait_id, trait_label in self.default_traits:
            control = ValueControlWidget(
                npc_name=npc_name,
                trait_name=trait_id,
                label_text=trait_label,
                initial_value=0,
                min_val=-100,
                max_val=100
            )
            control.value_changed.connect(self._on_trait_changed)
            self.trait_controls[trait_id] = control
            personality_layout.addWidget(control)
        
        layout.addWidget(personality_group)
        layout.addStretch()
    
    def _on_affinity_changed(self, npc: str, trait: str, value: int) -> None:
        """Handle affinity change."""
        self.affinity_changed.emit(npc, value)
        self._update_quest_indicator(value)
    
    def _update_quest_indicator(self, affinity: int) -> None:
        """Update quest trigger indicator."""
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
        """Handle personality trait change."""
        self.trait_changed.emit(npc, trait, value)
    
    def set_affinity(self, value: int) -> None:
        """Set affinity value from external source."""
        self.affinity_control.set_value(value)
        self._update_quest_indicator(value)
    
    def set_trait(self, trait_name: str, value: int) -> None:
        """Set personality trait value."""
        if trait_name in self.trait_controls:
            self.trait_controls[trait_name].set_value(value)
    
    def get_values(self) -> Dict[str, Any]:
        """Get all current values."""
        return {
            "affinity": self.affinity_control.get_value(),
            "traits": {
                name: control.get_value()
                for name, control in self.trait_controls.items()
            }
        }


class DebugPanelWindow(QDialog):
    """Debug window for tweaking game values in real-time."""
    
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        
        self.setWindowTitle("🔧 Debug Panel - Affinity & Personality")
        self.setMinimumSize(500, 600)
        self.resize(550, 700)
        
        self.npc_panels: Dict[str, NPCDebugPanel] = {}
        self._engine = None
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup the debug panel UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Header
        header = QLabel("🎮 Real-time Value Editor")
        header.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)
        
        # Info label
        info = QLabel("Modifica affinità e personalità per testare quest e comportamenti NPC.")
        info.setStyleSheet("color: gray; font-size: 11px; padding: 5px;")
        info.setWordWrap(True)
        layout.addWidget(info)
        
        # Tabs for each NPC
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, stretch=1)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.btn_refresh = QPushButton("🔄 Refresh from Game")
        self.btn_refresh.clicked.connect(self.refresh_values)
        button_layout.addWidget(self.btn_refresh)
        
        self.btn_reset = QPushButton("⚠️ Reset All")
        self.btn_reset.clicked.connect(self._on_reset)
        button_layout.addWidget(self.btn_reset)
        
        button_layout.addStretch()
        
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        button_layout.addWidget(self.btn_close)
        
        layout.addLayout(button_layout)
    
    def set_engine(self, engine) -> None:
        """Connect to game engine."""
        self._engine = engine
        self._populate_npcs()
        self.refresh_values()
    
    def _populate_npcs(self) -> None:
        """Create tabs for each NPC."""
        if not self._engine or not self._engine.world:
            return
        
        self.tabs.clear()
        self.npc_panels.clear()
        
        for npc_name in sorted(self._engine.world.companions.keys()):
            panel = NPCDebugPanel(npc_name)
            panel.affinity_changed.connect(self._on_affinity_changed)
            panel.trait_changed.connect(self._on_trait_changed)
            
            self.npc_panels[npc_name] = panel
            self.tabs.addTab(panel, npc_name)
    
    def _on_affinity_changed(self, npc_name: str, value: int) -> None:
        """Handle affinity change from UI."""
        if not self._engine:
            return
        
        # Get current affinity to calculate delta
        current = 0
        if hasattr(self._engine, 'state_manager'):
            current = self._engine.state_manager.get_affinity(npc_name)
            delta = value - current
            if delta != 0:
                self._engine.state_manager.change_affinity(npc_name, delta)
                logger.debug(f"[DebugPanel] {npc_name} affinity: {current} -> {value} (delta={delta})")
        
        # Also update gameplay_manager affinity if exists
        if self._engine.gameplay_manager and hasattr(self._engine.gameplay_manager, 'affinity'):
            try:
                # Try to set directly if method exists
                affinity_system = self._engine.gameplay_manager.affinity
                if hasattr(affinity_system, '_affinity'):
                    affinity_system._affinity[npc_name] = value
                elif hasattr(affinity_system, 'affinity'):
                    affinity_system.affinity[npc_name] = value
            except Exception as e:
                logger.warning(f"[DebugPanel] Note: Could not update gameplay_manager affinity: {e}")
    
    def _on_trait_changed(self, npc_name: str, trait: str, value: int) -> None:
        """Handle personality trait change from UI."""
        if not self._engine or not self._engine.personality_engine:
            return
        
        try:
            # Get the personality state
            state = self._engine.personality_engine._ensure_state(npc_name)
            
            # Map UI trait names to Impression fields
            trait_mapping = {
                "romantic": "attraction",
                "playful": "curiosity",
                "strict": None,  # Not in impression, skip
                "trust": "trust",
                "dominance": "dominance_balance",
                "openness": "curiosity",
            }
            
            impression_field = trait_mapping.get(trait)
            if impression_field and hasattr(state.impression, impression_field):
                setattr(state.impression, impression_field, max(-100, min(100, value)))
                logger.debug(f"[DebugPanel] {npc_name}.{impression_field} = {value}")
        except Exception as e:
            logger.error(f"[DebugPanel] Error updating trait: {e}")
    
    def refresh_values(self) -> None:
        """Refresh UI from current game state."""
        if not self._engine:
            return
        
        for npc_name, panel in self.npc_panels.items():
            # Get affinity
            affinity = 0
            if hasattr(self._engine, 'state_manager'):
                affinity = self._engine.state_manager.get_affinity(npc_name)
            elif self._engine.gameplay_manager and hasattr(self._engine.gameplay_manager, 'affinity'):
                affinity = self._engine.gameplay_manager.affinity.get_affinity(npc_name)
            
            panel.set_affinity(affinity)
            
            # Get personality traits from impression
            if self._engine.personality_engine:
                try:
                    state = self._engine.personality_engine._ensure_state(npc_name)
                    impression = state.impression
                    
                    # Map impression fields to UI traits
                    trait_values = {
                        "romantic": impression.attraction,
                        "playful": impression.curiosity,
                        "trust": impression.trust,
                        "dominance": impression.dominance_balance,
                        "openness": impression.curiosity,
                    }
                    
                    for trait_name, value in trait_values.items():
                        panel.set_trait(trait_name, value)
                except Exception as e:
                    logger.error(f"[DebugPanel] Could not load traits for {npc_name}: {e}")
    
    def _on_reset(self) -> None:
        """Reset all values to defaults."""
        for npc_name, panel in self.npc_panels.items():
            panel.set_affinity(0)
            for trait_id, _ in panel.default_traits:
                panel.set_trait(trait_id, 50)
            
            # Apply to engine
            self._on_affinity_changed(npc_name, 0)
    
    def showEvent(self, event) -> None:
        """Refresh values when window is shown."""
        super().showEvent(event)
        self.refresh_values()
