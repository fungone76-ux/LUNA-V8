"""NPC Actions Widget — UI component for NPC Secondary Activation System.

Shows two sections in a horizontal layout:
- NPC ACTIONS (left): Dynamic todo list of active goals
- LUOGHI & PERSONE (right): Static directory of reactive NPCs
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout,
    QLabel, QWidget, QFrame, QScrollArea
)
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from luna.systems.npc_goal_evaluator import NpcAction
    from luna.core.models import GameState, WorldDefinition


def _get_value(obj, key: str, default=None):
    """Safely get value from object or dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# Icons for initiative styles
_STYLE_ICONS = {
    "friendly": "📬",
    "authority": "⚠️",
    "secret_keeper": "🔍",
    "reactive": "💬",
}

# Style colors — bright enough to be visible on dark background
_STYLE_COLORS = {
    "friendly": "#66BB6A",       # Bright green
    "authority": "#EF5350",       # Bright red
    "secret_keeper": "#FFA726",  # Bright orange
    "reactive": "#42A5F5",        # Bright blue
}

_STYLESHEET = """
QGroupBox {
    color: #e0e0e0;
    font-size: 11px;
    font-weight: bold;
    border: 1px solid #5a5a5a;
    border-radius: 5px;
    margin-top: 6px;
    padding-top: 4px;
    background-color: #1e1e1e;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 5px;
    color: #c8c8c8;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    width: 6px;
    background: #2a2a2a;
}
QScrollBar::handle:vertical {
    background: #555;
    border-radius: 3px;
}
"""


class _SectionLabel(QLabel):
    """Styled section header."""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(
            "color: #9e9e9e; font-size: 9px; font-weight: bold; "
            "letter-spacing: 1px; padding-bottom: 2px;"
        )


class NpcActionsWidget(QGroupBox):
    """Horizontal widget showing NPC actions (left) and directory (right)."""

    MAX_ACTIONS = 5

    def __init__(
        self,
        world: Optional["WorldDefinition"] = None,
        parent: Optional[QWidget] = None
    ) -> None:
        super().__init__("NPC ACTIONS & LUOGHI & PERSONE", parent)
        self.world = world
        self._action_widgets: dict[str, QWidget] = {}
        self._directory_widgets: dict[str, QWidget] = {}

        self._setup_ui()
        if world:
            self._build_directory(world)

    def _setup_ui(self) -> None:
        self.setStyleSheet(_STYLESHEET)
        self.setMaximumHeight(200)
        self.setMinimumHeight(150)

        outer = QHBoxLayout(self)
        outer.setSpacing(0)
        outer.setContentsMargins(6, 14, 6, 6)

        # ── Left: NPC ACTIONS ──────────────────────────────────────────────
        left_col = QWidget()
        left_col.setMinimumWidth(200)
        left_vbox = QVBoxLayout(left_col)
        left_vbox.setSpacing(4)
        left_vbox.setContentsMargins(0, 0, 8, 0)

        left_vbox.addWidget(_SectionLabel("AZIONI NPC"))

        self._actions_scroll = QScrollArea()
        self._actions_scroll.setWidgetResizable(True)
        self._actions_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._actions_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        actions_inner = QWidget()
        self._actions_layout = QVBoxLayout(actions_inner)
        self._actions_layout.setSpacing(3)
        self._actions_layout.setContentsMargins(0, 0, 0, 0)
        self._actions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._empty_label = QLabel("(nessuna azione pendente)")
        self._empty_label.setStyleSheet("color: #5a5a5a; font-style: italic; font-size: 10px;")
        self._actions_layout.addWidget(self._empty_label)

        self._actions_scroll.setWidget(actions_inner)
        left_vbox.addWidget(self._actions_scroll)

        outer.addWidget(left_col, stretch=2)

        # ── Vertical separator ──────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #444; background-color: #444;")
        sep.setMaximumWidth(1)
        outer.addWidget(sep)

        # ── Right: LUOGHI & PERSONE ────────────────────────────────────────
        right_col = QWidget()
        right_vbox = QVBoxLayout(right_col)
        right_vbox.setSpacing(4)
        right_vbox.setContentsMargins(8, 0, 0, 0)

        right_vbox.addWidget(_SectionLabel("LUOGHI & PERSONE"))

        self._dir_scroll = QScrollArea()
        self._dir_scroll.setWidgetResizable(True)
        self._dir_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._dir_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        dir_inner = QWidget()
        self._directory_layout = QVBoxLayout(dir_inner)
        self._directory_layout.setSpacing(4)
        self._directory_layout.setContentsMargins(0, 0, 0, 0)
        self._directory_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._dir_scroll.setWidget(dir_inner)
        right_vbox.addWidget(self._dir_scroll)

        outer.addWidget(right_col, stretch=3)

    # ──────────────────────────────────────────────────────────────────────
    # Directory
    # ──────────────────────────────────────────────────────────────────────

    def _build_directory(self, world: "WorldDefinition") -> None:
        """Build the static directory of reactive and secret_keeper NPCs."""
        if not world or not hasattr(world, 'npc_templates'):
            return

        for npc_id, npc_def in world.npc_templates.items():
            initiative_style = _get_value(npc_def, 'initiative_style', 'reactive')

            # Show reactive and secret_keeper in directory
            if initiative_style not in ('reactive', 'secret_keeper'):
                continue

            npc_name = _get_value(npc_def, 'name', npc_id)
            icon = _STYLE_ICONS.get(initiative_style, "💬")

            # Location display name
            spawn_locs = _get_value(npc_def, 'spawn_locations', [])
            location = spawn_locs[0] if spawn_locs else "?"
            if hasattr(world, 'locations') and location in world.locations:
                loc_obj = world.locations[location]
                location = getattr(loc_obj, 'name', location)

            # Schedule times
            schedule = _get_value(npc_def, 'schedule', {})
            times = "/".join(schedule.keys()) if schedule else "Sempre"

            entry = self._create_directory_entry(
                icon=icon, name=npc_name,
                location=location, times=times,
                style=initiative_style,
            )
            self._directory_layout.addWidget(entry)
            self._directory_widgets[npc_id] = entry

    def _create_directory_entry(
        self, icon: str, name: str,
        location: str, times: str, style: str
    ) -> QWidget:
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(1)
        vbox.setContentsMargins(0, 1, 0, 1)

        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setSpacing(4)
        hbox.setContentsMargins(0, 0, 0, 0)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 12px;")
        icon_lbl.setFixedWidth(18)

        color = _STYLE_COLORS.get(style, "#aaa")
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 11px;")

        hbox.addWidget(icon_lbl)
        hbox.addWidget(name_lbl)
        hbox.addStretch()
        vbox.addWidget(row)

        detail = QLabel(f"{location}  ·  {times}")
        detail.setStyleSheet("color: #777; font-size: 9px; padding-left: 22px;")
        vbox.addWidget(detail)

        return container

    # ──────────────────────────────────────────────────────────────────────
    # Dynamic actions
    # ──────────────────────────────────────────────────────────────────────

    def add_action(self, action: "NpcAction") -> bool:
        """Add an action to the dynamic list. Returns True if added."""
        if len(self._action_widgets) >= self.MAX_ACTIONS:
            return False
        if action.npc_id in self._action_widgets:
            return False  # already shown

        self._empty_label.hide()

        widget = self._create_action_widget(action)
        self._action_widgets[action.npc_id] = widget
        self._actions_layout.addWidget(widget)
        return True

    def _create_action_widget(self, action: "NpcAction") -> QWidget:
        container = QWidget()
        container.setStyleSheet(
            "QWidget { background-color: #252525; border-radius: 3px; }"
        )
        vbox = QVBoxLayout(container)
        vbox.setSpacing(2)
        vbox.setContentsMargins(6, 4, 6, 4)

        # Header row: icon + name
        row = QWidget()
        row.setStyleSheet("QWidget { background: transparent; }")
        hbox = QHBoxLayout(row)
        hbox.setSpacing(5)
        hbox.setContentsMargins(0, 0, 0, 0)

        icon = _STYLE_ICONS.get(action.initiative_style, "📬")
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 14px; background: transparent;")
        icon_lbl.setFixedWidth(20)

        color = _STYLE_COLORS.get(action.initiative_style, "#ccc")
        name_lbl = QLabel(action.npc_display_name)
        name_lbl.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 11px; background: transparent;"
        )

        hbox.addWidget(icon_lbl)
        hbox.addWidget(name_lbl)
        hbox.addStretch()
        vbox.addWidget(row)

        # Secret subject (secret_keeper only)
        if action.secret_subject:
            secret = QLabel(f"  {action.secret_subject}")
            secret.setStyleSheet(
                "color: #FFA726; font-size: 9px; font-style: italic; background: transparent;"
            )
            vbox.addWidget(secret)

        # Location · time
        detail = QLabel(f"  {action.location_display}  ·  {action.time_display}")
        detail.setStyleSheet("color: #999; font-size: 9px; background: transparent;")
        vbox.addWidget(detail)

        return container

    def remove_action(self, npc_id: str) -> None:
        if npc_id in self._action_widgets:
            self._action_widgets.pop(npc_id).deleteLater()
        if not self._action_widgets:
            self._empty_label.show()

    def update_from_state(self, game_state: "GameState") -> None:
        if not game_state:
            return
        active_npcs = getattr(game_state, 'active_npc_actions', set())
        for npc_id in list(self._action_widgets.keys()):
            if npc_id not in active_npcs:
                self.remove_action(npc_id)

    def clear_actions(self) -> None:
        for widget in self._action_widgets.values():
            widget.deleteLater()
        self._action_widgets.clear()
        self._empty_label.show()
