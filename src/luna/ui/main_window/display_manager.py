"""Luna RPG - Display Manager.

Handles all UI update and rendering methods.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from luna.core.models import TimeOfDay
from luna.core.debug_tracer import tracer

if TYPE_CHECKING:
    from .main_window import MainWindow
    from luna.core.models import TurnResult

logger = logging.getLogger(__name__)


class DisplayManager:
    """Manages all UI display updates."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def update_all_widgets(self) -> None:
        """Update all UI widgets (used after load/new game)."""
        self.update_status()
        self.update_location_widget()
        self.update_outfit_widget()
        self.update_quest_tracker()
        self.update_story_beats()
        self.update_action_bars()
        self.update_companion_list()
        self.update_companion_locator()
        self.update_video_toggle()
        self.update_personality_display()
        self.update_event_widget()

    # ------------------------------------------------------------------
    # Companion / status
    # ------------------------------------------------------------------

    def update_companion_list(self) -> None:
        """Update companion list widget."""
        w = self.window
        if not w.engine:
            return
        world = w.engine.world
        _MAIN_COMPANIONS = {"luna", "stella", "maria"}
        companions = [c for c in world.companions.keys() if c.lower() in _MAIN_COMPANIONS]
        w.companion_status.set_companions(companions)

        game_state = w.engine.get_game_state()
        if game_state and game_state.affinity:
            for name, affinity_value in game_state.affinity.items():
                if name.lower() in _MAIN_COMPANIONS:
                    w.companion_status.update_companion(name, affinity_value, "", "😐")

    def update_companion_locator(self) -> None:
        """Removed — CompanionLocatorWidget no longer present."""
        pass

    def update_status(self) -> None:
        """Update status bar."""
        w = self.window
        if not w.engine:
            return

        w.statusbar.clearMessage()
        state = w.engine.get_game_state()
        w.lbl_turn.setText(f"Turn: {state.turn_count}")

        # v8: Modalità avanzamento fase manuale — indicatori di turno rimossi
        with tracer.step_context("UI Status Update", "ui"):
            tracer.expect("phase_manager_exists", True)
            tracer.actual("phase_manager_exists", w.engine.phase_manager is not None)
            
            if w.engine.phase_manager:
                is_frozen = w.engine.phase_manager.is_frozen
                tracer.actual("is_frozen", is_frozen)
                # Il pulsante "Avanza Fase" è sempre attivo in modalità manuale
                if w.btn_advance_phase:
                    w.btn_advance_phase.setEnabled(True)
            else:
                tracer.critical_alert("UI Error", "PhaseManager is None!")

        location_name = state.current_location
        if w.engine.world and state.current_location in w.engine.world.locations:
            location_obj = w.engine.world.locations[state.current_location]
            location_name = location_obj.name
        w.lbl_location.setText(f"📍 {location_name}")
        logger.debug(f"[StatusBar] Location updated: {location_name}")

        time_val = state.time_of_day
        if hasattr(time_val, 'value'):
            time_str = time_val.value
            time_enum = time_val
        else:
            time_str = str(time_val)
            try:
                time_enum = TimeOfDay(time_str)
            except ValueError:
                time_enum = TimeOfDay.MORNING

        time_icons = {
            TimeOfDay.MORNING: "☀️",
            TimeOfDay.AFTERNOON: "🌅",
            TimeOfDay.EVENING: "🌆",
            TimeOfDay.NIGHT: "🌙",
        }
        icon = time_icons.get(time_enum, "🕐")
        w.lbl_time.setText(f"{icon} {time_str.upper()}")

        if w.engine:
            active = w.engine.get_game_state().active_companion
            w.lbl_companion.setText(f"👤 {active}")

    # ------------------------------------------------------------------
    # Location / outfit
    # ------------------------------------------------------------------

    def update_location_widget(self, force_location_id: Optional[str] = None) -> None:
        """Update location widget display."""
        w = self.window
        if not w.engine or not w.engine.location_manager:
            logger.debug("[LocationWidget] No engine or location_manager")
            return

        loc_mgr = w.engine.location_manager

        if force_location_id:
            current = loc_mgr.get_location(force_location_id)
            instance = loc_mgr.get_instance(force_location_id)
            logger.debug(f"[LocationWidget] Forced location: {force_location_id}")
        else:
            current = loc_mgr.get_current_location()
            instance = loc_mgr.get_current_instance()

        logger.debug(f"[LocationWidget] Current location: {current.name if current else 'None'}, Instance: {instance is not None}")

        if not current:
            logger.debug("[LocationWidget] No current location")
            return
        if not instance:
            logger.debug(f"[LocationWidget] No instance for location: {loc_mgr.game_state.current_location}")
            return

        game_state = w.engine.get_game_state()
        characters_present = []

        current_location_id = game_state.current_location
        for companion_name in w.engine.world.companions.keys():
            companion_def = w.engine.world.companions.get(companion_name)
            if getattr(companion_def, 'is_temporary', False):
                continue

            npc_location = game_state.get_npc_location(companion_name)

            if not npc_location and w.engine.schedule_manager:
                npc_location = w.engine.schedule_manager.get_npc_current_location(companion_name)

            if npc_location == current_location_id:
                characters_present.append(companion_name)

        if not characters_present and current.available_characters:
            characters_present.extend(current.available_characters)

        desc = instance.get_effective_description(current, game_state.time_of_day)

        loc_state = instance.current_state.value if hasattr(instance.current_state, 'value') else str(instance.current_state)
        w.location_widget.set_location(
            name=current.name,
            description=desc,
            state=loc_state,
            characters=characters_present,
        )
        logger.debug(f"[LocationWidget] Updated: {current.name}, desc={desc[:50]}..., characters={len(characters_present)}")

    def update_outfit_widget(self, sd_prompt: Optional[str] = None) -> None:
        """Update outfit widget display."""
        w = self.window
        if not w.engine:
            return

        state = w.engine.get_game_state()
        outfit = state.get_outfit()

        logger.debug(f"[DEBUG Outfit] active_companion: {state.active_companion}")
        logger.debug(f"[DEBUG Outfit] outfit.style: {outfit.style}")
        logger.debug(f"[DEBUG Outfit] outfit.description: {outfit.description}")
        logger.debug(f"[DEBUG Outfit] outfit.components: {outfit.components}")
        if outfit.base_sd_prompt:
            logger.debug(f"[DEBUG Outfit] outfit.base_sd_prompt: {outfit.base_sd_prompt[:80]}...")
        else:
            logger.debug("[DEBUG Outfit] outfit.base_sd_prompt: (empty)")
        logger.debug(f"[DEBUG Outfit] to_sd_prompt(): {outfit.to_sd_prompt()[:80]}...")

        world = w.engine.world
        companion = world.companions.get(state.active_companion)

        description = outfit.description
        if companion and companion.wardrobe and not description:
            wardrobe_def = companion.wardrobe.get(outfit.style)
            if wardrobe_def:
                if isinstance(wardrobe_def, str):
                    description = wardrobe_def
                else:
                    description = getattr(wardrobe_def, 'description', '') or \
                                 getattr(wardrobe_def, 'sd_prompt', '')
            if not description:
                description = outfit.style

        if companion:
            styles = list(companion.wardrobe.keys()) if companion.wardrobe else ["default"]
            w.outfit_widget.set_available_styles(styles)

        prompt_to_show = sd_prompt if sd_prompt else ""

        w.outfit_widget.set_outfit(
            style=outfit.style,
            description=description,
            components=outfit.components,
            positive_prompt=prompt_to_show,
        )

    # ------------------------------------------------------------------
    # Quest / story
    # ------------------------------------------------------------------

    def update_quest_tracker(self) -> None:
        """Removed — quest state is now shown via QuestJournalWidget updated by NarrativeCompassData."""
        pass

    def update_story_beats(self) -> None:
        """Removed — StoryBeatsWidget no longer present."""
        pass

    def _update_story_beats_old(self) -> None:
        """Archived — kept for reference only, not called."""
        w = self.window
        if not w.engine or not w.engine.world:
            return
        game_state = w.engine.get_game_state()
        active_companion = game_state.active_companion
        story_beats = getattr(w.engine.world, 'story_beats', None)
        narrative_arc = getattr(w.engine.world, 'narrative_arc', None)

        logger.debug(f"[StoryBeats] Loading beats for {active_companion}")
        logger.debug(f"[StoryBeats] story_beats: {story_beats is not None}, narrative_arc: {narrative_arc is not None}")

        beats = []
        if story_beats and isinstance(story_beats, dict):
            beats = story_beats.get('beats', [])
        elif narrative_arc and hasattr(narrative_arc, 'beats'):
            beats = narrative_arc.beats

        if not beats:
            logger.debug(f"[StoryBeats] No beats found for {active_companion}")
            w.story_beats_widget.update_beats(active_companion, [])
            return

        logger.debug(f"[StoryBeats] Total beats: {len(beats)}")
        companion_beats = []
        current_affinity = game_state.affinity.get(active_companion, 0)

        for beat in beats:
            if hasattr(beat, 'id'):
                beat_id = beat.id
                beat_description = beat.description
                beat_trigger = beat.trigger
                beat_consequence = beat.consequence
            else:
                beat_id = beat.get('id', '')
                beat_description = beat.get('description', beat_id)
                beat_trigger = beat.get('trigger', '')
                beat_consequence = beat.get('consequence', '')

            if not beat_id.lower().startswith(active_companion.lower()):
                continue

            required_affinity = 0
            if 'affinity >=' in beat_trigger:
                try:
                    required_affinity = int(beat_trigger.split('>=')[1].split()[0])
                except (ValueError, IndexError):
                    pass

            completed = False
            if '=' in beat_consequence:
                flag_name = beat_consequence.split('=')[0].strip()
                if flag_name in game_state.flags:
                    completed = True

            companion_beats.append({
                'title': beat_description or beat_id,
                'required_affinity': required_affinity,
                'current_affinity': current_affinity,
                'completed': completed,
            })

        logger.debug(f"[StoryBeats] Found {len(companion_beats)} beats for {active_companion}")
        w.story_beats_widget.update_beats(active_companion, companion_beats)

    def update_action_bars(self) -> None:
        """Update quick action bar with available actions."""
        w = self.window
        if not w.engine:
            return
        actions = w.engine.get_available_actions()
        w.quick_actions.update_actions(actions)

    def update_video_toggle(self) -> None:
        """Update video button state based on execution mode."""
        w = self.window
        settings = get_settings()
        if settings.is_runpod:
            w.act_video.setEnabled(True)
            w.act_video.setToolTip("Genera video dall'immagine corrente")
        else:
            w.act_video.setEnabled(False)
            w.act_video.setToolTip("Video generation requires RunPod mode")

    def update_event_widget(self) -> None:
        """Update event widget with current active global event."""
        w = self.window
        if not getattr(w, "event_widget", None):
            return
        if not w.engine or not w.engine.event_manager:
            w.event_widget.set_event()
            return

        primary_event = w.engine.event_manager.get_primary_event()
        if primary_event:
            w.event_widget.set_event(
                title=primary_event.name,
                description=primary_event.description,
                icon=primary_event.icon,
            )
        else:
            w.event_widget.set_event()

    def update_personality_display(self) -> None:
        """Update personality archetype and impression display."""
        w = self.window
        if not w.engine or not w.engine.personality_engine:
            return

        game_state = w.engine.get_game_state()
        companion = game_state.active_companion

        archetype = w.engine.personality_engine.detect_archetype(companion)

        if archetype:
            w.lbl_archetype.setText(f"🎭 {archetype}")
            w.lbl_archetype.setToolTip(
                f"Your personality profile with {companion}\n"
                f"Detected archetype: {archetype}\n"
                f"Based on your behavioral patterns"
            )
        else:
            state = w.engine.personality_engine._ensure_state(companion)
            total_behaviors = sum(m.occurrences for m in state.behavioral_memory.values())
            if total_behaviors > 0:
                w.lbl_archetype.setText(f"🎭 Analyzing... ({total_behaviors}/3)")
            else:
                w.lbl_archetype.setText("🎭 Analyzing...")

        state = w.engine.personality_engine._ensure_state(companion)
        imp = state.impression

        w.personality_widget.set_archetype(archetype)
        w.personality_widget.set_impressions(
            trust=imp.trust,
            attraction=imp.attraction,
            fear=imp.fear,
            curiosity=imp.curiosity,
            dominance_balance=imp.dominance_balance,
        )

        behaviors = [
            (b.value if hasattr(b, 'value') else str(b)).replace("_", " ").title()
            for b, m in state.behavioral_memory.items()
            if m.occurrences > 0
        ]
        w.personality_widget.set_behaviors(behaviors)

        for behavior, memory in state.behavioral_memory.items():
            if memory.occurrences == 1 and memory.last_turn == game_state.turn_count - 1:
                behavior_str = behavior.value if hasattr(behavior, 'value') else str(behavior)
                behavior_name = behavior_str.replace("_", " ").title()
                w.feedback.behavior_detected(companion, behavior_name)

    # ------------------------------------------------------------------
    # Turn result display
    # ------------------------------------------------------------------

    def _display_npc_message(self, message: "NpcMessage") -> None:
        """Display an asynchronous NPC message in the log.

        Differenzia la visualizzazione per canale:
        - sms/phone  → 📱 stile SMS
        - note       → 📝 stile biglietto cartaceo
        - official   → 📄 convocazione formale
        - gossip     → 💬 voce di corridoio
        """
        w = self.window

        # Risolve nome display del mittente
        sender_name = message.sender_id
        if w.engine and w.engine.world:
            comp_def = w.engine.world.companions.get(message.sender_id)
            if comp_def:
                sender_name = getattr(comp_def, "name", message.sender_id)
            elif w.engine.world.npc_templates:
                npc_def = w.engine.world.npc_templates.get(message.sender_id)
                if isinstance(npc_def, dict):
                    sender_name = npc_def.get("name", message.sender_id)
                elif hasattr(npc_def, "name"):
                    sender_name = getattr(npc_def, "name", message.sender_id)

        channel = getattr(message, "channel", "sms")

        if channel == "official":
            text = (
                f"📄 <b>CONVOCAZIONE — {sender_name}</b><br>"
                f"<i>{message.text}</i>"
            )
        elif channel == "note":
            text = (
                f"📝 <i>Trovi un biglietto piegato da <b>{sender_name}</b>:</i><br>"
                f"\"<i>{message.text}</i>\""
            )
        elif channel == "gossip":
            text = (
                f"💬 <i>Voci di corridoio su <b>{sender_name}</b>:</i> {message.text}"
            )
        else:  # sms / phone / default
            text = (
                f"📱 <b>{sender_name}</b>: <i>\"{message.text}\"</i>"
            )

        w.story_log.append_system_message(text)
        logger.info("[DisplayManager] NPC message displayed — channel=%s sender=%s", channel, message.sender_id)

    def display_result(self, result: TurnResult) -> None:
        """Display turn result in the UI.
        
        NOTE: User input is already displayed by game_controller before processing,
        so we don't show it here to avoid duplication.
        """
        w = self.window

        # User message is already shown by game_controller before process_turn
        # We only display NPC responses here

        if result.switched_companion and result.previous_companion and result.current_companion:
            logger.debug(f"[MainWindow] SWITCHED COMPANION: {result.previous_companion} -> {result.current_companion}")
            display_switch_name = result.current_companion
            if result.current_companion != "_solo_":
                comp_def = w.engine.world.companions.get(result.current_companion)
                if comp_def:
                    display_switch_name = comp_def.name
            w.story_log.append_system_message(
                f"📍 Ora parli con {display_switch_name} (prima: {result.previous_companion})"
            )
            w.lbl_companion.setText(f"👤 {display_switch_name}")
            self.update_companion_list()
            if result.is_temporary_companion and result.current_companion not in (w.engine.get_game_state().affinity or {}):
                w.engine.get_game_state().affinity[result.current_companion] = 0
                # Only update widget for main companions (not secondary NPCs)
                if result.current_companion in {"luna", "stella", "maria"}:
                    w.companion_status.update_companion(result.current_companion, 0, "", "😐")
            self.update_quest_tracker()
            self.update_story_beats()
            self.update_outfit_widget()
            self.update_personality_display()
            if getattr(w, "event_widget", None):
                w.event_widget.set_event()

        # Handle MultiNPC sequence display
        if result.multi_npc_sequence:
            # Don't show result.text separately - it's already in the sequence
            self._display_multi_npc_sequence(result)
            if result.audio_path:
                w.media_manager._play_audio(result.audio_path)
        else:
            # Standard single message display
            current_companion = result.current_companion or (w.engine.companion if w.engine else "Narrator")
            
            if result.provider_used == "system" and current_companion == "_solo_":
                w.story_log.append_system_message(result.text)
            else:
                if result.is_temporary_companion:
                    comp_def = w.engine.world.companions.get(current_companion) if w.engine else None
                    display_name = comp_def.name if comp_def else current_companion
                else:
                    # Check companions first, then npc_templates (initiative turns)
                    comp_def = w.engine.world.companions.get(current_companion) if w.engine else None
                    if comp_def:
                        display_name = comp_def.name
                    elif w.engine:
                        npc_tmpl = w.engine.world.npc_templates.get(current_companion)
                        if npc_tmpl:
                            display_name = (
                                npc_tmpl.get('name', current_companion)
                                if isinstance(npc_tmpl, dict)
                                else getattr(npc_tmpl, 'name', current_companion)
                            )
                        else:
                            display_name = current_companion
                    else:
                        display_name = current_companion
                # Skip empty text — happens when turns were already shown via
                # intermediate callbacks (e.g. NPC authority dialogue turns)
                if result.text:
                    w.story_log.append_character_message(result.text, display_name)

            if result.audio_path:
                w.media_manager._play_audio(result.audio_path)

            if result.image_path:
                img_path = Path(result.image_path)
                if img_path.exists():
                    w.image_display.set_image(str(img_path))

        if result.new_quests:
            for quest_title in result.new_quests:
                w.story_log.append_system_message(f"📜 New Quest: {quest_title}")
                w.feedback.quest_started(quest_title)

        if result.completed_quests:
            for quest_title in result.completed_quests:
                w.story_log.append_system_message(f"✅ Quest Completed: {quest_title}")
                w.feedback.quest_completed(quest_title)

        if result.active_event:
            if getattr(w, "event_widget", None):
                w.event_widget.set_event(
                    title=result.active_event.get('name', ''),
                    description=result.active_event.get('description', ''),
                    icon=result.active_event.get('icon', '🌍'),
                )
            if result.new_event_started:
                w.feedback.info(
                    f"{result.active_event.get('icon', '🌍')} {result.active_event.get('name', '')}",
                    result.active_event.get('description', '')
                )

        if result.dynamic_event and result.dynamic_event.get('choices'):
            w.event_handler._show_dynamic_event_choices(result.dynamic_event)

        _MAIN = {"luna", "stella", "maria"}
        state = w.engine.get_game_state()
        for name, delta in result.affinity_changes.items():
            if name.lower() in _MAIN:
                current_affinity = state.affinity.get(name, 0)
                w.companion_status.update_companion(name, current_affinity, "", "😐")

        if result.available_actions:
            w.quick_actions.update_actions(result.available_actions)

        # HUD: active_event takes priority and is shown regardless of narrative_compass
        if result.active_event:
            evt = result.active_event
            hud_type = "macro_event" if evt.get("is_macro") else "event"
            w.quest_journal.update_hud({
                "type": hud_type,
                "title": evt.get("name", ""),
                "description": evt.get("description", ""),
            })
        elif result.narrative_compass is not None:
            nc = result.narrative_compass
            w.quest_journal.update_quest(
                active_quest_title=nc.active_quest_title,
                active_stage_hint=nc.active_stage_hint,
                next_quest_title=nc.next_quest_title,
            )

        if result.narrative_compass is not None:
            nc = result.narrative_compass
            w.compass_widget.update_compass(nc)
            w.compass_widget.update_quest(
                active_quest_title=nc.active_quest_title,
                active_stage_title=nc.active_stage_title,
                player_hint=nc.active_stage_hint,
                next_quest_title=nc.next_quest_title,
                is_hidden=nc.is_hidden,
            )


    def _display_multi_npc_sequence(self, result: TurnResult) -> None:
        """Display multi-NPC images (text is already shown during generation via callback).

        result.multi_npc_sequence is a list of dicts:
          [{"speaker": str, "text": str, "visual_en": str, ...}, ...]
        
        NOTE: Text messages are already displayed in real-time during MultiNPC generation
        via the _ui_intermediate_message_callback. This method only handles image display.
        """
        w = self.window
        
        # Skip text display - already shown during generation via callback
        # Just display the final image
        if result.image_path:
            img_path = Path(result.image_path)
            if img_path.exists():
                w.image_display.set_image(str(img_path))
        elif result.multi_npc_image_paths:
            # Show the last non-None image (final scene state)
            valid_paths = [p for p in result.multi_npc_image_paths if p]
            if valid_paths:
                last_path = Path(valid_paths[-1])
                if last_path.exists():
                    w.image_display.set_image(str(last_path))

    # ------------------------------------------------------------------
    # Callbacks from engine
    # ------------------------------------------------------------------

    def on_time_change(self, new_time, message: str) -> None:
        """Handle time change — update UI time display."""
        w = self.window

        if hasattr(new_time, 'value'):
            time_str = new_time.value
            time_enum = new_time
        else:
            time_str = str(new_time)
            try:
                time_enum = TimeOfDay(time_str)
            except ValueError:
                time_enum = TimeOfDay.MORNING

        time_icons = {
            TimeOfDay.MORNING: "☀️",
            TimeOfDay.AFTERNOON: "🌅",
            TimeOfDay.EVENING: "🌆",
            TimeOfDay.NIGHT: "🌙",
        }
        icon = time_icons.get(time_enum, "🕐")
        w.lbl_time.setText(f"{icon} {time_str.upper()}")
        self.update_location_widget()
        logger.debug(f"[MainWindow] UI time updated to: {time_str}")

    def on_event_changed(self, event) -> None:
        """Handle global event activation/deactivation."""
        w = self.window
        if not getattr(w, "event_widget", None):
            return
        logger.debug(f"[GlobalEvent] Event changed: {event}")
        if event:
            logger.debug(f"[GlobalEvent] Setting event: {event.name} - {event.description[:50]}...")
            w.event_widget.set_event(
                title=event.name,
                description=event.description,
                icon=event.icon,
            )
            if hasattr(event, 'event_id'):
                w.feedback.info(f"{event.icon} {event.name}", event.description)
        else:
            logger.debug("[GlobalEvent] Clearing event widget")
            w.event_widget.set_event()

    def build_prompt_preview(self, companion, outfit) -> str:
        """Build SD positive prompt preview for display."""
        # Simple local fallback instead of missing BASE_PROMPTS
        
        if not companion:
            return ""

        char_lower = companion.name.lower()
        character_base = f"1girl, {companion.name}"

        outfit_prompt = outfit.to_sd_prompt(include_weight=False)
        prompt = f"{character_base}, {outfit_prompt}"

        w = self.window
        if hasattr(w, '_lora_mapping') and w._lora_mapping.is_enabled():
            outfit_state = {
                "description": outfit.description or "",
                "style": outfit.style or "",
                "components": outfit.components or {}
            }
            tags = [outfit.style] if outfit.style else []
            selected_loras = w._lora_mapping.select_loras(tags, companion.name, outfit_state)
            if selected_loras:
                lora_suffix = w._lora_mapping.lora_prompt_suffix(selected_loras, include_triggers=True)
                prompt = lora_suffix + ", " + prompt

        return prompt


# Local import needed inside method
from luna.core.config import get_settings
