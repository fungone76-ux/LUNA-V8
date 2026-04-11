"""Luna RPG - Media Manager.

Handles save/load, audio playback and video generation.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from qasync import asyncSlot
from PySide6.QtWidgets import QMessageBox, QProgressDialog
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from .main_window import MainWindow

logger = logging.getLogger(__name__)


class MediaManager:
    """Manages save/load, audio and video."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window

    # ------------------------------------------------------------------
    # Save / Load
    # ------------------------------------------------------------------

    @asyncSlot()
    async def _on_save(self) -> None:
        """Save game to database with custom name."""
        w = self.window
        logger.debug("[MainWindow] Save button clicked")

        if not w.engine or not w.engine.state_manager.is_loaded:
            QMessageBox.warning(w, "Save", "No game to save!")
            return

        state = w.engine.get_game_state()
        companion = state.active_companion
        location = state.current_location
        turn = state.turn_count
        default_name = f"{companion} - {location} (Turn {turn})"

        from luna.ui.save_dialog import SaveDialog
        save_name, accepted = SaveDialog.get_save_name_dialog(default_name, w)

        if not accepted:
            logger.debug("[MainWindow] Save cancelled by user")
            return

        if not save_name:
            save_name = default_name

        try:
            from luna.core.database import get_db_session
            current_loc = w.engine.get_game_state().current_location
            logger.debug(f"[Save] Current location before save: {current_loc}")
            async with get_db_session() as db:
                success = await w.engine.state_manager.save(db, name=save_name)
                if success:
                    session_id = w.engine.state_manager.current.session_id
                    w.statusbar.showMessage(f"💾 Salvato: {save_name}", 5000)
                    w.feedback.success("💾 Salvato", f"'{save_name}' salvato!")
                    logger.debug(f"[MainWindow] Game saved: '{save_name}' (ID: {session_id})")
                else:
                    QMessageBox.critical(w, "Save Error", "Failed to save game!")
        except Exception as e:
            logger.error(f"[Save Error] {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(w, "Save Error", f"Error saving: {str(e)}")

    async def _handle_delete_save(self, session_id: int) -> None:
        """Handle save deletion with async database operations."""
        w = self.window
        from luna.core.database import get_db_session, get_db_manager

        try:
            async with get_db_session() as db:
                db_manager = get_db_manager()
                success = await db_manager.delete_save(db, session_id)

                if success:
                    QMessageBox.information(w, "Eliminato", f"Salvataggio {session_id} eliminato con successo.")
                    await self._on_load()
                else:
                    QMessageBox.warning(w, "Errore", "Salvataggio non trovato.")
        except Exception as e:
            QMessageBox.critical(w, "Errore", f"Errore durante l'eliminazione: {e}")

    @asyncSlot()
    async def _on_load(self) -> None:
        """Load game from database."""
        w = self.window
        logger.debug("[MainWindow] Load button clicked")

        from luna.core.database import get_db_session, get_db_manager
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout,
            QListWidget, QListWidgetItem, QLabel, QPushButton
        )

        try:
            async with get_db_session() as db:
                db_manager = get_db_manager()
                saves = await db_manager.list_saves(db)
        except Exception as e:
            QMessageBox.warning(w, "Load Error", f"Could not load save list: {e}")
            return

        if not saves:
            QMessageBox.information(w, "No Saves", "Nessun salvataggio trovato!")
            return

        dialog = QDialog(w)
        dialog.setWindowTitle("📂 Carica Partita")
        dialog.setMinimumSize(500, 400)

        layout = QVBoxLayout(dialog)

        title_lbl = QLabel("Seleziona un salvataggio:")
        title_lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_lbl)

        list_widget = QListWidget()
        list_widget.setStyleSheet("""
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
            QListWidget::item:selected { background-color: #E91E63; }
            QListWidget::item:hover { background-color: #444; }
        """)

        save_map = {}
        for i, save in enumerate(saves):
            session_id = save.get('session_id', i)
            name = save.get('name') or f"Salvataggio {session_id}"
            companion = save.get('active_companion', 'unknown')
            location = save.get('current_location', 'unknown')
            turn_count = save.get('turn_count', 0)
            updated_at = save.get('updated_at', 'unknown')

            display_text = f"📁 {name}\n"
            display_text += f"   👤 {companion} | 📍 {location} | 🎲 Turno {turn_count}\n"
            display_text += f"   🕐 {updated_at}"

            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, session_id)
            list_widget.addItem(item)
            save_map[i] = save

        layout.addWidget(list_widget)

        info = QLabel(f"Trovati {len(saves)} salvataggi")
        info.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(info)

        btn_layout = QHBoxLayout()

        btn_load = QPushButton("📂 Carica")
        btn_load.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white;
                padding: 8px 16px; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #555; }
        """)
        btn_load.setEnabled(False)

        btn_cancel = QPushButton("❌ Annulla")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #666; color: white;
                padding: 8px 16px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #777; }
        """)

        btn_delete = QPushButton("🗑️ Elimina")
        btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #f44336; color: white;
                padding: 8px 16px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #d32f2f; }
            QPushButton:disabled { background-color: #555; }
        """)
        btn_delete.setEnabled(False)
        btn_delete.setToolTip("Elimina permanentemente il salvataggio selezionato")

        btn_layout.addWidget(btn_load)
        btn_layout.addWidget(btn_delete)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        selected_session_id = [None]

        def on_selection_changed():
            current = list_widget.currentItem()
            if current:
                selected_session_id[0] = current.data(Qt.UserRole)
                btn_load.setEnabled(True)
                btn_delete.setEnabled(True)
            else:
                selected_session_id[0] = None
                btn_load.setEnabled(False)
                btn_delete.setEnabled(False)

        def on_double_click(item):
            selected_session_id[0] = item.data(Qt.UserRole)
            dialog.accept()

        delete_requested = [False]
        session_to_delete = [None]

        def on_delete_clicked():
            current = list_widget.currentItem()
            if not current:
                return

            session_id_to_delete = current.data(Qt.UserRole)
            save_name = save_map.get(list_widget.row(current), {}).get(
                'name', f'Salvataggio {session_id_to_delete}'
            )

            reply = QMessageBox.question(
                dialog,
                "Conferma Eliminazione",
                f'Sei sicuro di voler eliminare "{save_name}"?\n\nQuesta azione è irreversibile!',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                delete_requested[0] = True
                session_to_delete[0] = session_id_to_delete
                dialog.reject()

        list_widget.itemSelectionChanged.connect(on_selection_changed)
        list_widget.itemDoubleClicked.connect(on_double_click)
        btn_load.clicked.connect(dialog.accept)
        btn_cancel.clicked.connect(dialog.reject)
        btn_delete.clicked.connect(on_delete_clicked)

        result = dialog.exec()

        if delete_requested[0] and session_to_delete[0] is not None:
            await self._handle_delete_save(session_to_delete[0])
            return

        if result != QDialog.Accepted or selected_session_id[0] is None:
            return

        session_id = selected_session_id[0]

        try:
            from luna.core.database import get_db_session, get_db_manager
            from luna.core.engine import GameEngine

            async with get_db_session() as db:
                from luna.core.state import StateManager
                db_manager = get_db_manager()
                temp_manager = StateManager(db_manager)
                state = await temp_manager.load(db, session_id)

                if not state:
                    QMessageBox.warning(w, "Load Error", f"No save found in slot {session_id}!")
                    return

                if w.engine:
                    w.engine = None

                w.engine = GameEngine(state.world_id, state.active_companion)

                await w.engine.initialize()

                w.engine.state_manager._current = state

                session_model = await db_manager.get_session(db, session_id)
                if session_model and session_model.personality_state:
                    try:
                        from luna.systems.personality import PersonalityState
                        personality_data = session_model.personality_state
                        states_list = personality_data.get("states", [])
                        personality_states = [
                            PersonalityState(**state_data)
                            for state_data in states_list
                        ]
                        w.engine.personality_engine.load_states(personality_states)
                        logger.debug(f"[Load] Loaded {len(personality_states)} personality states")
                    except Exception as e:
                        logger.error(f"[Load] Error loading personality states: {e}")

                from luna.core.models import QuestInstance, QuestStatus
                quest_state_models = await db_manager.get_all_quest_states(db, session_id)
                quest_instances = []
                for qm in quest_state_models:
                    try:
                        instance = QuestInstance(
                            quest_id=qm.quest_id,
                            status=QuestStatus(qm.status) if isinstance(qm.status, str) else qm.status,
                            current_stage_id=qm.current_stage_id,
                            stage_data=qm.stage_data or {},
                            started_at=qm.started_at,
                            completed_at=qm.completed_at,
                        )
                        quest_instances.append(instance)
                    except Exception as e:
                        logger.error(f"[Load] Error loading quest state {qm.quest_id}: {e}")
                w.engine.quest_engine.load_instances({qi.quest_id: qi for qi in quest_instances})
                logger.debug(f"[Load] Loaded {len(quest_instances)} quest states")

                game_state = w.engine.get_game_state()

                for comp_name, outfit_state in state.companion_outfits.items():
                    game_state.companion_outfits[comp_name] = outfit_state

                for npc_name, npc_state in state.npc_states.items():
                    game_state.npc_states[npc_name] = npc_state

                game_state.affinity = state.affinity
                game_state.flags = state.flags
                game_state.active_quests = state.active_quests
                game_state.completed_quests = state.completed_quests

                saved_companion = state.active_companion
                world_companions = list(w.engine.world.companions.keys()) if w.engine.world else []

                if saved_companion and saved_companion not in world_companions and saved_companion != "_solo_":
                    logger.warning(f"[Load] WARNING: Saved companion '{saved_companion}' not found in world (temporary NPC?), resetting to _solo_")
                    if saved_companion in game_state.affinity:
                        del game_state.affinity[saved_companion]
                        logger.debug(f"[Load] Removed temporary NPC '{saved_companion}' from affinity")
                    game_state.active_companion = "_solo_"
                    w.engine.companion = "_solo_"
                else:
                    game_state.active_companion = saved_companion
                    w.engine.companion = saved_companion

                logger.debug(f"[Load] Restored companion: {game_state.active_companion}")

                world_companion_names = set(w.engine.world.companions.keys()) if w.engine.world else set()
                world_companion_names.add("_solo_")

                affinity_to_remove = []
                for name in list(game_state.affinity.keys()):
                    if name not in world_companion_names:
                        affinity_to_remove.append(name)

                for name in affinity_to_remove:
                    del game_state.affinity[name]
                    logger.debug(f"[Load] Cleaned up temporary NPC from affinity: {name}")

                if affinity_to_remove:
                    logger.debug(f"[Load] Total temporary NPCs cleaned: {len(affinity_to_remove)}")

                game_state.current_location = state.current_location
                logger.debug(f"[Load] Restored location: {state.current_location}")

                if w.engine.location_manager:
                    current_loc = w.engine.location_manager.get_current_location()
                    logger.debug(f"[Load] Location manager current: {current_loc.name if current_loc else 'None'}")
                    w.engine.location_manager.refresh_after_load()

                if w.engine.event_manager:
                    w.engine.event_manager.on_event_changed = w.display_manager.on_event_changed
                    primary_event = w.engine.event_manager.get_primary_event()
                    if primary_event:
                        logger.debug(f"[Load] Restoring active event: {primary_event.name}")
                        w.display_manager.on_event_changed(primary_event)
                    else:
                        w.event_widget.set_event()

                if w.engine:
                    w.engine.set_ui_time_change_callback(w.display_manager.on_time_change)

                w.display_manager.update_all_widgets()
                w.story_log.clear()

                w.story_log.append_system_message(
                    f"Game loaded from slot {session_id}!\n"
                    f"   Turn: {state.turn_count} | Location: {state.current_location}\n"
                    f"   Companion: {state.active_companion}"
                )

                w.statusbar.showMessage(f"Loaded slot {session_id}", 3000)
                w.feedback.success("📂 Caricato", f"Partita caricata (ID: {session_id})")

        except Exception as e:
            logger.error(f"[Load Error] {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(w, "Load Error", f"Error loading: {str(e)}")

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def _play_audio(self, audio_path: str) -> None:
        """Play audio file."""
        w = self.window
        if not w.act_audio.isChecked():
            return

        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()

            pygame.mixer.music.load(audio_path)
            pygame.mixer.music.play()

        except Exception as e:
            logger.error(f"[MainWindow] Audio playback failed: {e}")

    # ------------------------------------------------------------------
    # Video
    # ------------------------------------------------------------------

    def _generate_video(self, image_path: str, user_action: str, character_name: str) -> None:
        """Generate video from image (kicks off async task)."""
        w = self.window
        progress = QProgressDialog(
            "🎬 Generazione video in corso...\n\n"
            f"Azione: {user_action}\n\n"
            "Questo processo richiede ~5-7 minuti.",
            "Annulla",
            0, 0, w,
        )
        progress.setWindowTitle("Generazione Video")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.show()

        asyncio.create_task(
            self._generate_video_async(image_path, user_action, character_name, progress)
        )

    async def _generate_video_async(
        self,
        image_path: str,
        user_action: str,
        character_name: str,
        progress: QProgressDialog,
    ) -> None:
        """Async video generation."""
        w = self.window
        try:
            from luna.media.video_client import VideoClient

            video_client = VideoClient()

            video_path = await video_client.generate_video(
                image_path=Path(image_path),
                user_action=user_action,
                character_name=character_name,
            )

            progress.close()

            if video_path:
                QMessageBox.information(
                    w, "Video Generato!", f"🎬 Video salvato in:\n{video_path}"
                )
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(video_path)))
            else:
                QMessageBox.warning(w, "Errore", "Impossibile generare il video.")

        except Exception as e:
            progress.close()
            QMessageBox.critical(w, "Errore", f"Errore durante la generazione video:\n{str(e)}")
