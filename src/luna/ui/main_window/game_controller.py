"""Luna RPG - Game Controller.

Handles the game loop: turn execution and choice processing.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from pathlib import Path

import asyncio

from qasync import asyncSlot
from PySide6.QtWidgets import QMessageBox

if TYPE_CHECKING:
    from .main_window import MainWindow

logger = logging.getLogger(__name__)


class GameController:
    """Controls the game loop and turn execution."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window

    @asyncSlot()
    async def _on_send(self) -> None:
        """Handle send button / Enter key."""
        w = self.window
        if not w.engine:
            return

        if w._input_blocked or w.choice_widget.is_active() or w._is_processing:
            return

        text = w.txt_input.text().strip()
        if not text:
            return

        w.txt_input.clear()
        w.btn_send.setEnabled(False)
        w.lbl_status.setText("Processing...")
        w._is_processing = True

        # Show user message immediately (before processing, so it appears first)
        w.story_log.append_user_message(text)

        try:
            result = await w.engine.process_turn(text)

            # --- Poker window integration ---
            # If a poker game just started, open the dedicated PokerWindow
            # instead of showing the result in the main story log.
            poker_active = (
                w.engine.state.flags.get("poker_active")
                if w.engine and w.engine.state else False
            )
            poker_win_open = (
                w._poker_window is not None and w._poker_window.isVisible()
            )
            if poker_active and not poker_win_open:
                from luna.ui.poker_window import PokerWindow
                # Use a top-level window (no parent) so parent UI refreshes don't
                # momentarily hide the poker window during long media generation.
                w._poker_window = PokerWindow(w.engine, parent=None)
                w._poker_window.closed.connect(w._on_poker_window_closed)
                w._poker_window.display_startup_result(result)
                w._poker_window.show()
                # Brief notice in main window; don't duplicate the full table log
                w.story_log.append_system_message(
                    "♠ Finestra poker aperta. Usa l'input nella finestra del poker."
                )
                w.display_manager.update_status()
                return

            # display_result will show NPC responses (not user_input which is already shown)
            w.display_manager.display_result(result)

            if w.engine and w.engine.phase_manager:
                logger.debug(f"[MainWindow] BEFORE _update_status: turns_in_phase={w.engine.phase_manager._turns_in_phase}")
            w.display_manager.update_status()
            if w.engine and w.engine.phase_manager:
                logger.debug(f"[MainWindow] AFTER _update_status: turns_in_phase={w.engine.phase_manager._turns_in_phase}")

            w.display_manager.update_location_widget(force_location_id=result.new_location_id)
            w.display_manager.update_outfit_widget(sd_prompt=result.sd_prompt)
            w.display_manager.update_quest_tracker()
            w.display_manager.update_story_beats()
            w.display_manager.update_action_bars()
            w.display_manager.update_personality_display()
            w.display_manager.update_event_widget()
            w.display_manager.update_npc_actions_widget()  # v8: NPC Actions

            w.event_handler._check_pending_quest_choices()

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"[TURN ERROR TRACEBACK]\n{tb}")
            logs_dir = Path("logs")
            logs_dir.mkdir(parents=True, exist_ok=True)
            with open(logs_dir / "turn_error.log", "w", encoding="utf-8") as _f:
                _f.write(tb)
            QMessageBox.critical(w, "Error", f"Turn failed: {e}")

        finally:
            w._is_processing = False
            if not w.choice_widget.is_active():
                w.btn_send.setEnabled(True)
                w.txt_input.setEnabled(True)
            w.lbl_status.setText("Ready")

    def _on_initiative_tick(self) -> None:
        """Timer callback (sync) — guard check, then schedule async turn if safe."""
        w = self.window
        if not w.engine or w._is_processing or w._input_blocked:
            return
        if w.choice_widget.is_active():
            return
        # Suspend all autonomous NPC initiatives during poker
        if w.engine.state and w.engine.state.flags.get("poker_active"):
            return
        pending = getattr(w.engine, '_pending_initiatives', [])
        if not pending:
            return
        asyncio.ensure_future(self._run_initiative_turn())

    async def _run_initiative_turn(self) -> None:
        """Async body of the initiative turn, scheduled only when safe."""
        w = self.window
        # Double-check guards (state may have changed between scheduling and execution)
        if not w.engine or w._is_processing or w._input_blocked:
            return
        if w.choice_widget.is_active():
            return
        # Suspend all autonomous NPC initiatives during poker
        if w.engine.state and w.engine.state.flags.get("poker_active"):
            return
        pending = getattr(w.engine, '_pending_initiatives', [])
        if not pending:
            return

        hint = pending.pop(0)
        logger.info("[Initiative] Autonomous turn for %s", hint.npc_id)

        w._is_processing = True
        w.lbl_status.setText(f"⚡ {hint.npc_display_name} prende l'iniziativa...")
        try:
            result = await w.engine.run_initiative_turn(hint)
            if result:
                w.display_manager.display_result(result)
                w.display_manager.update_status()
            else:
                w.engine._pending_initiatives.insert(0, hint)
                logger.warning("[Initiative] Turn returned None for %s — re-queued", hint.npc_id)
        except Exception as e:
            logger.error("[Initiative] Turn error for %s: %s", hint.npc_id, e)
            w.engine._pending_initiatives.insert(0, hint)
        finally:
            w._is_processing = False
            w.lbl_status.setText("Ready")

    async def _process_choice_turn(self, choice_text: str) -> None:
        """Process a turn from a choice selection.

        Args:
            choice_text: Text command from choice
        """
        w = self.window
        if w._is_processing:
            return
        w._is_processing = True
        try:
            w.lbl_status.setText("Processing choice...")

            result = await w.engine.process_turn(choice_text)

            w.display_manager.display_result(result)
            w.display_manager.update_status()
            w.display_manager.update_location_widget()
            w.display_manager.update_quest_tracker()
            w.display_manager.update_action_bars()
            w.display_manager.update_personality_display()
            w.display_manager.update_npc_actions_widget()  # v8: NPC Actions

            w.lbl_status.setText("Ready")

        except Exception as e:
            logger.error(f"[Choice] Error processing choice: {e}")
            QMessageBox.critical(w, "Error", f"Choice processing failed: {e}")
        finally:
            w._is_processing = False
