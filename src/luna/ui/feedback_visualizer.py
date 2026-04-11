"""Feedback Visualizer - Visual feedback system for gameplay events.

Shows floating notifications, toast messages, and visual effects
for game events like affinity changes, quest completions, etc.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsOpacityEffect,
    QFrame, QApplication
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QPoint, QEasingCurve
from PySide6.QtGui import QColor, QPalette


class FeedbackType(Enum):
    """Types of feedback notifications."""
    AFFINITY_GAIN = "affinity_gain"
    AFFINITY_LOSS = "affinity_loss"
    QUEST_STARTED = "quest_started"
    QUEST_COMPLETED = "quest_completed"
    QUEST_UPDATED = "quest_updated"
    ITEM_RECEIVED = "item_received"
    ITEM_USED = "item_used"
    MONEY_GAIN = "money_gain"
    MONEY_LOSS = "money_loss"
    LEVEL_UP = "level_up"
    SKILL_UNLOCKED = "skill_unlocked"
    TIER_UNLOCKED = "tier_unlocked"
    COMBAT_HIT = "combat_hit"
    COMBAT_DAMAGE = "combat_damage"
    COMBAT_VICTORY = "combat_victory"
    # Personality feedback
    BEHAVIOR_DETECTED = "behavior_detected"
    ARCHETYPE_UNLOCKED = "archetype_unlocked"
    IMPRESSION_CHANGE = "impression_change"
    SYSTEM_INFO = "system_info"
    SYSTEM_WARNING = "system_warning"
    SYSTEM_ERROR = "system_error"


@dataclass
class FeedbackEvent:
    """A feedback event to display."""
    feedback_type: FeedbackType
    title: str
    message: str
    icon: str
    color: str
    duration_ms: int = 3000
    sound_effect: Optional[str] = None


class FloatingNotification(QFrame):
    """A floating notification that fades in/out."""
    
    def __init__(
        self,
        title: str,
        message: str,
        icon: str,
        color: str,
        parent=None,
    ) -> None:
        """Initialize notification."""
        super().__init__(parent)
        
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self._setup_ui(title, message, icon, color)
        self._setup_animations()
    
    def _setup_ui(self, title: str, message: str, icon: str, color: str) -> None:
        """Setup UI."""
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {color};
                border: 2px solid #fff;
                border-radius: 12px;
                padding: 10px;
            }}
            QLabel {{
                color: #fff;
                background: transparent;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(15, 10, 15, 10)
        
        # Header with icon and title
        header = QHBoxLayout()
        
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 24px;")
        header.addWidget(icon_label)
        
        title_label = QLabel(f"<b>{title}</b>")
        title_label.setStyleSheet("font-size: 16px;")
        header.addWidget(title_label)
        header.addStretch()
        
        layout.addLayout(header)
        
        # Message
        if message:
            msg_label = QLabel(message)
            msg_label.setStyleSheet("font-size: 13px; opacity: 0.9;")
            msg_label.setWordWrap(True)
            layout.addWidget(msg_label)
        
        self.adjustSize()
    
    def _setup_animations(self) -> None:
        """Setup fade animations."""
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0)
        
        # Fade in
        self.fade_in = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_in.setDuration(300)
        self.fade_in.setStartValue(0)
        self.fade_in.setEndValue(1)
        self.fade_in.setEasingCurve(QEasingCurve.OutCubic)
        
        # Fade out
        self.fade_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out.setDuration(300)
        self.fade_out.setStartValue(1)
        self.fade_out.setEndValue(0)
        self.fade_out.setEasingCurve(QEasingCurve.InCubic)
        self.fade_out.finished.connect(self.deleteLater)
    
    def show_notification(self, duration_ms: int = 3000) -> None:
        """Show the notification with fade in/out."""
        self.show()
        self.raise_()
        
        # Fade in
        self.fade_in.start()
        
        # Schedule fade out
        QTimer.singleShot(duration_ms, self.fade_out.start)
    
    def move_to_position(self, x: int, y: int) -> None:
        """Move notification to position."""
        self.move(x, y)


class ToastManager:
    """Manages toast notifications in the corner of the screen."""
    
    def __init__(self, parent_widget: QWidget) -> None:
        """Initialize toast manager.
        
        Args:
            parent_widget: Widget to use for positioning
        """
        self.parent = parent_widget
        self._toasts: List[FloatingNotification] = []
        self._max_toasts = 5
        self._toast_height = 80
        self._toast_spacing = 10
    
    def show_toast(
        self,
        title: str,
        message: str,
        icon: str = "📢",
        color: str = "#333",
        duration_ms: int = 3000,
    ) -> None:
        """Show a toast notification.
        
        Args:
            title: Toast title
            message: Toast message
            icon: Icon emoji
            color: Background color (hex)
            duration_ms: How long to show
        """
        toast = FloatingNotification(title, message, icon, color, self.parent)
        
        # Position toast
        self._position_toast(toast)
        
        # Add to list
        self._toasts.append(toast)
        
        # Remove old toasts if too many
        while len(self._toasts) > self._max_toasts:
            old_toast = self._toasts.pop(0)
            old_toast.deleteLater()
        
        # Show
        toast.show_notification(duration_ms)
        
        # Remove from list when done
        toast.fade_out.finished.connect(lambda: self._remove_toast(toast))
    
    def _position_toast(self, toast: FloatingNotification) -> None:
        """Position toast in the corner."""
        # Get parent geometry
        parent_geo = self.parent.geometry()
        
        # Calculate position (bottom-right)
        toast_x = parent_geo.right() - toast.width() - 20
        toast_y = parent_geo.bottom() - (len(self._toasts) + 1) * (self._toast_height + self._toast_spacing) - 20
        
        toast.move_to_position(toast_x, toast_y)
    
    def _remove_toast(self, toast: FloatingNotification) -> None:
        """Remove toast from list."""
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._reposition_toasts()
    
    def _reposition_toasts(self) -> None:
        """Reposition all remaining toasts."""
        parent_geo = self.parent.geometry()
        
        for i, toast in enumerate(self._toasts):
            toast_x = parent_geo.right() - toast.width() - 20
            toast_y = parent_geo.bottom() - (i + 1) * (self._toast_height + self._toast_spacing) - 20
            toast.move_to_position(toast_x, toast_y)


class FeedbackVisualizer:
    """Main feedback visualizer class.
    
    Provides easy methods to show different types of feedback.
    """
    
    # Color scheme for different feedback types
    COLORS = {
        FeedbackType.AFFINITY_GAIN: "#E91E63",      # Pink
        FeedbackType.AFFINITY_LOSS: "#9C27B0",      # Purple
        FeedbackType.QUEST_STARTED: "#2196F3",      # Blue
        FeedbackType.QUEST_COMPLETED: "#4CAF50",    # Green
        FeedbackType.QUEST_UPDATED: "#03A9F4",      # Light Blue
        FeedbackType.ITEM_RECEIVED: "#FF9800",      # Orange
        FeedbackType.ITEM_USED: "#795548",          # Brown
        FeedbackType.MONEY_GAIN: "#FFC107",         # Gold
        FeedbackType.MONEY_LOSS: "#F44336",         # Red
        FeedbackType.LEVEL_UP: "#FFEB3B",           # Yellow
        FeedbackType.SKILL_UNLOCKED: "#9C27B0",     # Purple
        FeedbackType.TIER_UNLOCKED: "#E91E63",      # Pink
        FeedbackType.COMBAT_HIT: "#FF5722",         # Deep Orange
        FeedbackType.COMBAT_DAMAGE: "#F44336",      # Red
        FeedbackType.COMBAT_VICTORY: "#4CAF50",     # Green
        # Personality colors
        FeedbackType.BEHAVIOR_DETECTED: "#9C27B0",  # Purple
        FeedbackType.ARCHETYPE_UNLOCKED: "#FFD700", # Gold
        FeedbackType.IMPRESSION_CHANGE: "#00BCD4",  # Cyan
        FeedbackType.SYSTEM_INFO: "#607D8B",        # Blue Grey
        FeedbackType.SYSTEM_WARNING: "#FF9800",     # Orange
        FeedbackType.SYSTEM_ERROR: "#F44336",       # Red
    }
    
    ICONS = {
        FeedbackType.AFFINITY_GAIN: "❤️",
        FeedbackType.AFFINITY_LOSS: "💔",
        FeedbackType.QUEST_STARTED: "📜",
        FeedbackType.QUEST_COMPLETED: "✅",
        FeedbackType.QUEST_UPDATED: "📝",
        FeedbackType.ITEM_RECEIVED: "📦",
        FeedbackType.ITEM_USED: "🧪",
        FeedbackType.MONEY_GAIN: "💰",
        FeedbackType.MONEY_LOSS: "💸",
        FeedbackType.LEVEL_UP: "⬆️",
        FeedbackType.SKILL_UNLOCKED: "✨",
        FeedbackType.TIER_UNLOCKED: "🔓",
        FeedbackType.COMBAT_HIT: "⚔️",
        FeedbackType.COMBAT_DAMAGE: "🩸",
        FeedbackType.COMBAT_VICTORY: "🏆",
        # Personality icons
        FeedbackType.BEHAVIOR_DETECTED: "🧠",
        FeedbackType.ARCHETYPE_UNLOCKED: "🎭",
        FeedbackType.IMPRESSION_CHANGE: "👁️",
        FeedbackType.SYSTEM_INFO: "ℹ️",
        FeedbackType.SYSTEM_WARNING: "⚠️",
        FeedbackType.SYSTEM_ERROR: "❌",
    }
    
    def __init__(self, parent_widget: QWidget) -> None:
        """Initialize feedback visualizer.
        
        Args:
            parent_widget: Parent widget for positioning toasts
        """
        self.toast_manager = ToastManager(parent_widget)
    
    def show(
        self,
        feedback_type: FeedbackType,
        title: str,
        message: str = "",
        duration_ms: int = 3000,
    ) -> None:
        """Show a feedback notification.
        
        Args:
            feedback_type: Type of feedback
            title: Title text
            message: Optional message
            duration_ms: How long to show
        """
        icon = self.ICONS.get(feedback_type, "📢")
        color = self.COLORS.get(feedback_type, "#333")
        
        self.toast_manager.show_toast(title, message, icon, color, duration_ms)
    
    # Convenience methods for common feedback types
    
    def affinity_change(self, character: str, amount: int, new_value: int) -> None:
        """Show affinity change feedback."""
        if amount > 0:
            self.show(
                FeedbackType.AFFINITY_GAIN,
                f"+{amount} Affinity",
                f"{character} now likes you more! ({new_value}/100)",
                2500,
            )
        else:
            self.show(
                FeedbackType.AFFINITY_LOSS,
                f"{amount} Affinity",
                f"{character} is less interested... ({new_value}/100)",
                2500,
            )
    
    def tier_unlocked(self, character: str, tier_name: str) -> None:
        """Show tier unlock feedback."""
        self.show(
            FeedbackType.TIER_UNLOCKED,
            f"Tier Unlocked: {tier_name}",
            f"Your relationship with {character} has deepened!",
            4000,
        )
    
    def quest_started(self, quest_title: str) -> None:
        """Show quest start feedback."""
        self.show(
            FeedbackType.QUEST_STARTED,
            "Quest Started",
            quest_title,
            3000,
        )
    
    def quest_completed(self, quest_title: str, rewards: str = "") -> None:
        """Show quest completion feedback."""
        msg = f"{quest_title}"
        if rewards:
            msg += f"\nRewards: {rewards}"
        
        self.show(
            FeedbackType.QUEST_COMPLETED,
            "Quest Completed!",
            msg,
            4000,
        )
    
    def item_received(self, item_name: str, quantity: int = 1) -> None:
        """Show item received feedback."""
        qty_str = f" x{quantity}" if quantity > 1 else ""
        self.show(
            FeedbackType.ITEM_RECEIVED,
            "Item Received",
            f"{item_name}{qty_str}",
            2500,
        )
    
    def money_change(self, amount: int, new_balance: int) -> None:
        """Show money change feedback."""
        if amount > 0:
            self.show(
                FeedbackType.MONEY_GAIN,
                f"+{amount} Gold",
                f"Balance: {new_balance}",
                2500,
            )
        else:
            self.show(
                FeedbackType.MONEY_LOSS,
                f"{amount} Gold",
                f"Balance: {new_balance}",
                2500,
            )
    
    def combat_hit(self, target: str, damage: int) -> None:
        """Show combat hit feedback."""
        self.show(
            FeedbackType.COMBAT_HIT,
            f"Hit! -{damage} HP",
            f"You strike {target}",
            1500,
        )
    
    def combat_damage(self, source: str, damage: int) -> None:
        """Show damage taken feedback."""
        self.show(
            FeedbackType.COMBAT_DAMAGE,
            f"Ouch! -{damage} HP",
            f"{source} hits you",
            1500,
        )
    
    def combat_victory(self, enemies_defeated: int = 1) -> None:
        """Show combat victory feedback."""
        enemy_text = "enemy" if enemies_defeated == 1 else "enemies"
        self.show(
            FeedbackType.COMBAT_VICTORY,
            "Victory!",
            f"Defeated {enemies_defeated} {enemy_text}",
            3000,
        )
    
    def level_up(self, character: str, new_level: int) -> None:
        """Show level up feedback."""
        self.show(
            FeedbackType.LEVEL_UP,
            "Level Up!",
            f"{character} reached level {new_level}",
            4000,
        )
    
    def skill_unlocked(self, skill_name: str) -> None:
        """Show skill unlock feedback."""
        self.show(
            FeedbackType.SKILL_UNLOCKED,
            "Skill Unlocked!",
            skill_name,
            3000,
        )
    
    def success(self, title: str, message: str = "") -> None:
        """Show success feedback."""
        self.show(FeedbackType.QUEST_COMPLETED, title, message, 3000)
    
    def info(self, title: str, message: str = "") -> None:
        """Show info feedback."""
        self.show(FeedbackType.SYSTEM_INFO, title, message, 3000)
    
    def warning(self, title: str, message: str = "") -> None:
        """Show warning feedback."""
        self.show(FeedbackType.SYSTEM_WARNING, title, message, 4000)
    
    def error(self, title: str, message: str = "") -> None:
        """Show error feedback."""
        self.show(FeedbackType.SYSTEM_ERROR, title, message, 5000)
    
    # Personality feedback methods
    
    def behavior_detected(self, companion: str, behavior: str) -> None:
        """Show behavior detection feedback."""
        self.show(
            FeedbackType.BEHAVIOR_DETECTED,
            f"{companion} has noticed...",
            f"You seem {behavior.lower()}",
            3000,
        )
    
    def archetype_unlocked(self, archetype: str) -> None:
        """Show archetype unlock feedback."""
        self.show(
            FeedbackType.ARCHETYPE_UNLOCKED,
            "Personality Profile Updated!",
            f"You are now: {archetype}",
            5000,
        )
    
    def impression_change(self, companion: str, dimension: str, delta: int) -> None:
        """Show impression change feedback."""
        direction = "↑" if delta > 0 else "↓"
        self.show(
            FeedbackType.IMPRESSION_CHANGE,
            f"{companion}'s perception changed",
            f"{dimension}: {direction}{abs(delta)}",
            2500,
        )


class InlineFeedbackWidget(QFrame):
    """Widget for inline feedback in the story log.
    
    Shows small badges/chips for immediate feedback.
    """
    
    def __init__(self, parent=None) -> None:
        """Initialize inline feedback widget."""
        super().__init__(parent)
        
        self.setFrameStyle(QFrame.NoFrame)
        self.setStyleSheet("background: transparent;")
        
        self.layout = QHBoxLayout(self)
        self.layout.setSpacing(8)
        self.layout.setContentsMargins(0, 0, 0, 0)
    
    def add_badge(self, text: str, color: str = "#4CAF50") -> None:
        """Add a feedback badge."""
        badge = QLabel(f"  {text}  ")
        badge.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: white;
                border-radius: 10px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: bold;
            }}
        """)
        self.layout.addWidget(badge)
        
        # Auto-remove after delay
        QTimer.singleShot(5000, badge.deleteLater)
    
    def clear_badges(self) -> None:
        """Clear all badges."""
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
