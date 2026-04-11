"""Luna RPG v6 - World Loader.

Supports legacy single-file and modular folder formats.
Fully compatible with existing v5 YAML worlds.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from luna.core.config import get_settings
from luna.core.models import (
    CompanionDefinition,
    GlobalEventDefinition,
    Location,
    NarrativeArc,
    QuestAction,
    QuestCondition,
    QuestDefinition,
    QuestRewards,
    QuestStage,
    ScheduleEntry,
    TimeOfDay,
    WardrobeDefinition,
    WorldDefinition,
)

logger = logging.getLogger(__name__)

_TIME_KEY_ALIAS_MAP = {
    "dawn": TimeOfDay.MORNING,
    "sunrise": TimeOfDay.MORNING,
    "mattino": TimeOfDay.MORNING,
    "mattina": TimeOfDay.MORNING,
    "noon": TimeOfDay.AFTERNOON,  # schedule files often treat noon as afternoon
    "pomeriggio": TimeOfDay.AFTERNOON,
    "sera": TimeOfDay.EVENING,
    "tramonto": TimeOfDay.EVENING,
    "notte": TimeOfDay.NIGHT,
    "midnight": TimeOfDay.NIGHT,
}


def _normalize_time_key(value: Any) -> Optional[TimeOfDay]:
    """Normalize arbitrary schedule keys to TimeOfDay."""
    if isinstance(value, TimeOfDay):
        return value
    if value is None:
        return None

    key = str(value).strip()
    if not key:
        return None

    # Direct enum match (keeps capitalized canonical values working)
    try:
        return TimeOfDay(key)
    except ValueError:
        pass

    normalized = key.lower()
    for candidate in TimeOfDay:
        if candidate.value.lower() == normalized:
            return candidate

    # Remove separators ("evening " etc.)
    compact = normalized.replace("_", "").replace("-", "").replace(" ", "")
    for alias_key, target in _TIME_KEY_ALIAS_MAP.items():
        if alias_key == normalized or alias_key == compact:
            return target

    return None


class WorldLoadError(Exception):
    pass


class WorldValidator:
    @staticmethod
    def validate_world(data: Dict[str, Any]) -> List[str]:
        errors = []
        if "meta" not in data:
            errors.append("Missing required section: meta")
        else:
            if "id" not in data["meta"]:
                errors.append("meta.id is required")
            if "name" not in data["meta"]:
                errors.append("meta.name is required")
        if not data.get("companions"):
            errors.append("Missing or empty section: companions")
        return errors


class WorldLoader:
    """Loads world definitions from YAML files.

    Supports:
    - Legacy: single YAML file (world_name.yaml)
    - Modular: folder with multiple YAML files (world_name/_meta.yaml + ...)
    """

    def __init__(self, worlds_path: Optional[Path] = None) -> None:
        settings = get_settings()
        self.worlds_path = Path(worlds_path or settings.worlds_path)
        self._cache: Dict[str, WorldDefinition] = {}

    def list_worlds(self) -> List[Dict[str, Any]]:
        worlds = []
        if not self.worlds_path.exists():
            return worlds

        for file_path in self.worlds_path.glob("*.yaml"):
            try:
                data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
                meta = data.get("meta", {})
                worlds.append({
                    "id":     meta.get("id", file_path.stem),
                    "name":   meta.get("name", file_path.stem),
                    "genre":  meta.get("genre", "Unknown"),
                    "description": meta.get("description", ""),
                    "format": "legacy",
                })
            except Exception as e:
                logger.warning("Error loading world file %s: %s", file_path, e)

        for folder_path in self.worlds_path.iterdir():
            if folder_path.is_dir() and (folder_path / "_meta.yaml").exists():
                try:
                    meta_data = yaml.safe_load(
                        (folder_path / "_meta.yaml").read_text(encoding="utf-8")
                    )
                    meta = meta_data.get("meta", {})
                    worlds.append({
                        "id":     meta.get("id", folder_path.name),
                        "name":   meta.get("name", folder_path.name),
                        "genre":  meta.get("genre", "Unknown"),
                        "description": meta.get("description", ""),
                        "format": "modular",
                    })
                except Exception as e:
                    logger.warning("Error loading world folder %s: %s", folder_path, e)

        return sorted(worlds, key=lambda w: w["name"])

    def load_world(self, world_id: str) -> Optional[WorldDefinition]:
        if world_id in self._cache:
            return self._cache[world_id]

        folder_path = self.worlds_path / world_id
        if folder_path.is_dir() and (folder_path / "_meta.yaml").exists():
            world = self._load_modular(folder_path, world_id)
        else:
            file_path = self.worlds_path / f"{world_id}.yaml"
            if not file_path.exists():
                file_path = self.worlds_path / world_id
            world = self._load_legacy(file_path, world_id) if file_path.exists() else None

        if world:
            self._cache[world_id] = world
        return world

    def clear_cache(self) -> None:
        self._cache.clear()

    # -------------------------------------------------------------------------
    # Loaders
    # -------------------------------------------------------------------------

    def _load_legacy(self, file_path: Path, world_id: str) -> Optional[WorldDefinition]:
        try:
            raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
            return self._process_world_data(raw, world_id)
        except Exception as e:
            logger.error("Error loading legacy world %s: %s", world_id, e)
            return None

    def _load_modular(self, folder_path: Path, world_id: str) -> Optional[WorldDefinition]:
        try:
            merged: Dict[str, Any] = {
                "meta": {}, "companions": {}, "locations": {},
                "quests": {}, "time": {}, "global_events": {},
                "random_events": {}, "daily_events": {},
                "npc_templates": {}, "npc_schedules": {}, "npc_logic": {},
                "player_character": {}, "story_beats": {},
            }

            meta_file = folder_path / "_meta.yaml"
            if meta_file.exists():
                meta_data = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
                merged["meta"]             = meta_data.get("meta", {})
                merged["npc_logic"]        = meta_data.get("npc_logic", {})
                merged["player_character"] = meta_data.get("player_character", {})
                merged["story_beats"]      = meta_data.get("story_beats", {})
                merged["narrative_arc"]    = meta_data.get("narrative_arc", {})

            for yaml_file in sorted(folder_path.glob("*.yaml")):
                if yaml_file.name == "_meta.yaml":
                    continue
                try:
                    file_data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                    if not file_data:
                        continue
                    self._merge_file(merged, file_data, yaml_file.name)
                except Exception as e:
                    logger.warning("Error loading %s: %s", yaml_file.name, e)

            return self._process_world_data(merged, world_id)
        except Exception as e:
            logger.error("Error loading modular world %s: %s", world_id, e)
            return None

    def _merge_file(
        self, merged: Dict[str, Any], file_data: Dict[str, Any], filename: str
    ) -> None:
        """Merge one YAML file into the merged dict."""
        # Single companion file (companion: {...})
        if "companion" in file_data:
            comp = file_data["companion"]
            name = comp.get("name", filename.replace(".yaml", ""))
            merged["companions"][name] = comp

        if "companions" in file_data:
            merged["companions"].update(file_data["companions"])
        if "quests" in file_data:
            merged["quests"].update(file_data["quests"])
        if "locations" in file_data:
            locs = file_data["locations"]
            if isinstance(locs, list):
                for loc in locs:
                    if isinstance(loc, dict) and "id" in loc:
                        merged["locations"][loc["id"]] = loc
            else:
                merged["locations"].update(locs)
        if "time" in file_data:
            merged["time"].update(file_data["time"])
        if "global_events" in file_data:
            merged["global_events"].update(file_data["global_events"])
        if "npc_templates" in file_data:
            merged["npc_templates"].update(file_data["npc_templates"])
        if "npc_schedules" in file_data:
            merged["npc_schedules"] = file_data["npc_schedules"]

        # v7: tension config
        if "tension_axes" in file_data:
            merged["tension_config"] = file_data["tension_axes"]

        # v7: companion-level fields (npc_relationships, goal_templates, needs_profile)
        # v8: Character Realism fields (auto_states, avoid_topics_unless_asked, behavior_responses)
        # These are loaded alongside the companion definition in single-companion files
        if "companion" in file_data:
            comp_name = file_data["companion"].get("name", filename.replace(".yaml", ""))
            for v7_field in (
                "npc_relationships", "goal_templates", "needs_profile",
                "auto_states", "avoid_topics_unless_asked", "behavior_responses",
            ):
                if v7_field in file_data:
                    if comp_name in merged["companions"]:
                        merged["companions"][comp_name][v7_field] = file_data[v7_field]

        if filename == "random_events.yaml" and "events" in file_data:
            evt = file_data["events"]
            if isinstance(evt, dict):
                merged["random_events"].update(evt)
                # Also add to global_events so GlobalEventManager can use them
                merged["global_events"].update(evt)
            elif isinstance(evt, list):
                for e in evt:
                    if isinstance(e, dict) and "id" in e:
                        merged["random_events"][e["id"]] = e
                        merged["global_events"][e["id"]] = e

        if filename == "daily_events.yaml" and "events" in file_data:
            evt = file_data["events"]
            if isinstance(evt, dict):
                merged["daily_events"].update(evt)
                # Also add to global_events so GlobalEventManager can use them
                merged["global_events"].update(evt)
            elif isinstance(evt, list):
                for e in evt:
                    if isinstance(e, dict) and "id" in e:
                        merged["daily_events"][e["id"]] = e
                        merged["global_events"][e["id"]] = e

        if filename == "companion_schedules.yaml" and "npc_schedules" in file_data:
            merged["npc_schedules"] = file_data["npc_schedules"]

    # -------------------------------------------------------------------------
    # Processing
    # -------------------------------------------------------------------------

    def _process_world_data(
        self, data: Dict[str, Any], world_id: str
    ) -> Optional[WorldDefinition]:
        errors = WorldValidator.validate_world(data)
        if errors:
            for e in errors:
                logger.error("[WorldLoader] %s: %s", world_id, e)
            return None

        meta = data.get("meta", {})

        # Companions
        companions = {}
        for name, comp_data in data.get("companions", {}).items():
            try:
                companions[name] = self._process_companion(name, comp_data)
            except Exception as e:
                logger.warning("[WorldLoader] Companion %s failed: %s", name, e)

        # Locations
        locations = {}
        for loc_id, loc_data in data.get("locations", {}).items():
            try:
                locations[loc_id] = self._process_location(loc_id, loc_data)
            except Exception as e:
                logger.warning("[WorldLoader] Location %s failed: %s", loc_id, e)

        # Time slots (stored as plain dicts in v6)
        time_slots: Dict[Any, Any] = {}
        for time_key, time_data in data.get("time", {}).items():
            tod = _normalize_time_key(time_key)
            if tod:
                time_slots[tod] = time_data
            else:
                logger.warning("[WorldLoader] Invalid time slot: %s", time_key)

        # Quests
        quests = {}
        for quest_id, quest_data in data.get("quests", {}).items():
            try:
                quests[quest_id] = self._process_quest(quest_id, quest_data)
            except Exception as e:
                logger.warning("[WorldLoader] Quest %s failed: %s", quest_id, e)

        # Narrative arc
        narrative_arc = self._process_narrative_arc(
            data.get("narrative_arc", {})
        )

        # Global events
        global_events = {}
        for evt_id, evt_data in data.get("global_events", {}).items():
            try:
                if not isinstance(evt_data, dict):
                    continue
                meta_evt = evt_data.get("meta", {})
                trigger  = evt_data.get("trigger", {})
                
                # Build trigger conditions from trigger dict
                trigger_conditions = []
                if trigger.get("conditions"):
                    trigger_conditions.extend(trigger["conditions"])
                
                global_events[evt_id] = GlobalEventDefinition(
                    id=evt_id,
                    title=meta_evt.get("title", evt_data.get("title", evt_id)),
                    description=meta_evt.get("description", evt_data.get("description", "")),
                    trigger_type=trigger.get("type", "random"),
                    trigger_chance=float(trigger.get("chance", 0.1)),
                    allowed_times=trigger.get("allowed_times", []),
                    allowed_locations=trigger.get("allowed_locations", []),
                    min_turn=int(trigger.get("min_turn", 0)),
                    repeatable=trigger.get("repeatable", True) if isinstance(trigger.get("repeatable"), bool) else True,
                    narrative_prompt=evt_data.get("narrative_prompt", ""),
                    narrative=evt_data.get("narrative", ""),
                    choices=evt_data.get("choices", []),
                    type=evt_data.get("type", "random"),
                    trigger_conditions=trigger_conditions,
                )
            except Exception as e:
                logger.warning("[WorldLoader] GlobalEvent %s failed: %s", evt_id, e)

        return WorldDefinition(
            id=meta.get("id", world_id),
            name=meta.get("name", world_id),
            genre=meta.get("genre", "Visual Novel"),
            description=str(meta.get("description", "")),
            lore=str(meta.get("lore", "")),
            locations=locations,
            companions=companions,
            time_slots=time_slots,
            quests=quests,
            narrative_arc=narrative_arc,
            female_hints=data.get("npc_logic", {}).get("female_hints", []),
            male_hints=data.get("npc_logic", {}).get("male_hints", []),
            global_events=global_events,
            random_events=data.get("random_events", {}),
            daily_events=data.get("daily_events", {}),
            npc_templates=data.get("npc_templates", {}),
            npc_schedules=data.get("npc_schedules", {}),
            player_character=data.get("player_character", {}),
            gameplay_systems=data.get("gameplay_systems", {}),
            tension_config=data.get("tension_config", {}),
        )

    def _process_companion(
        self, name: str, data: Dict[str, Any]
    ) -> CompanionDefinition:
        # Schedule
        schedule = {}
        for time_key, sched_data in data.get("schedule", {}).items():
            tod = _normalize_time_key(time_key)
            if not tod:
                logger.warning("[WorldLoader] Invalid schedule time: %s", time_key)
                continue

            loc = (
                sched_data.get("preferred_location")
                or sched_data.get("location", "Unknown")
            )
            schedule[tod] = ScheduleEntry(
                time_slot=tod.value,
                location=loc,
                outfit=sched_data.get("outfit", "default"),
                activity=sched_data.get("activity", ""),
            )

        # Wardrobe
        wardrobe: Dict[str, Any] = {}
        for style_name, style_data in data.get("wardrobe", {}).items():
            if isinstance(style_data, str):
                wardrobe[style_name] = WardrobeDefinition(description=style_data)
            elif isinstance(style_data, dict):
                wardrobe[style_name] = WardrobeDefinition(
                    description=style_data.get("description", ""),
                    sd_prompt=style_data.get("sd_prompt", ""),
                    special=style_data.get("special", False),
                )
            else:
                wardrobe[style_name] = style_data

        # Personality system
        personality = data.get("personality_system", {})
        core_traits = personality.get("core_traits", {})

        # Relations
        relations: Dict[str, Dict[str, Any]] = {}
        for rel_name, rel_data in data.get("relations", {}).items():
            if isinstance(rel_data, dict):
                relations[rel_name] = rel_data

        return CompanionDefinition(
            name=name,
            role=data.get("role", ""),
            age=int(data.get("age", 21)),
            base_personality=data.get("base_personality", ""),
            base_prompt=data.get("base_prompt", ""),
            physical_description=data.get("physical_description", ""),
            default_outfit=data.get("default_outfit", "default"),
            visual_tags=data.get("visual_tags", []),
            wardrobe=wardrobe,
            emotional_states=personality.get("emotional_states", {}),
            affinity_tiers=personality.get("affinity_tiers", {}),
            background=core_traits.get("background", data.get("background", "")),
            relationship_to_player=core_traits.get(
                "relationship_to_player",
                data.get("relationship_to_player", ""),
            ),
            aliases=data.get("aliases", []),
            schedule=schedule,
            relations=relations,
            is_temporary=bool(data.get("is_temporary", False)),
            gender=data.get("gender", "female"),
            # v7 fields
            npc_relationships=data.get("npc_relationships", {}),
            goal_templates=data.get("goal_templates", []),
            needs_profile=data.get("needs_profile", {}),
            # v8: Character Realism System
            auto_states=data.get("auto_states", []),
            avoid_topics_unless_asked=data.get("avoid_topics_unless_asked", []),
            behavior_responses=data.get("behavior_responses", {}),
        )

    def _process_location(
        self, loc_id: str, data: Dict[str, Any]
    ) -> Location:
        # time_descriptions keys
        time_desc: Dict[str, str] = {}
        for time_key, desc in data.get("time_descriptions", {}).items():
            time_desc[time_key] = desc

        # available_times
        available_times: List[TimeOfDay] = []
        for time_key in data.get("available_times", []):
            tod = _normalize_time_key(time_key)
            if tod:
                available_times.append(tod)

        return Location(
            id=loc_id,
            name=data.get("name", loc_id),
            description=data.get("description", ""),
            visual_style=data.get("visual_style", ""),
            lighting=data.get("lighting", ""),
            connected_to=data.get("connected_to", []),
            aliases=data.get("aliases", []),
            available_times=available_times or list(TimeOfDay),
            time_descriptions=time_desc,
            dynamic_descriptions=data.get("dynamic_descriptions", {}),
            hidden=bool(data.get("hidden", False)),
            requires_flag=data.get("requires_flag"),
            available_characters=data.get("available_characters", []),
        )

    def _process_narrative_arc(self, data: Dict[str, Any]) -> NarrativeArc:
        # Load beats from narrative_arc data
        from luna.core.models import StoryBeat
        
        beats = []
        for beat_data in data.get("beats", []):
            if isinstance(beat_data, dict):
                beats.append(StoryBeat(
                    id=beat_data.get("id", ""),
                    description=beat_data.get("description", ""),
                    trigger=beat_data.get("trigger", ""),
                    required_elements=beat_data.get("required_elements", []),
                    tone=beat_data.get("tone", ""),
                    once=beat_data.get("once", True),
                    priority=beat_data.get("priority", 5),
                    consequence=beat_data.get("consequence"),
                ))
        
        return NarrativeArc(
            premise=data.get("premise", ""),
            themes=data.get("themes", []),
            beats=beats,
            hard_limits=data.get("hard_limits", []),
            soft_guidelines=data.get("soft_guidelines", []),
        )

    def _process_quest(
        self, quest_id: str, data: Dict[str, Any]
    ) -> QuestDefinition:
        # Stages
        stages: Dict[str, QuestStage] = {}
        for stage_id, stage_data in data.get("stages", {}).items():
            on_enter = [
                QuestAction(**a) for a in stage_data.get("on_enter", [])
                if isinstance(a, dict)
            ]
            exit_conditions = [
                QuestCondition(**c) for c in stage_data.get("exit_conditions", [])
                if isinstance(c, dict)
            ]
            # Transitions stored as plain dicts (QuestTransition removed from v6)
            transitions = []
            for t in stage_data.get("transitions", []):
                if isinstance(t, dict):
                    # Normalize target key
                    if "target" in t and "target_stage" not in t:
                        t = {**t, "target_stage": t.pop("target")}
                    transitions.append(t)

            stages[stage_id] = QuestStage(
                title=stage_data.get("title", ""),
                description=stage_data.get("description", ""),
                narrative_prompt=stage_data.get("narrative_prompt", ""),
                on_enter=on_enter,
                exit_conditions=exit_conditions,
                transitions=transitions,
                max_turns=stage_data.get("max_turns"),
            )

        # Activation
        activation = data.get("activation", {})
        activation_conditions = [
            QuestCondition(**c)
            for c in activation.get("conditions", [])
            if isinstance(c, dict)
        ]

        # Rewards
        rewards_data = data.get("rewards", {})
        rewards = QuestRewards(
            affinity=rewards_data.get("affinity", {}),
            items=rewards_data.get("items", []),
            flags=rewards_data.get("flags", {}),
            unlock_quests=rewards_data.get("unlock_quests", []),
        )

        meta = data.get("meta", {})

        return QuestDefinition(
            id=quest_id,
            title=meta.get("title", quest_id),
            description=meta.get("description", ""),
            character=meta.get("character"),
            activation_type=activation.get("type", "auto"),
            activation_conditions=activation_conditions,
            trigger_event=activation.get("trigger_event"),
            hidden=bool(meta.get("hidden", False)),
            priority=int(meta.get("priority", 5)),
            mutex_group=meta.get("mutex_group"),
            required_quests=data.get("requires", []),
            requires_player_choice=bool(data.get("requires_player_choice", False)),
            choice_title=data.get("choice_title", ""),
            choice_description=data.get("choice_description", ""),
            accept_button_text=data.get("accept_button_text", "Accetta"),
            decline_button_text=data.get("decline_button_text", "Rifiuta"),
            choice_timeout_turns=data.get("choice_timeout_turns"),
            stages=stages,
            start_stage=(
                "start" if "start" in stages
                else list(stages.keys())[0] if stages
                else ""
            ),
            rewards=rewards,
        )

    # -------------------------------------------------------------------------
    # Convenience helpers
    # -------------------------------------------------------------------------

    def get_companion_list(self, world_id: str) -> List[str]:
        world = self.load_world(world_id)
        return list(world.companions.keys()) if world else []

    def get_companion(
        self, world_id: str, companion_name: str
    ) -> Optional[CompanionDefinition]:
        world = self.load_world(world_id)
        return world.companions.get(companion_name) if world else None


# =============================================================================
# Singleton
# =============================================================================

_world_loader: Optional[WorldLoader] = None


def get_world_loader() -> WorldLoader:
    global _world_loader
    if _world_loader is None:
        _world_loader = WorldLoader()
    return _world_loader


def reset_world_loader() -> None:
    global _world_loader
    _world_loader = None
