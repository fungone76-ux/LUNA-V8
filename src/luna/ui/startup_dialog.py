"""Startup dialog for Luna RPG v4.

3-tab interface:
- New Game: World/Companion selection
- Load Game: Database saves
- Settings: Configuration
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QTabWidget, QWidget,
    QListWidget, QListWidgetItem, QMessageBox,
    QGroupBox, QFormLayout, QLineEdit, QCheckBox, QSpinBox,
)
from PySide6.QtCore import Qt

from luna.core.config import get_settings, get_user_prefs
from luna.systems.world import get_world_loader


class StartupDialog(QDialog):
    """Initial dialog for game setup."""

    def __init__(self, parent=None) -> None:
        """Initialize startup dialog."""
        super().__init__(parent)
        self.setWindowTitle("LUNA RPG v4 - Session Setup")
        self.resize(600, 500)

        # Services
        self.settings = get_settings()
        self.user_prefs = get_user_prefs()
        self.world_loader = get_world_loader()

        # Selection state
        self.selected_world_id: Optional[str] = None
        self.selected_companion: Optional[str] = None
        self.selected_session_id: Optional[int] = None
        self.mode: str = "new"  # 'new' or 'load'

        self._setup_ui()
        self._load_worlds()
        self._load_settings()
        
        # Connect tab change to load saves when Load Game tab is selected
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _setup_ui(self) -> None:
        """Setup UI components."""
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("🌙 LUNA RPG v4")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #E91E63;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Tabs
        self.tabs = QTabWidget()

        # Tab 1: New Game
        self.tabs.addTab(self._create_new_game_tab(), "🎮 New Game")

        # Tab 2: Load Game
        self.tabs.addTab(self._create_load_game_tab(), "💾 Load Game")

        # Tab 3: Settings
        self.tabs.addTab(self._create_settings_tab(), "⚙️ Settings")

        layout.addWidget(self.tabs)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("❌ Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_start = QPushButton("▶ Start")
        btn_start.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
            }
        """)
        btn_start.clicked.connect(self._on_start)
        btn_layout.addWidget(btn_start)

        layout.addLayout(btn_layout)

    def _create_new_game_tab(self) -> QWidget:
        """Create New Game tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # World selection
        world_group = QGroupBox("📚 Select World")
        world_layout = QFormLayout(world_group)

        self.combo_worlds = QComboBox()
        self.combo_worlds.currentIndexChanged.connect(self._on_world_changed)
        world_layout.addRow("World:", self.combo_worlds)

        self.lbl_world_desc = QLabel("Select a world to begin...")
        self.lbl_world_desc.setWordWrap(True)
        self.lbl_world_desc.setStyleSheet("color: #888; font-size: 11px;")
        world_layout.addRow(self.lbl_world_desc)

        layout.addWidget(world_group)

        # Companion selection
        companion_group = QGroupBox("👤 Select Companion")
        companion_layout = QFormLayout(companion_group)

        self.combo_companions = QComboBox()
        companion_layout.addRow("Companion:", self.combo_companions)

        self.lbl_companion_desc = QLabel("Select your companion...")
        self.lbl_companion_desc.setWordWrap(True)
        self.lbl_companion_desc.setStyleSheet("color: #888; font-size: 11px;")
        companion_layout.addRow(self.lbl_companion_desc)

        layout.addWidget(companion_group)
        layout.addStretch()

        return tab

    def _create_load_game_tab(self) -> QWidget:
        """Create Load Game tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info = QLabel("📂 Select a saved game:")
        info.setStyleSheet("font-weight: bold;")
        layout.addWidget(info)

        self.list_saves = QListWidget()
        self.list_saves.setStyleSheet("""
            QListWidget {
                background-color: #2d2d2d;
                border: 1px solid #444;
                border-radius: 4px;
                color: #fff;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #444;
            }
            QListWidget::item:selected {
                background-color: #4CAF50;
            }
        """)
        self.list_saves.itemDoubleClicked.connect(self._on_start)
        layout.addWidget(self.list_saves)

        # Buttons row
        btn_layout = QHBoxLayout()
        
        btn_refresh = QPushButton("🔄 Refresh")
        btn_refresh.clicked.connect(self._load_saves)
        btn_layout.addWidget(btn_refresh)
        
        btn_delete_all = QPushButton("🗑️ Elimina Tutti")
        btn_delete_all.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                padding: 5px 15px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        btn_delete_all.clicked.connect(self._delete_all_saves)
        btn_layout.addWidget(btn_delete_all)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        return tab

    def _create_settings_tab(self) -> QWidget:
        """Create Settings tab."""
        tab = QWidget()
        main_layout = QVBoxLayout(tab)

        layout = QFormLayout()
        main_layout.addLayout(layout)

        # Execution mode
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["LOCAL", "RUNPOD"])
        self.combo_mode.currentTextChanged.connect(self._on_execution_mode_changed)
        layout.addRow("Execution Mode:", self.combo_mode)

        # RunPod ID
        self.edit_runpod_id = QLineEdit()
        self.edit_runpod_id.setPlaceholderText("Enter RunPod ID...")
        layout.addRow("RunPod ID:", self.edit_runpod_id)

        # Mock options
        self.chk_mock_llm = QCheckBox("Mock LLM (for testing)")
        layout.addRow(self.chk_mock_llm)

        self.chk_mock_media = QCheckBox("Mock Media (for testing)")
        layout.addRow(self.chk_mock_media)

        # Audio
        self.chk_audio = QCheckBox("Enable Audio")
        self.chk_audio.setChecked(True)
        layout.addRow(self.chk_audio)

        # Video (RunPod only)
        self.chk_video = QCheckBox("Enable Video Generation (RunPod only)")
        self.chk_video.setChecked(False)
        self.chk_video.setEnabled(False)  # Disabled by default
        self.chk_video.setToolTip("Video generation requires RunPod mode with cloud GPU")
        layout.addRow(self.chk_video)

        # No-media (disable all image/video generation, useful without GPU)
        self.chk_no_media = QCheckBox("Disabilita Media (no GPU)")
        self.chk_no_media.setChecked(False)
        self.chk_no_media.setToolTip(
            "Disabilita la generazione di immagini e video. "
            "Utile se non hai una GPU disponibile."
        )
        layout.addRow(self.chk_no_media)

        # Memory Settings Group
        memory_group = QGroupBox("🧠 Memory Settings")
        memory_layout = QFormLayout(memory_group)

        # Semantic memory toggle
        self.chk_semantic_memory = QCheckBox("Enable Smart Memory (Semantic Search)")
        self.chk_semantic_memory.setChecked(self.user_prefs.enable_semantic_memory)
        self.chk_semantic_memory.setToolTip(
            "Uses AI embeddings for better memory recall. "
            "Requires: pip install chromadb sentence-transformers"
        )
        self.chk_semantic_memory.stateChanged.connect(self._on_semantic_memory_changed)
        memory_layout.addRow(self.chk_semantic_memory)

        # Info label
        self.lbl_memory_info = QLabel()
        self.lbl_memory_info.setWordWrap(True)
        self.lbl_memory_info.setStyleSheet("color: #888; font-size: 11px;")
        memory_layout.addRow(self.lbl_memory_info)

        self._update_memory_info()
        main_layout.addWidget(memory_group)
        main_layout.addStretch()

        return tab

    def _update_memory_info(self) -> None:
        """Update memory info label."""
        if self.user_prefs.enable_semantic_memory:
            self.lbl_memory_info.setText(
                "✅ Smart Memory enabled: NPCs will remember contextually relevant things "
                "using AI-powered semantic search."
            )
        else:
            self.lbl_memory_info.setText(
                "ℹ️ Using standard memory (keyword-based). "
                "Enable Smart Memory for better contextual recall. "
                "Install requirements: pip install chromadb sentence-transformers"
            )

    def _on_semantic_memory_changed(self, state: int) -> None:
        """Handle semantic memory toggle."""
        enabled = state == Qt.CheckState.Checked.value
        self.user_prefs.enable_semantic_memory = enabled
        self._update_memory_info()

    def _on_execution_mode_changed(self, mode: str) -> None:
        """Handle execution mode change.
        
        Args:
            mode: New execution mode ("LOCAL" or "RUNPOD")
        """
        is_runpod = mode.upper() == "RUNPOD"
        self.chk_video.setEnabled(is_runpod)
        
        if not is_runpod:
            self.chk_video.setChecked(False)
            self.chk_video.setText("Enable Video Generation (RunPod only) 🚫")
        else:
            self.chk_video.setText("Enable Video Generation (RunPod only) ✅")

    def _load_worlds(self) -> None:
        """Load available worlds."""
        worlds = self.world_loader.list_worlds()

        self.combo_worlds.clear()
        for world in worlds:
            self.combo_worlds.addItem(
                f"{world['name']} ({world['genre']})",
                world['id']
            )

    def _load_settings(self) -> None:
        """Load saved settings."""
        # Load last used values
        last_world = self.user_prefs.last_world
        last_companion = self.user_prefs.last_companion

        if last_world:
            index = self.combo_worlds.findData(last_world)
            if index >= 0:
                self.combo_worlds.setCurrentIndex(index)
                # V4.1: After world selection triggers companion loading,
                # select the last companion
                if last_companion:
                    comp_index = self.combo_companions.findData(last_companion)
                    if comp_index >= 0:
                        self.combo_companions.setCurrentIndex(comp_index)
        
        # Load execution mode from settings
        current_mode = "RUNPOD" if self.settings.is_runpod else "LOCAL"
        mode_index = self.combo_mode.findText(current_mode)
        if mode_index >= 0:
            self.combo_mode.setCurrentIndex(mode_index)
        
        # Update video checkbox based on initial mode
        self._on_execution_mode_changed(self.combo_mode.currentText())

    async def _load_saves_async(self) -> None:
        """Load saved games from database (async version)."""
        from luna.core.database import get_db_session, get_db_manager
        
        try:
            async with get_db_session() as db:
                db_manager = get_db_manager()
                saves = await db_manager.list_saves(db)
                
                self.list_saves.clear()
                
                if not saves:
                    item = QListWidgetItem("Nessun salvataggio trovato")
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    self.list_saves.addItem(item)
                    return
                
                for save in saves:
                    session_id = save.get('session_id', 0)
                    name = save.get('name') or f"Salvataggio {session_id}"
                    companion = save.get('active_companion', 'unknown')
                    location = save.get('current_location', 'unknown')
                    turn_count = save.get('turn_count', 0)
                    updated_at = save.get('updated_at', 'unknown')
                    
                    # Format display text
                    display_text = f"📁 {name}\n"
                    display_text += f"   👤 {companion} | 📍 {location} | 🎲 Turno {turn_count}\n"
                    display_text += f"   🕐 {updated_at}"
                    
                    item = QListWidgetItem(display_text)
                    item.setData(Qt.UserRole, session_id)
                    self.list_saves.addItem(item)
                    
        except Exception as e:
            logger.error(f"[StartupDialog] Error loading saves: {e}")
            self.list_saves.clear()
            item = QListWidgetItem(f"Errore caricamento: {e}")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.list_saves.addItem(item)
    
    def _on_tab_changed(self, index: int) -> None:
        """Handle tab change.
        
        Args:
            index: New tab index
        """
        if index == 1:  # Load Game tab
            self._load_saves()
    
    def _load_saves(self) -> None:
        """Load saved games from database."""
        # Show loading message
        self.list_saves.clear()
        item = QListWidgetItem("⏳ Caricamento salvataggi...")
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.list_saves.addItem(item)
        
        # Use QTimer to allow UI to update before async call
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self._execute_load_saves)
    
    def _delete_all_saves(self) -> None:
        """Delete all saves with confirmation."""
        reply = QMessageBox.question(
            self,
            "⚠️ Conferma Eliminazione",
            "Sei sicuro di voler eliminare TUTTI i salvataggi?\n\n"
            f"Questa azione eliminerà tutti i dati di gioco salvati\n"
            "e non può essere annullata!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._execute_delete_all)
    
    def _execute_load_saves(self) -> None:
        """Execute the async save loading."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._load_saves_async())
            else:
                loop.run_until_complete(self._load_saves_async())
        except RuntimeError:
            # No event loop
            self.list_saves.clear()
            item = QListWidgetItem("❌ Errore: event loop non disponibile")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.list_saves.addItem(item)
    
    def _execute_delete_all(self) -> None:
        """Execute delete all saves."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._delete_all_saves_async())
            else:
                loop.run_until_complete(self._delete_all_saves_async())
        except RuntimeError:
            QMessageBox.critical(self, "Errore", "Event loop non disponibile")
    
    async def _delete_all_saves_async(self) -> None:
        """Async delete all saves."""
        from luna.core.database import get_db_session, get_db_manager
        
        try:
            async with get_db_session() as db:
                db_manager = get_db_manager()
                deleted_count = await db_manager.delete_all_saves(db)
                
                QMessageBox.information(
                    self,
                    "Completato",
                    f"Eliminati {deleted_count} salvataggi.\n\n"
                    "La lista verrà aggiornata."
                )
                
                # Refresh the list
                await self._load_saves_async()
                
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Errore durante l'eliminazione: {e}")

    def _on_world_changed(self, index: int) -> None:
        """Handle world selection change."""
        world_id = self.combo_worlds.itemData(index)
        if not world_id:
            return

        world = self.world_loader.load_world(world_id)
        if world:
            self.lbl_world_desc.setText(
                f"<b>{world.name}</b><br/>{world.description}"
            )

            # Update companions
            self.combo_companions.clear()
            companion_count = 0
            for name, companion in world.companions.items():
                # Skip temporary NPCs
                if getattr(companion, 'is_temporary', False):
                    continue
                self.combo_companions.addItem(
                    f"{name} - {companion.role}", name
                )
                companion_count += 1
            
            # V4.1: Show message if no companions available
            if companion_count == 0:
                self.combo_companions.addItem("⚠️ Nessuna companion disponibile", None)
                self.lbl_companion_desc.setText(
                    "<span style='color: #ff6b6b;'>Questo mondo non ha companion principali definite.</span>"
                )

    def _on_start(self) -> None:
        """Handle start button."""
        current_tab = self.tabs.currentIndex()

        if current_tab == 0:  # New Game
            self.selected_world_id = self.combo_worlds.currentData()
            self.selected_companion = self.combo_companions.currentData()
            self.mode = "new"

            if not self.selected_world_id or not self.selected_companion:
                QMessageBox.warning(
                    self, "Selection Required",
                    "Please select a world and companion."
                )
                return

            # Save preferences
            self.user_prefs.last_world = self.selected_world_id
            self.user_prefs.last_companion = self.selected_companion

        elif current_tab == 1:  # Load Game
            item = self.list_saves.currentItem()
            if item:
                self.selected_session_id = item.data(Qt.UserRole)
                self.mode = "load"
            else:
                QMessageBox.warning(
                    self, "Selection Required",
                    "Please select a saved game."
                )
                return

        elif current_tab == 2:  # Settings only
            self._save_settings()
            return
        
        # Save execution mode and RunPod ID
        self._save_execution_settings()

        self.accept()
    
    def _save_execution_settings(self) -> None:
        """Save execution mode and RunPod settings."""
        # Save to user preferences
        execution_mode = self.combo_mode.currentText()
        self.user_prefs.execution_mode = execution_mode
        
        runpod_id = self.edit_runpod_id.text().strip()
        if runpod_id:
            self.user_prefs.runpod_id = runpod_id
        
        logger.debug(f"[StartupDialog] Saved execution mode: {execution_mode}")
        if runpod_id:
            logger.debug(f"[StartupDialog] Saved RunPod ID: {runpod_id}")

    def _save_settings(self) -> None:
        """Save settings."""
        # Memory settings are already saved via checkbox signal
        QMessageBox.information(
            self, "Settings Saved",
            "Settings have been saved.\n\n"
            f"Smart Memory: {'Enabled' if self.user_prefs.enable_semantic_memory else 'Disabled'}"
        )

    def get_selection(self) -> dict:
        """Get selected options."""
        return {
            "mode": self.mode,
            "world_id": self.selected_world_id,
            "companion": self.selected_companion,
            "session_id": self.selected_session_id,
            "execution_mode": self.combo_mode.currentText(),
            "runpod_id": self.edit_runpod_id.text().strip(),
            "no_media": self.chk_no_media.isChecked(),
        }
