"""Luna RPG - Event Handler.

Handles all UI event handlers and user interaction callbacks.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from qasync import asyncSlot
from PySide6.QtWidgets import QMessageBox, QInputDialog
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from .main_window import MainWindow

logger = logging.getLogger(__name__)


class EventHandler:
    """Processes all UI events and user interactions."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window

    # ------------------------------------------------------------------
    # MultiNPC callbacks
    # ------------------------------------------------------------------

    def _on_interrupt_multi_npc(self) -> None:
        """User clicked interrupt button during MultiNPC sequence."""
        w = self.window
        if w.engine and w.engine.state_manager:
            w.engine.state_manager.current.flags["_user_interrupt_multi_npc"] = True
            w.engine.state_manager.current.flags["_user_interrupt_requested"] = True

            w.btn_interrupt.setEnabled(False)
            w.btn_interrupt.setText("⏹ Interrompendo...")
            w.lbl_status.setText("Interruzione richiesta...")

            logger.info("[UI] MultiNPC interruption requested by user")

    def show_interrupt_button(self, show: bool) -> None:
        """Show or hide the interrupt button."""
        w = self.window
        if show:
            w.btn_interrupt.show()
            w.btn_interrupt.setEnabled(True)
            w.btn_interrupt.setText("⏹ Interrompi")
            w.lbl_status.setText("⏵ Conversazione MultiNPC in corso...")
        else:
            w.btn_interrupt.hide()
            w.btn_interrupt.setEnabled(True)
            w.btn_interrupt.setText("⏹ Interrompi")
            if "MultiNPC" in w.lbl_status.text():
                w.lbl_status.setText("Ready")

    async def on_intermediate_npc_message(
        self,
        text: str,
        speaker: str,
        turn_number: int,
        visual_en: str = "",
        tags_en: Optional[list] = None,
    ) -> None:
        """Display intermediate NPC message immediately."""
        from PySide6.QtWidgets import QApplication
        w = self.window
        # Suppress all intermediate NPC messages during poker
        if w.engine and w.engine.state and w.engine.state.flags.get("poker_active"):
            return
        w.story_log.append_npc_message(speaker, text)
        w.story_log.scroll_to_bottom()
        QApplication.processEvents()

    def on_intermediate_image(self, image_path: str) -> None:
        """Display intermediate image."""
        from pathlib import Path
        from PySide6.QtWidgets import QApplication
        w = self.window
        if image_path and Path(image_path).exists():
            w.image_display.set_image(image_path)
            QApplication.processEvents()

    # ------------------------------------------------------------------
    # Action bar
    # ------------------------------------------------------------------

    @asyncSlot()
    async def _on_action_triggered(self, action_id: str, target: str) -> None:
        """Handle action button click."""
        w = self.window
        if not w.engine:
            return

        w.btn_send.setEnabled(False)
        w.lbl_status.setText(f"Executing: {action_id}...")

        try:
            result = w.engine.execute_action(action_id, target)

            if result.success:
                if result.message:
                    w.story_log.append_system_message(result.message)

                for char, amount in result.affinity_changes.items():
                    if amount != 0:
                        current_aff = (
                            w.engine.gameplay_manager.affinity.get_affinity(char)
                            if w.engine.gameplay_manager.affinity else 0
                        )
                        w.feedback.affinity_change(char, amount, current_aff)
                        w.companion_status.update_companion(char, current_aff, "", "😐")

                        if w.engine.gameplay_manager.affinity:
                            tier = w.engine.gameplay_manager.affinity.get_tier(char)
                            if hasattr(tier, 'name'):
                                w.feedback.tier_unlocked(char, tier.name)

                for item in result.items_gained:
                    w.story_log.append_system_message(f"📦 Received: {item.name}")

                if result.money_change != 0:
                    icon = "💰" if result.money_change > 0 else "💸"
                    w.story_log.append_system_message(
                        f"{icon} Money: {'+' if result.money_change > 0 else ''}{result.money_change}"
                    )

                w.display_manager.update_action_bars()
            else:
                w.story_log.append_system_message(f"❌ {result.message}")

        except Exception as e:
            logger.error(f"[MainWindow] Action execution failed: {e}")
            w.story_log.append_system_message(f"❌ Error: {str(e)}")

        finally:
            w.btn_send.setEnabled(True)
            w.lbl_status.setText("Ready")

    # ------------------------------------------------------------------
    # Audio / video toggles
    # ------------------------------------------------------------------

    def _on_toggle_audio(self, checked: bool) -> None:
        """Toggle audio on/off."""
        w = self.window
        if w.engine:
            w.engine.toggle_audio()
        w.act_audio.setText("🔊 Audio" if checked else "🔇 Audio")

    def _on_toggle_video(self) -> None:
        """Handle video button click."""
        from luna.core.config import get_settings
        w = self.window
        settings = get_settings()

        if not settings.is_runpod:
            w.act_video.setChecked(False)
            QMessageBox.information(
                w,
                "Video Non Disponibile",
                "🎬 La generazione video è disponibile solo in modalità RunPod.\n\n"
                "Vai in Settings → Execution Mode e seleziona RUNPOD"
            )
            return

        if not w.engine:
            QMessageBox.warning(w, "Errore", "Gioco non inizializzato")
            return

        import os
        from pathlib import Path

        images_dir = Path("storage/images")
        if images_dir.exists():
            image_files = sorted(images_dir.glob("*.png"), key=os.path.getmtime, reverse=True)
            if image_files:
                current_image = str(image_files[0])
                from luna.ui.video_dialog import VideoGenerationDialog

                game_state = w.engine.get_game_state()
                dialog = VideoGenerationDialog(
                    image_path=current_image,
                    character_name=game_state.active_companion,
                    parent=w,
                )

                if dialog.exec() == VideoGenerationDialog.Accepted:
                    user_action = dialog.get_action()
                    if user_action:
                        w.media_manager._generate_video(current_image, user_action, game_state.active_companion)
                return

        QMessageBox.warning(w, "Nessuna Immagine", "Genera prima un'immagine.")

    # ------------------------------------------------------------------
    # New game
    # ------------------------------------------------------------------

    @asyncSlot()
    async def _on_new_game(self) -> None:
        """Start a new game."""
        w = self.window
        logger.debug("[MainWindow] New Game button clicked")

        reply = QMessageBox.question(
            w, "New Game",
            "Start a new game?\n\nCurrent progress will be lost unless saved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if w.engine and hasattr(w.engine, '_session_id') and w.engine._session_id:
                old_session_id = w.engine._session_id
                logger.debug(f"[MainWindow] Cleaning up old session {old_session_id} before new game...")
                try:
                    if w.engine.memory_manager and hasattr(w.engine.memory_manager, '_semantic_store'):
                        if w.engine.memory_manager._semantic_store:
                            w.engine.memory_manager._semantic_store.delete_session()
                            logger.debug(f"[MainWindow] Deleted semantic memory for session {old_session_id}")
                except Exception as e:
                    logger.warning(f"[MainWindow] Warning: Could not delete semantic memory: {e}")

            if w.engine:
                w.engine = None

            w.story_log.clear()
            w.display_manager.update_all_widgets()

            from luna.ui.startup_dialog import StartupDialog
            from luna.core.config import reload_settings

            dialog = StartupDialog()
            result = await self._show_dialog_async(dialog)

            if result:
                selection = dialog.get_selection()
                world_id = selection.get("world_id")
                companion = selection.get("companion")

                if not world_id or not companion:
                    QMessageBox.warning(w, "Error", "Please select world and companion!")
                    return

                reload_settings()
                await w.initialize_game(world_id, companion, session_id=None)
                w.feedback.success("🎮 Nuova Partita", "Nuova partita iniziata!")

        except Exception as e:
            logger.error(f"[New Game Error] {e}")
            QMessageBox.critical(w, "Error", f"Failed to start new game: {str(e)}")

    async def _show_dialog_async(self, dialog) -> bool:
        """Helper to show a dialog asynchronously."""
        future: asyncio.Future = asyncio.get_event_loop().create_future()

        def on_accepted():
            if not future.done():
                future.set_result(True)

        def on_rejected():
            if not future.done():
                future.set_result(False)

        dialog.accepted.connect(on_accepted)
        dialog.rejected.connect(on_rejected)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

        return await future

    # ------------------------------------------------------------------
    # Settings / debug / LoRA
    # ------------------------------------------------------------------

    def _on_settings(self) -> None:
        """Open settings."""
        QMessageBox.information(self.window, "Settings", "Settings coming soon!")

    def _on_open_debug(self) -> None:
        """Open debug panel."""
        from luna.ui.debug_panel import DebugPanelWindow
        w = self.window
        if not hasattr(w, '_debug_window') or w._debug_window is None:
            w._debug_window = DebugPanelWindow(w)

        if w.engine:
            w._debug_window.set_engine(w.engine)

        w._debug_window.show()
        w._debug_window.raise_()
        w._debug_window.activateWindow()

    def _on_toggle_lora(self, checked: bool) -> None:
        """Toggle LoRA mapping on/off."""
        w = self.window
        if hasattr(w, 'lora_mapping'):
            w.lora_mapping.set_enabled(checked)
            if w.engine and hasattr(w.engine, 'lora_mapping'):
                w.engine.lora_mapping.set_enabled(checked)
            if w._lora_toggle_action:
                status = "ON" if checked else "OFF"
                w._lora_toggle_action.setText(f"🎭 LoRA {status}")
                if checked:
                    w._lora_toggle_action.setToolTip("LoRA attivi - Click per disattivare")
                else:
                    w._lora_toggle_action.setToolTip("LoRA disattivati - Click per attivare")

    # ------------------------------------------------------------------
    # Time / phase controls
    # ------------------------------------------------------------------

    def _on_advance_time(self) -> None:
        """Advance time of day."""
        from luna.core.models import TimeOfDay
        w = self.window
        if not w.engine:
            return

        new_time = w.engine.state_manager.advance_time()
        w.display_manager.update_status()
        w.display_manager.update_companion_locator()

        time_names = {
            TimeOfDay.MORNING: "A new day begins... ☀️",
            TimeOfDay.AFTERNOON: "The sun climbs higher... 🌅",
            TimeOfDay.EVENING: "The day draws to a close... 🌆",
            TimeOfDay.NIGHT: "Night falls... 🌙",
        }

        if hasattr(new_time, 'value'):
            time_str = new_time.value
        else:
            time_str = str(new_time)

        try:
            time_enum = TimeOfDay(time_str) if isinstance(time_str, str) else new_time
        except ValueError:
            time_enum = TimeOfDay.MORNING

        message = time_names.get(time_enum, f"Time passes... {time_str}")
        w.story_log.append_system_message(message)

    def _on_freeze_turns(self) -> None:
        """Freeze turn counting."""
        w = self.window
        if not w.engine or not w.engine.phase_manager:
            return
        w.engine.phase_manager.freeze()
        w.display_manager.update_status()
        w.story_log.append_system_message("⏸️ Turn counting paused - Phase time is frozen")
        w.feedback.info("⏸️ Pausa", "Turn counting paused")

    def _on_unfreeze_turns(self) -> None:
        """Unfreeze turn counting."""
        w = self.window
        if not w.engine or not w.engine.phase_manager:
            return
        w.engine.phase_manager.unfreeze()
        w.display_manager.update_status()
        w.story_log.append_system_message("▶️ Turn counting resumed - Phase time advances normally")
        w.feedback.success("▶️ Riprendi", "Turn counting resumed")

    @asyncSlot()
    async def _on_advance_phase(self) -> None:
        """v8: Pulsante 'Avanza Fase' — mostra preview, conferma, esegue cambio fase."""
        w = self.window
        if not w.engine:
            return

        # 1. Preview sincrona — chi si sposta dove
        preview = w.engine.preview_phase_advance()
        if not preview:
            QMessageBox.warning(w, "Errore", "Impossibile calcolare il cambio fase.")
            return

        # 2. Costruisci messaggio di conferma
        phase_names = {
            "Morning": "Mattina ☀️",
            "Afternoon": "Pomeriggio 🌅",
            "Evening": "Sera 🌆",
            "Night": "Notte 🌙",
        }
        next_phase_name = phase_names.get(str(preview.next_phase), str(preview.next_phase))

        msg_lines = [f"Passare a <b>{next_phase_name}</b>?<br><br>"]
        
        if preview.movements:
            msg_lines.append("<b>Spostamenti NPC:</b><ul>")
            for m in preview.movements:
                if m.is_active_companion:
                    msg_lines.append(f"<li>⚠️ <b>{m.npc_name}</b> lascerà la scena → {m.to_location}</li>")
                else:
                    msg_lines.append(f"<li>{m.npc_name}: {m.from_location} → {m.to_location}</li>")
            msg_lines.append("</ul>")
        else:
            msg_lines.append("Nessun NPC si sposterà.<br>")

        if preview.active_companion_leaves:
            msg_lines.append("<br><i>Il companion attivo ti saluterà prima di andare.</i>")

        # 3. Dialogo di conferma
        reply = QMessageBox.question(
            w, "Conferma cambio fase",
            "".join(msg_lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # 4. Esegui avanzamento fase (async con LLM se c'è farewell)
        w.lbl_status.setText("Avanzamento fase...")
        try:
            result = await w.engine.advance_phase()
            
            # 5. Mostra risultato (farewell) nella chat
            if result and result.text:
                w.display_manager.display_result(result)
            else:
                # Nessun farewell (companion non lascia)
                w.story_log.append_system_message(f"🌅 Fase avanzata a {next_phase_name}")
            
            # Aggiorna UI
            w.display_manager.update_status()
            w.display_manager.update_companion_locator()
            w.feedback.success("🌅 Fase avanzata", f"Ora è {next_phase_name}")
            
        except Exception as e:
            logger.error(f"[Advance Phase Error] {e}")
            QMessageBox.critical(w, "Errore", f"Impossibile avanzare la fase: {str(e)}")
            w.lbl_status.setText("Errore cambio fase")

    # ------------------------------------------------------------------
    # Outfit management
    # ------------------------------------------------------------------

    @asyncSlot()
    async def _on_change_outfit(self) -> None:
        """Handle 'Cambia' button — change to random outfit."""
        w = self.window
        if not w.engine:
            return

        game_state = w.engine.get_game_state()
        companion_def = w.engine.world.companions.get(game_state.active_companion)

        if not companion_def:
            return

        new_outfit = w.engine.outfit_modifier.change_random_outfit(game_state, companion_def)

        if new_outfit:
            w.display_manager.update_outfit_widget()
            w.feedback.info("👗 Outfit Cambiato", f"Luna indossa ora: {new_outfit}")
            logger.debug(f"[MainWindow] Random outfit changed to: {new_outfit}")

            w.lbl_status.setText("Generazione immagine...")
            image_path = await w.engine.generate_image_after_outfit_change()

            if image_path:
                from pathlib import Path
                img_path = Path(image_path)
                if img_path.exists():
                    w.image_display.set_image(str(img_path))
                    w.feedback.info("🖼️ Immagine Aggiornata", "Outfit cambiato visualizzato")

            w.lbl_status.setText("Ready")

    @asyncSlot()
    async def _on_modify_outfit(self) -> None:
        """Handle 'Modifica' button — custom outfit description."""
        w = self.window
        if not w.engine:
            return

        text, ok = QInputDialog.getText(
            w,
            "Modifica Outfit",
            "Descrivi l'outfit che vuoi (in italiano):\n\n"
            "Esempi:\n"
            "• vestito da sera rosso\n"
            "• pigiama con orsetti\n"
            "• bikini blu\n"
            "• solo intimo nero",
        )

        if not ok or not text.strip():
            return

        game_state = w.engine.get_game_state()

        try:
            description_en = await w.engine.outfit_modifier.change_custom_outfit(
                game_state,
                text.strip(),
                w.engine.llm_manager,
            )

            w.display_manager.update_outfit_widget()
            w.feedback.info("👗 Outfit Modificato", f"Nuovo outfit: {text[:30]}...")
            logger.debug(f"[MainWindow] Custom outfit: {text} -> {description_en}")

            w.lbl_status.setText("Generazione immagine...")
            image_path = await w.engine.generate_image_after_outfit_change()

            if image_path:
                from pathlib import Path
                img_path = Path(image_path)
                if img_path.exists():
                    w.image_display.set_image(str(img_path))
                    w.feedback.info("🖼️ Immagine Aggiornata", "Outfit modificato visualizzato")

            w.lbl_status.setText("Ready")

        except Exception as e:
            QMessageBox.warning(w, "Errore", f"Impossibile modificare outfit: {e}")

    # ------------------------------------------------------------------
    # Quest management
    # ------------------------------------------------------------------

    def _on_quest_activate_requested(self, quest_id: str) -> None:
        """Handle user clicking to activate a quest."""
        if not self.window.engine:
            return
        asyncio.create_task(self._activate_quest_async(quest_id))

    async def _activate_quest_async(self, quest_id: str) -> None:
        """Async activate quest."""
        w = self.window
        try:
            game_state = w.engine.get_game_state()
            result = w.engine.quest_engine.activate_quest(quest_id, game_state)

            if result:
                w.feedback.success("🎯 Quest Attivata!", f"Hai attivato: {result.title}")
                w.story_log.append_system_message(f"📜 Quest attivata: {result.title}")
                w.display_manager.update_quest_tracker()
            else:
                quest_def = w.engine.world.quests.get(quest_id)
                if quest_def:
                    w.feedback.info(
                        "ℹ️ Quest non ancora disponibile",
                        f"{quest_def.title} richiede condizioni specifiche"
                    )

        except Exception as e:
            logger.error(f"[Quest Activation] Error: {e}")
            w.feedback.error("Errore", f"Impossibile attivare quest: {e}")

    # ------------------------------------------------------------------
    # Choice system
    # ------------------------------------------------------------------

    def _check_pending_quest_choices(self) -> None:
        """Check for quests awaiting player choice and show dialog."""
        w = self.window
        if not w.engine:
            return

        pending = w.engine.get_pending_quest_choices()
        for choice_data in pending:
            if w.choice_widget.is_active():
                break

            quest_id = choice_data["quest_id"]
            title = choice_data["title"]
            description = choice_data["description"]
            giver = choice_data["giver"]

            logger.debug(f"[MainWindow] Showing pending quest choice: {quest_id}")

            w._current_choice_quest_id = quest_id
            w._input_blocked = True
            w.txt_input.setEnabled(False)
            w.btn_send.setEnabled(False)
            w.txt_input.setPlaceholderText("⛔ Scegli un'opzione sopra...")

            w.choice_widget.show_quest_acceptance(
                quest_title=title,
                quest_description=description,
                giver_name=giver,
            )

            break

    @asyncSlot()
    async def _on_choice_made(self, choice_id: str) -> None:
        """Handle player making a choice."""
        w = self.window
        logger.debug(f"[Choice] Player selected: {choice_id}")

        is_accept = choice_id in ("accept", "yes")
        is_decline = choice_id in ("decline", "no")

        if hasattr(w, '_current_choice_quest_id') and w._current_choice_quest_id:
            if w.engine and (is_accept or is_decline):
                w.lbl_status.setText(f"Processing choice: {choice_id}...")

                quest_title = await w.engine.resolve_quest_choice(
                    w._current_choice_quest_id,
                    accepted=is_accept,
                )

                if quest_title and is_accept:
                    w.feedback.success("Quest Accettata!", f"Hai accettato: {quest_title}")
                    w.story_log.append_system_message(f"📜 Quest accettata: {quest_title}")
                elif is_decline:
                    w.feedback.info("Quest Rifiutata", "Hai rifiutato la missione")
                    w.story_log.append_system_message("❌ Quest rifiutata")

                w.display_manager.update_quest_tracker()
                w._current_choice_quest_id = None
        else:
            if w.engine:
                choice_text = self._choice_to_text(choice_id)
                await w.game_controller._process_choice_turn(choice_text)

        if hasattr(w, '_current_dynamic_event'):
            w._current_dynamic_event = None

        w._input_blocked = False
        w.txt_input.setEnabled(True)
        w.btn_send.setEnabled(True)
        w.txt_input.setPlaceholderText("Scrivi qui il tuo messaggio...")
        w.txt_input.setFocus()

    def _on_choice_cancelled(self) -> None:
        """Handle player cancelling choice."""
        w = self.window
        logger.debug("[Choice] Player cancelled")

        if hasattr(w, '_current_dynamic_event'):
            w._current_dynamic_event = None

        w._input_blocked = False
        w.txt_input.setEnabled(True)
        w.btn_send.setEnabled(True)
        w.txt_input.setPlaceholderText("Scrivi qui il tuo messaggio...")
        w.lbl_status.setText("Ready")

    def _choice_to_text(self, choice_id: str) -> str:
        """Convert choice ID to text command."""
        choice_map = {
            "accept": "Accetto la missione.",
            "decline": "Rifiuto, non sono interessato.",
            "ask_more": "Dimmi di più su questa missione.",
            "yes": "Sì.",
            "no": "No.",
        }

        if choice_id.startswith("event_choice_"):
            try:
                index = int(choice_id.split("_")[-1])
                return str(index + 1)
            except (ValueError, IndexError):
                return "1"

        if choice_id.startswith("quest_"):
            parts = choice_id.rsplit("_", 1)
            if len(parts) == 2:
                result = parts[1]
                return choice_map.get(result, f"Scelgo: {choice_id}")

        return choice_map.get(choice_id, f"Scelgo: {choice_id}")

    # ------------------------------------------------------------------
    # Dynamic event handling
    # ------------------------------------------------------------------

    def _show_dynamic_event_choices(self, dynamic_event: dict) -> None:
        """Show choice buttons for dynamic event in Event widget."""
        w = self.window
        event_id = dynamic_event.get('event_id', 'Evento')
        narrative = dynamic_event.get('narrative', '')
        choices_data = dynamic_event.get('choices', [])

        if not choices_data:
            return

        w._current_dynamic_event = event_id
        w._current_event_choices = choices_data

        choice_texts = [c.get('text', f'Opzione {i+1}') for i, c in enumerate(choices_data)]

        w.event_widget.show_event_choices(
            event_title=event_id.replace('_', ' ').title(),
            description=narrative,
            choices=choice_texts,
        )

        logger.debug(f"[MainWindow] Showing dynamic event choices in Event widget for: {event_id}")

    @asyncSlot()
    async def _on_event_choice_selected(self, choice_index: int) -> None:
        """Handle event choice selected from Event widget."""
        w = self.window
        logger.debug(f"[MainWindow] Event choice selected: {choice_index}")

        if not w.engine or not hasattr(w, '_current_dynamic_event'):
            return

        choice_text = str(choice_index + 1)
        await w.game_controller._process_choice_turn(choice_text)

        w._current_dynamic_event = None
        w._current_event_choices = None

    def _on_event_dismissed(self) -> None:
        """Handle event dismissed (user clicked Ignora)."""
        w = self.window
        logger.debug(f"[MainWindow] Event dismissed: {getattr(w, '_current_dynamic_event', None)}")

        if w.engine and hasattr(w, '_current_dynamic_event'):
            if (hasattr(w.engine, 'gameplay_manager') and
                    w.engine.gameplay_manager and
                    hasattr(w.engine.gameplay_manager, 'event_manager') and
                    w.engine.gameplay_manager.event_manager):
                w.engine.gameplay_manager.event_manager.skip_event()
                logger.debug("[MainWindow] Event skipped via event_manager")

        w._current_dynamic_event = None
        w._current_event_choices = None
