"""Quest Choice Widget - Multiple choice dialog for quest decisions.

Replaces text-based choices with clear, clickable buttons.
Prevents LLM misinterpretation of player intent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Callable

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QSpacerItem,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


@dataclass
class QuestChoice:
    """A single choice option."""
    choice_id: str
    text: str
    description: str = ""
    icon: str = "⭕"
    style: str = "default"  # default, positive, negative, neutral


class ChoiceButton(QPushButton):
    """Button for a single choice."""
    
    def __init__(
        self,
        choice: QuestChoice,
        parent=None,
    ) -> None:
        """Initialize choice button."""
        super().__init__(parent)
        
        self.choice = choice
        
        # Style based on choice type
        self._setup_style(choice.style)
        
        # Layout with icon and text
        self.setText(f"{choice.icon} {choice.text}")
        self.setToolTip(choice.description)
        
        # Size and alignment
        self.setMinimumHeight(44)
        self.setMaximumHeight(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # Font
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.setFont(font)
    
    def _setup_style(self, style: str) -> None:
        """Setup button style."""
        styles = {
            "positive": ("#4CAF50", "#66BB6A", "#2E7D32"),  # Green
            "negative": ("#F44336", "#EF5350", "#C62828"),  # Red
            "neutral": ("#2196F3", "#42A5F5", "#1565C0"),   # Blue
            "default": ("#607D8B", "#78909C", "#455A64"),   # Gray
        }
        
        bg, hover, border = styles.get(style, styles["default"])
        
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: white;
                border: 2px solid {border};
                border-radius: 8px;
                padding: 10px 20px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {hover};
                border-color: {hover};
            }}
            QPushButton:pressed {{
                background-color: {border};
            }}
        """)


class QuestChoiceWidget(QFrame):
    """Widget for displaying quest choices.
    
    Shows a dialog-like interface with multiple choice buttons.
    Blocks normal input until a choice is made.
    
    Signals:
        choice_made: Emitted when player selects a choice (choice_id)
        cancelled: Emitted when player dismisses without choosing
    """
    
    choice_made = Signal(str)  # choice_id
    cancelled = Signal()
    
    def __init__(self, parent=None) -> None:
        """Initialize quest choice widget."""
        super().__init__(parent)
        
        self._choices: List[QuestChoice] = []
        self._buttons: List[ChoiceButton] = []
        
        self._setup_ui()
        self.hide()  # Hidden by default
    
    def _setup_ui(self) -> None:
        """Setup UI."""
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
                border: 3px solid #4CAF50;
                border-radius: 12px;
            }
        """)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header_layout = QHBoxLayout()
        
        self.icon_label = QLabel("🎯")
        self.icon_label.setStyleSheet("font-size: 32px;")
        header_layout.addWidget(self.icon_label)
        
        header_text = QVBoxLayout()
        
        self.title_label = QLabel("SCelta Importante")
        self.title_label.setStyleSheet("""
            color: #4CAF50;
            font-size: 18px;
            font-weight: bold;
        """)
        header_text.addWidget(self.title_label)
        
        self.subtitle_label = QLabel("La tua decisione influenzerà la storia...")
        self.subtitle_label.setStyleSheet("color: #888; font-size: 12px;")
        header_text.addWidget(self.subtitle_label)
        
        header_layout.addLayout(header_text, 1)
        layout.addLayout(header_layout)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #444;")
        separator.setFixedHeight(2)
        layout.addWidget(separator)
        
        # Question/Context
        self.context_label = QLabel("Cosa vuoi fare?")
        self.context_label.setStyleSheet("""
            color: #fff;
            font-size: 14px;
            padding: 10px 0;
        """)
        self.context_label.setWordWrap(True)
        layout.addWidget(self.context_label)
        
        # Choices container
        self.choices_layout = QVBoxLayout()
        self.choices_layout.setSpacing(10)
        layout.addLayout(self.choices_layout)
        
        # Cancel button (optional)
        self.cancel_button = QPushButton("❌ Annulla / Pensa ancora")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #666;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #999;
                border-color: #666;
            }
        """)
        self.cancel_button.clicked.connect(self._on_cancel)
        layout.addWidget(self.cancel_button)
        
        layout.addStretch()
    
    def show_choices(
        self,
        title: str,
        context: str,
        choices: List[QuestChoice],
        subtitle: str = "La tua decisione influenzerà la storia...",
        show_cancel: bool = True,
    ) -> None:
        """Show choice dialog.
        
        Args:
            title: Dialog title (e.g., "Proposta di Luna")
            context: Question or situation text
            choices: List of choice options
            subtitle: Optional subtitle
            show_cancel: Whether to show cancel button
        """
        self.title_label.setText(f"🎯 {title}")
        self.context_label.setText(context)
        self.subtitle_label.setText(subtitle)
        
        # Clear old choices
        self._clear_choices()
        
        # Add new choice buttons
        for choice in choices:
            button = ChoiceButton(choice)
            button.clicked.connect(lambda checked, cid=choice.choice_id: self._on_choice(cid))
            self.choices_layout.addWidget(button)
            self._buttons.append(button)
        
        # Show/hide cancel
        self.cancel_button.setVisible(show_cancel)
        
        self.show()
        self.raise_()
    
    def show_quest_acceptance(
        self,
        quest_title: str,
        quest_description: str,
        giver_name: str,
    ) -> None:
        """Show standard quest acceptance dialog.
        
        Args:
            quest_title: Title of the quest
            quest_description: Brief description
            giver_name: Name of NPC giving the quest
        """
        choices = [
            QuestChoice(
                choice_id="accept",
                text="Accetta",
                description="Inizia la quest",
                icon="✅",
                style="positive",
            ),
            QuestChoice(
                choice_id="decline",
                text="Rifiuta",
                description="Non ora",
                icon="❌",
                style="negative",
            ),
            QuestChoice(
                choice_id="ask_more",
                text="Dimmi di più",
                description="Chiedi dettagli",
                icon="❓",
                style="neutral",
            ),
        ]
        
        self.show_choices(
            title=f"Missione da {giver_name}",
            context=f"📜 {quest_title}\n\n{quest_description}",
            choices=choices,
            subtitle="Vuoi accettare questa missione?",
            show_cancel=True,
        )
    
    def show_binary_choice(
        self,
        title: str,
        question: str,
        yes_text: str = "Sì",
        no_text: str = "No",
        yes_icon: str = "✅",
        no_icon: str = "❌",
    ) -> None:
        """Show simple yes/no choice.
        
        Args:
            title: Dialog title
            question: Question to ask
            yes_text: Text for yes button
            no_text: Text for no button
        """
        choices = [
            QuestChoice(
                choice_id="yes",
                text=yes_text,
                icon=yes_icon,
                style="positive",
            ),
            QuestChoice(
                choice_id="no",
                text=no_text,
                icon=no_icon,
                style="negative",
            ),
        ]
        
        self.show_choices(
            title=title,
            context=question,
            choices=choices,
            show_cancel=False,
        )
    
    def _on_choice(self, choice_id: str) -> None:
        """Handle choice selection."""
        self.choice_made.emit(choice_id)
        self.hide()
    
    def _on_cancel(self) -> None:
        """Handle cancel."""
        self.cancelled.emit()
        self.hide()
    
    def _clear_choices(self) -> None:
        """Clear all choice buttons."""
        for button in self._buttons:
            button.deleteLater()
        self._buttons.clear()
    
    def is_active(self) -> bool:
        """Check if choice dialog is currently shown."""
        return self.isVisible()
    
    def hide_choices(self) -> None:
        """Hide choice dialog."""
        self.hide()
        self._clear_choices()


class PendingChoiceManager:
    """Manages pending choices that need player decision.
    
    Integrates with GameEngine to intercept quest activations
    that require player choice before proceeding.
    """
    
    def __init__(self) -> None:
        """Initialize manager."""
        self.pending_choices: dict = {}
        self._current_choice_id: Optional[str] = None
    
    def register_quest_choice(
        self,
        quest_id: str,
        title: str,
        description: str,
        giver: str,
    ) -> str:
        """Register a quest that needs acceptance choice.
        
        Returns:
            choice_id to track this choice
        """
        choice_id = f"quest_{quest_id}_accept"
        self.pending_choices[choice_id] = {
            "type": "quest_accept",
            "quest_id": quest_id,
            "title": title,
            "description": description,
            "giver": giver,
        }
        return choice_id
    
    def get_choice_data(self, choice_id: str) -> Optional[dict]:
        """Get data for a pending choice."""
        return self.pending_choices.get(choice_id)
    
    def resolve_choice(self, choice_id: str, result: str) -> Optional[dict]:
        """Resolve a choice with player decision.
        
        Args:
            choice_id: The choice that was made
            result: The result (e.g., "accept", "decline")
            
        Returns:
            Choice data if resolved, None if not found
        """
        data = self.pending_choices.pop(choice_id, None)
        if data:
            data["result"] = result
        return data
    
    def has_pending(self) -> bool:
        """Check if there are pending choices."""
        return len(self.pending_choices) > 0
    
    def clear(self) -> None:
        """Clear all pending choices."""
        self.pending_choices.clear()
