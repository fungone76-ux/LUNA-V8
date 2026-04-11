"""Action Bar UI - Context-aware action buttons.

Displays available actions as clickable buttons with icons and tooltips.
Integrates with GameplayManager to show only valid actions.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Callable

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QToolButton, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont


class ActionButton(QPushButton):
    """Button for a single action."""
    
    clicked_with_id = Signal(str, str)  # action_id, target
    
    def __init__(
        self,
        action_id: str,
        name: str,
        description: str,
        icon: str,
        category: str,
        enabled: bool = True,
        requires_target: bool = False,
        target_type: Optional[str] = None,
        parent=None,
    ) -> None:
        """Initialize action button."""
        super().__init__(parent)
        
        self.action_id = action_id
        self.action_name = name
        self.description = description
        self.requires_target = requires_target
        self.target_type = target_type
        self._category = category
        
        # Style based on category
        self._setup_style(category, enabled)
        
        # Set text with icon
        self.setText(f"{icon} {name}")
        self.setToolTip(f"<b>{name}</b><br>{description}")
        
        # Size
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # Connect
        self.clicked.connect(self._on_clicked)
        
        self.setEnabled(enabled)
    
    def _setup_style(self, category: str, enabled: bool) -> None:
        """Setup button style based on category."""
        # Category colors
        colors = {
            "social": ("#E91E63", "#F48FB1"),      # Pink
            "combat": ("#F44336", "#EF9A9A"),      # Red
            "item": ("#9C27B0", "#CE93D8"),        # Purple
            "economy": ("#FFC107", "#FFE082"),     # Gold
            "movement": ("#4CAF50", "#A5D6A7"),    # Green
            "quest": ("#2196F3", "#90CAF9"),       # Blue
            "skill": ("#FF9800", "#FFCC80"),       # Orange
        }
        
        bg_color, hover_color = colors.get(category, ("#607D8B", "#B0BEC5"))
        
        if not enabled:
            bg_color = "#424242"
            hover_color = "#424242"
        
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: {'#000' if category == 'economy' else '#fff'};
                border: 2px solid {bg_color};
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                font-weight: bold;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
                border-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: {bg_color};
            }}
            QPushButton:disabled {{
                background-color: #333;
                color: #666;
                border-color: #444;
            }}
        """)
    
    def _on_clicked(self) -> None:
        """Handle button click."""
        # For now, emit without target (target selection will be handled by dialog)
        self.clicked_with_id.emit(self.action_id, "")


class ActionCategoryWidget(QFrame):
    """Widget for a category of actions."""
    
    action_triggered = Signal(str, str)  # action_id, target
    
    def __init__(self, category: str, title: str, icon: str, parent=None) -> None:
        """Initialize category widget."""
        super().__init__(parent)
        
        self.category = category
        self._buttons: Dict[str, ActionButton] = {}
        
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border: 1px solid #444;
                border-radius: 8px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Header
        header = QLabel(f"{icon} {title}")
        header.setStyleSheet("""
            color: #fff;
            font-size: 14px;
            font-weight: bold;
            padding-bottom: 4px;
            border-bottom: 2px solid #444;
        """)
        layout.addWidget(header)
        
        # Buttons container
        self.buttons_layout = QVBoxLayout()
        self.buttons_layout.setSpacing(4)
        layout.addLayout(self.buttons_layout)
        
        layout.addStretch()
    
    def add_action(self, action_data: Dict[str, Any]) -> None:
        """Add an action button."""
        action_id = action_data["action_id"]
        
        # Remove existing if present
        if action_id in self._buttons:
            self._remove_button(action_id)
        
        button = ActionButton(
            action_id=action_id,
            name=action_data["name"],
            description=action_data["description"],
            icon=action_data.get("icon", "🎯"),
            category=action_data.get("category", "general"),
            enabled=action_data.get("enabled", True),
            requires_target=action_data.get("requires_target", False),
            target_type=action_data.get("target_type"),
        )
        
        button.clicked_with_id.connect(self.action_triggered.emit)
        self.buttons_layout.addWidget(button)
        self._buttons[action_id] = button
    
    def update_actions(self, actions: List[Dict[str, Any]]) -> None:
        """Update all actions in this category."""
        # Clear existing
        for action_id in list(self._buttons.keys()):
            self._remove_button(action_id)
        
        # Add new
        for action_data in actions:
            if action_data.get("category") == self.category:
                self.add_action(action_data)
    
    def _remove_button(self, action_id: str) -> None:
        """Remove a button."""
        if action_id in self._buttons:
            button = self._buttons.pop(action_id)
            button.deleteLater()
    
    def set_action_enabled(self, action_id: str, enabled: bool) -> None:
        """Enable/disable a specific action."""
        if action_id in self._buttons:
            self._buttons[action_id].setEnabled(enabled)
    
    def has_actions(self) -> bool:
        """Check if category has any actions."""
        return len(self._buttons) > 0


class ActionBarWidget(QScrollArea):
    """Action bar with categorized action buttons.
    
    Displays context-aware actions grouped by category:
    - Social (flirt, hug, gift...)
    - Item (use potion, equip...)
    - Combat (attack, defend...)
    - Movement (go to...)
    - Quest (accept, complete...)
    """
    
    action_triggered = Signal(str, str)  # action_id, target
    
    def __init__(self, parent=None) -> None:
        """Initialize action bar."""
        super().__init__(parent)
        
        self._categories: Dict[str, ActionCategoryWidget] = {}
        self._actions_cache: List[Dict[str, Any]] = []
        
        self.setMinimumWidth(200)
        self.setMaximumWidth(280)
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup UI."""
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setMaximumWidth(280)
        self.setMinimumWidth(200)
        
        self.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #1e1e1e;
            }
            QScrollBar:vertical {
                background-color: #2d2d2d;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #555;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666;
            }
        """)
        
        # Container widget
        container = QWidget()
        self.setWidget(container)
        
        self.main_layout = QVBoxLayout(container)
        self.main_layout.setSpacing(12)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Title
        title = QLabel("🎮 Actions")
        title.setStyleSheet("""
            color: #4CAF50;
            font-size: 18px;
            font-weight: bold;
            padding: 5px;
        """)
        self.main_layout.addWidget(title)
        
        # Create category widgets
        self._create_categories()
        
        self.main_layout.addStretch()
    
    def _create_categories(self) -> None:
        """Create category widgets."""
        categories = [
            ("social", "Social", "💬"),
            ("item", "Items", "🎒"),
            ("combat", "Combat", "⚔️"),
            ("economy", "Economy", "💰"),
            ("movement", "Movement", "🚶"),
            ("quest", "Quest", "📜"),
            ("skill", "Skills", "✨"),
        ]
        
        for cat_id, title, icon in categories:
            widget = ActionCategoryWidget(cat_id, title, icon)
            widget.action_triggered.connect(self.action_triggered.emit)
            self._categories[cat_id] = widget
            self.main_layout.addWidget(widget)
            widget.hide()  # Hidden by default until actions are added
    
    def update_actions(self, actions: List[Dict[str, Any]]) -> None:
        """Update all actions.
        
        Args:
            actions: List of action dictionaries from GameplayManager
        """
        self._actions_cache = actions
        
        # Group by category
        by_category: Dict[str, List[Dict[str, Any]]] = {}
        for action in actions:
            cat = action.get("category", "general")
            by_category.setdefault(cat, []).append(action)
        
        # Update each category
        for cat_id, widget in self._categories.items():
            if cat_id in by_category:
                widget.update_actions(by_category[cat_id])
                widget.show()
            else:
                widget.hide()
    
    def refresh_actions(self) -> None:
        """Refresh with cached actions."""
        self.update_actions(self._actions_cache)
    
    def set_action_enabled(self, action_id: str, enabled: bool) -> None:
        """Enable/disable a specific action."""
        for widget in self._categories.values():
            widget.set_action_enabled(action_id, enabled)
    
    def clear(self) -> None:
        """Clear all actions."""
        for widget in self._categories.values():
            widget.update_actions([])
            widget.hide()
        self._actions_cache = []


class QuickActionBar(QFrame):
    """Horizontal quick action bar for most common actions.
    
    Shows the top 3-4 most relevant actions as large buttons.
    """
    
    action_triggered = Signal(str, str)
    
    def __init__(self, parent=None) -> None:
        """Initialize quick action bar."""
        super().__init__(parent)
        
        self._buttons: List[QPushButton] = []
        
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border: 1px solid #444;
                border-radius: 8px;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 5, 10, 5)
        
        self.buttons_layout = QHBoxLayout()
        layout.addLayout(self.buttons_layout)
        layout.addStretch()
    
    def update_actions(self, actions: List[Dict[str, Any]]) -> None:
        """Update quick actions (shows first 4 enabled actions)."""
        # Clear existing
        for button in self._buttons:
            button.deleteLater()
        self._buttons.clear()
        
        # Add up to 4 enabled actions
        count = 0
        for action in actions:
            if action.get("enabled", True) and count < 4:
                self._add_button(action)
                count += 1
    
    def _add_button(self, action_data: Dict[str, Any]) -> None:
        """Add a quick action button."""
        button = QPushButton(f"{action_data.get('icon', '🎯')} {action_data['name']}")
        button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #66BB6A;
            }
        """)
        button.setToolTip(action_data.get("description", ""))
        
        action_id = action_data["action_id"]
        button.clicked.connect(lambda: self.action_triggered.emit(action_id, ""))
        
        self.buttons_layout.addWidget(button)
        self._buttons.append(button)
