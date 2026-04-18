"""Luna RPG - Main Window.

Main application window — thin coordinator that delegates to components:
- LayoutManager:   builds and manages UI widgets
- GameController:  handles game loop and turn execution
- EventHandler:    processes UI events and user interactions
- DisplayManager:  updates UI with game state
- MediaManager:    handles save/load, audio and video
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtWidgets import QMainWindow, QMessageBox
from PySide6.QtCore import QTimer

from luna.core.engine import GameEngine

from .layout_manager import LayoutManager
from .game_controller import GameController
from .event_handler import EventHandler
from .display_manager import DisplayManager
from .media_manager import MediaManager

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window — coordinates all UI components."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LUNA RPG v4")
        self.setMinimumSize(1400, 850)
        self.showMaximized()

        # Engine (set during initialize_game)
        self.engine: Optional[GameEngine] = None

        # Re-entrancy guards
        self._is_processing: bool = False
        self._input_blocked: bool = False

        # Choice tracking
        self._current_choice_quest_id: Optional[str] = None
        self._current_dynamic_event = None
        self._current_event_choices = None

        # Debug window (lazy)
        self._debug_window = None

        # v8: NPC initiative timer — fires autonomous NPC turns
        self._initiative_timer: Optional[QTimer] = None

        # v8: Poker mini-game window (None when not playing)
        self._poker_window = None

        # --- Create components (order matters: EventHandler before LayoutManager) ---
        self.event_handler = EventHandler(self)
        self.game_controller = GameController(self)
        self.display_manager = DisplayManager(self)
        self.media_manager = MediaManager(self)
        self.layout_manager = LayoutManager(self)

        # Build UI (assigns widget attrs to self via _assign_widgets)
        self.layout_manager.setup_all()
        self._assign_widgets()

    # ------------------------------------------------------------------
    # Widget proxy — widgets live on layout_manager, exposed here too
    # ------------------------------------------------------------------

    def _assign_widgets(self) -> None:
        """Copy widget references from LayoutManager onto self for convenience."""
        lm = self.layout_manager
        self.personality_widget = lm.personality_widget
        self.event_widget = lm.event_widget
        self.location_widget = lm.location_widget
        self.outfit_widget = lm.outfit_widget
        self.compass_widget = lm.compass_widget
        self.image_display = lm.image_display
        self.quest_journal = lm.quest_journal
        self.companion_status = lm.companion_status
        self.quick_actions = lm.quick_actions
        self.choice_widget = lm.choice_widget
        self.story_log = lm.story_log
        self.txt_input = lm.txt_input
        self.btn_send = lm.btn_send
        self.btn_interrupt = lm.btn_interrupt
        self.lbl_companion = lm.lbl_companion
        self.lbl_archetype = lm.lbl_archetype
        self.lbl_status = lm.lbl_status
        self.lbl_turn = lm.lbl_turn
        self.lbl_location = lm.lbl_location
        self.lbl_time = lm.lbl_time
        self.btn_advance_phase = lm.btn_advance_phase  # v8: pulsante avanza fase
        self.statusbar = lm.statusbar
        self.act_audio = lm.act_audio
        self.act_video = lm.act_video
        self._lora_toggle_action = lm._lora_toggle_action
        self.feedback = lm.feedback
        self.choice_manager = lm.choice_manager
        self.lora_mapping = lm.lora_mapping
        self.npc_actions_widget = lm.npc_actions_widget  # v8: NPC Actions Widget

    # ------------------------------------------------------------------
    # Game initialization
    # ------------------------------------------------------------------

    async def initialize_game(
        self,
        world_id: str,
        companion: str,
        session_id: Optional[int] = None,
    ) -> None:
        """Initialize game engine and show opening scene."""
        self.lbl_status.setText("Initializing game...")

        try:
            self.engine = GameEngine(world_id, companion)

            if session_id:
                await self.engine.load_session(session_id)
            else:
                await self.engine.initialize()

            if self.engine.event_manager:
                self.engine.event_manager.on_event_changed = self.display_manager.on_event_changed

            if self.engine:
                self.engine.set_ui_time_change_callback(self.display_manager.on_time_change)

            if self.engine:
                self.engine.set_ui_intermediate_message_callback(
                    self.event_handler.on_intermediate_npc_message
                )
                self.engine.set_ui_show_interrupt_callback(
                    self.event_handler.show_interrupt_button
                )
                self.engine.set_ui_image_callback(
                    self.event_handler.on_intermediate_image
                )

            self.display_manager.update_companion_list()
            self.display_manager.update_companion_locator()
            self.display_manager.update_status()
            self.display_manager.update_location_widget()
            self.display_manager.update_video_toggle()
            self.display_manager.update_outfit_widget()
            self.display_manager.update_quest_tracker()
            self.display_manager.update_story_beats()
            self.display_manager.update_action_bars()
            self.display_manager.update_event_widget()

            self.feedback.info("Game Started", f"Playing with {companion} in {world_id}")

            self.lbl_status.setText("Generating opening scene...")
            intro_result = await self.engine.generate_intro()

            self.display_manager.display_result(intro_result)

            self.lbl_status.setText("Ready")
            self.display_manager.update_event_widget()

            # Initiative timer (15s) has been removed (NPC Immersion System M2)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to initialize: {e}")

    # ------------------------------------------------------------------
    # Timer callback (trivial)
    # ------------------------------------------------------------------

    def _on_update(self) -> None:
        """Timer update for async operations."""
        pass

    # ------------------------------------------------------------------
    # Public interface for external callers (engine callbacks)
    # ------------------------------------------------------------------

    def show_quest_choice(
        self,
        quest_id: str,
        title: str,
        description: str,
        giver_name: str,
    ) -> None:
        """Show quest acceptance choice dialog."""
        self._current_choice_quest_id = quest_id
        self._input_blocked = True
        self.txt_input.setEnabled(False)
        self.btn_send.setEnabled(False)
        self.txt_input.setPlaceholderText("⛔ Scegli un'opzione sopra...")
        self.choice_widget.show_quest_acceptance(
            quest_title=title,
            quest_description=description,
            giver_name=giver_name,
        )
        logger.debug(f"[Choice] Showing quest choice: {quest_id} - {title}")

    def show_binary_choice(
        self,
        title: str,
        question: str,
        yes_text: str = "Sì",
        no_text: str = "No",
    ) -> None:
        """Show simple yes/no choice."""
        self._input_blocked = True
        self.txt_input.setEnabled(False)
        self.btn_send.setEnabled(False)
        self.txt_input.setPlaceholderText("⛔ Scegli un'opzione sopra...")
        self.choice_widget.show_binary_choice(
            title=title,
            question=question,
            yes_text=yes_text,
            no_text=no_text,
        )

    def show_custom_choices(
        self,
        title: str,
        context: str,
        choices: list,
    ) -> None:
        """Show custom choice dialog (for quest choices)."""
        self._input_blocked = True
        self.txt_input.setEnabled(False)
        self.btn_send.setEnabled(False)
        self.txt_input.setPlaceholderText("⛔ Scegli un'opzione sopra...")
        self.choice_widget.show_choices(title=title, context=context, choices=choices)

    def show_interrupt_button(self, show: bool) -> None:
        """Show or hide the interrupt button (delegated to EventHandler)."""
        self.event_handler.show_interrupt_button(show)

    async def on_intermediate_npc_message(
        self,
        text: str,
        speaker: str,
        turn_number: int,
        visual_en: str = "",
        tags_en=None,
    ) -> None:
        """Display intermediate NPC message (delegated to EventHandler)."""
        await self.event_handler.on_intermediate_npc_message(
            text, speaker, turn_number, visual_en, tags_en
        )

    def on_intermediate_image(self, image_path: str) -> None:
        """Display intermediate image (delegated to EventHandler)."""
        self.event_handler.on_intermediate_image(image_path)

    def _on_poker_window_closed(self) -> None:
        """Called when the PokerWindow is closed — clean up reference."""
        self._poker_window = None
        logger.info("[MainWindow] Poker window closed, reference cleared")
