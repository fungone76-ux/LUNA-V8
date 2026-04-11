"""UI Widgets for Luna RPG v4.

Quest tracker, companion status, event display, etc.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QProgressBar,
    QGroupBox, QScrollArea, QFrame, QPushButton,
)
from PySide6.QtCore import Qt, Signal


class StoryBeatsWidget(QGroupBox):
    """Widget for displaying story beats for active companion."""

    def __init__(self, parent=None) -> None:
        """Initialize story beats widget."""
        super().__init__("🎭 Story Beats", parent)
        self.setMaximumHeight(180)
        self.setMinimumHeight(120)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 12, 8, 8)

        # Header with companion name
        self.lbl_companion = QLabel("Nessun companion attivo")
        self.lbl_companion.setStyleSheet("color: #aaa; font-weight: bold; font-size: 12px;")
        layout.addWidget(self.lbl_companion)

        # Beats list
        self.beats_list = QListWidget()
        self.beats_list.setStyleSheet("""
            QListWidget {
                background-color: #2d2d2d;
                border: 1px solid #444;
                border-radius: 4px;
                color: #fff;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 4px;
                border-bottom: 1px solid #333;
            }
        """)
        self.beats_list.setMaximumHeight(80)
        layout.addWidget(self.beats_list)

        # Progress summary
        self.lbl_progress = QLabel("")
        self.lbl_progress.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(self.lbl_progress)

    def update_beats(self, companion_name: str, beats: List[dict]) -> None:
        """Update beats for current companion.
        
        Args:
            companion_name: Name of active companion
            beats: List of beat dicts with 'title', 'required_affinity', 'current_affinity', 'completed'
        """
        self.lbl_companion.setText(f"🎭 {companion_name}")
        self.beats_list.clear()
        
        completed_count = 0
        for beat in beats:
            title = beat.get('title', 'Unknown')
            req_aff = beat.get('required_affinity', 0)
            cur_aff = beat.get('current_affinity', 0)
            completed = beat.get('completed', False)
            
            if completed:
                icon = "✅"
                text = f"{icon} {title}"
                completed_count += 1
            elif cur_aff >= req_aff:
                icon = "🟢"
                text = f"{icon} {title} (pronta!)"
            else:
                icon = "🔒"
                text = f"{icon} {title} ({cur_aff}/{req_aff})"
            
            item = QListWidgetItem(text)
            if completed:
                item.setForeground(Qt.gray)
            elif cur_aff >= req_aff:
                item.setForeground(Qt.green)
            
            self.beats_list.addItem(item)
        
        # Update progress
        total = len(beats)
        if total > 0:
            self.lbl_progress.setText(f"Progresso: {completed_count}/{total} beats completati")
        else:
            self.lbl_progress.setText("Nessun beat disponibile")


class QuestTrackerWidget(QGroupBox):
    """Widget for tracking active quests with activation button."""
    
    # Signal emitted when user clicks to activate a quest
    quest_activate_requested = Signal(str)  # quest_id

    def __init__(self, parent=None) -> None:
        """Initialize quest tracker."""
        super().__init__("📋 Quest", parent)
        self.setMaximumHeight(200)
        self.setMinimumHeight(120)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # Quest list
        self.quest_list = QListWidget()
        self.quest_list.setStyleSheet("""
            QListWidget {
                background-color: #2d2d2d;
                border: 1px solid #444;
                border-radius: 4px;
                color: #fff;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #444;
            }
            QListWidget::item:selected {
                background-color: #4CAF50;
            }
        """)
        layout.addWidget(self.quest_list)

        # Activate button (hidden by default)
        self.btn_activate = QPushButton("🎯 Clicca qui per attivare")
        self.btn_activate.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 6px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        self.btn_activate.setVisible(False)
        self.btn_activate.clicked.connect(self._on_activate_clicked)
        layout.addWidget(self.btn_activate)

        # Detail label
        self.lbl_detail = QLabel("No active quests")
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.lbl_detail)

        self.quest_list.currentRowChanged.connect(self._on_quest_selected)
        
        # Store current quest data
        self._current_quests: List[dict] = []
        self._selected_quest_id: Optional[str] = None

    def _on_quest_selected(self, row: int) -> None:
        """Handle quest selection."""
        if row >= 0 and row < len(self._current_quests):
            quest = self._current_quests[row]
            self._selected_quest_id = quest.get('quest_id')
            self.lbl_detail.setText(quest.get('description', ''))
            
            # Show activate button if quest is available (not active or completed)
            status = quest.get('status', '')
            requirements = quest.get('requirements', {})
            can_activate = status == 'available' and requirements
            
            self.btn_activate.setVisible(can_activate)
            if can_activate:
                req_text = f"Richiede: Affinity {requirements.get('affinity', '??')}"
                self.btn_activate.setToolTip(req_text)
        else:
            self._selected_quest_id = None
            self.btn_activate.setVisible(False)

    def _on_activate_clicked(self) -> None:
        """Emit signal to activate selected quest."""
        if self._selected_quest_id:
            self.quest_activate_requested.emit(self._selected_quest_id)

    def update_quests(self, quests: List[dict]) -> None:
        """Update quest list.
        
        Args:
            quests: List of quest dicts with 'quest_id', 'title', 'status', 'description', 'requirements'
        """
        self._current_quests = quests
        self.quest_list.clear()
        self.btn_activate.setVisible(False)

        for quest in quests:
            status = quest.get('status', 'unknown')
            if status == 'active':
                icon = "🟢"
            elif status == 'completed':
                icon = "✅"
            elif status == 'available':
                icon = "⭐"  # Available but not started
            else:
                icon = "🔴"
            
            title = quest.get('title', 'Unknown Quest')
            item = QListWidgetItem(f"{icon} {title}")
            item.setToolTip(quest.get('description', ''))

            if status == 'completed':
                item.setForeground(Qt.gray)
            elif status == 'available':
                item.setForeground(Qt.yellow)

            self.quest_list.addItem(item)


class CompanionStatusWidget(QGroupBox):
    """Widget for displaying Luna, Maria and Stella status only."""

    _ALLOWED = {"luna", "stella", "maria"}

    # Color per companion (barra affinità)
    _COLORS = {
        "luna":   "#9C88FF",
        "stella": "#FF9F43",
        "maria":  "#E84393",
    }

    def __init__(self, parent=None) -> None:
        super().__init__("COMPANION", parent)
        self.setMinimumHeight(80)
        self.setMaximumHeight(200)
        self.setMinimumWidth(180)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 14, 8, 6)

        self.companion_widgets: Dict[str, dict] = {}

        self.setStyleSheet("""
            QGroupBox {
                color: #bbb;
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 1px;
                border: 1px solid #444;
                border-radius: 4px;
                margin-top: 6px;
                padding-top: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
            QProgressBar {
                border: none;
                border-radius: 3px;
                background-color: #2a2a2a;
                max-height: 6px;
                text-align: center;
            }
            QProgressBar::chunk {
                border-radius: 3px;
            }
        """)

    def _affinity_color(self, name: str, value: int) -> str:
        base = self._COLORS.get(name.lower(), "#9C88FF")
        # Desatura leggermente se affinità bassa
        if value < 20:
            return "#555555"
        return base

    def _make_row(self, name: str) -> dict:
        color = self._COLORS.get(name.lower(), "#9C88FF")
        display = name.capitalize()

        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setSpacing(2)
        row_layout.setContentsMargins(0, 0, 0, 0)

        # Header: nome + valore numerico
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        lbl_name = QLabel(display)
        lbl_name.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold;")

        lbl_value = QLabel("0")
        lbl_value.setStyleSheet("color: #777; font-size: 10px; min-width: 28px;")
        lbl_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        lbl_emotion = QLabel("")
        lbl_emotion.setStyleSheet("color: #888; font-size: 10px;")

        header.addWidget(lbl_name)
        header.addStretch()
        header.addWidget(lbl_emotion)
        header.addWidget(lbl_value)
        row_layout.addLayout(header)

        # Barra affinità sottile
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setMaximumHeight(6)
        bar.setStyleSheet(f"""
            QProgressBar {{ background-color: #2a2a2a; border-radius: 3px; }}
            QProgressBar::chunk {{ background-color: {color}; border-radius: 3px; }}
        """)
        row_layout.addWidget(bar)

        return {
            'widget': row,
            'bar': bar,
            'lbl_value': lbl_value,
            'lbl_emotion': lbl_emotion,
            'color': color,
            'name_label': lbl_name,
        }

    def set_companions(self, companions: List[str]) -> None:
        """Initialize widgets for allowed companions only."""
        while self.layout().count():
            item = self.layout().takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.companion_widgets.clear()

        for name in companions:
            if name.lower() not in self._ALLOWED:
                continue
            entry = self._make_row(name)
            self.layout().addWidget(entry['widget'])
            self.companion_widgets[name] = entry

        self.layout().addStretch()

    def add_companion(self, name: str) -> None:
        """Add companion only if in the allowed set."""
        if name in self.companion_widgets or name.lower() not in self._ALLOWED:
            return
        entry = self._make_row(name)
        self.layout().insertWidget(self.layout().count() - 1, entry['widget'])
        self.companion_widgets[name] = entry

    def update_companion(
        self,
        name: str,
        affinity: int,
        emotion: str = "",
        emotion_icon: str = "😐",
    ) -> None:
        """Update companion display. Ignores non-main companions."""
        if name.lower() not in self._ALLOWED:
            return
        if name not in self.companion_widgets:
            self.add_companion(name)
            if name not in self.companion_widgets:
                return

        w = self.companion_widgets[name]
        w['bar'].setValue(affinity)
        w['lbl_value'].setText(str(affinity))

        # Aggiorna colore barra in base al valore
        color = self._affinity_color(name, affinity)
        w['bar'].setStyleSheet(f"""
            QProgressBar {{ background-color: #2a2a2a; border-radius: 3px; }}
            QProgressBar::chunk {{ background-color: {color}; border-radius: 3px; }}
        """)

        if emotion:
            w['lbl_emotion'].setText(f"{emotion_icon} {emotion[:12]}")
        else:
            w['lbl_emotion'].setText("")


class GlobalEventWidget(QGroupBox):
    """Widget for displaying active global event and dynamic event choices."""
    
    # Signals for choice selection
    choice_selected = Signal(int)  # choice index
    event_dismissed = Signal()

    def __init__(self, parent=None) -> None:
        """Initialize event widget."""
        super().__init__("🌍 Event", parent)
        self.setMaximumHeight(200)
        self.setMinimumHeight(60)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self.lbl_event = QLabel("No active events")
        self.lbl_event.setWordWrap(True)
        self.lbl_event.setStyleSheet("color: #888; font-size: 11px; padding: 5px;")
        layout.addWidget(self.lbl_event)
        
        # Container for choice buttons (hidden by default)
        self.choices_container = QWidget()
        choices_layout = QHBoxLayout(self.choices_container)
        choices_layout.setSpacing(4)
        choices_layout.setContentsMargins(0, 0, 0, 0)
        self.choice_buttons: List[QPushButton] = []
        layout.addWidget(self.choices_container)
        self.choices_container.hide()
        
        layout.addStretch()

    def set_event(
        self,
        title: str = "",
        description: str = "",
        icon: str = "🌍",
    ) -> None:
        """Set active event display."""
        if title:
            self.setTitle(f"{icon} {title}")
            self.lbl_event.setText(description)
            self.lbl_event.setStyleSheet(
                "color: #4CAF50; font-size: 11px; padding: 5px; "
                "background-color: #1a3a1a; border-radius: 4px;"
            )
        else:
            self.setTitle("🌍 Event")
            self.lbl_event.setText("No active events")
            self.lbl_event.setStyleSheet(
                "color: #888; font-size: 11px; padding: 5px;"
            )
        # Hide choices when regular event is set
        self._clear_choices()
    
    def show_event_choices(
        self,
        event_title: str,
        description: str,
        choices: List[str],
    ) -> None:
        """Show dynamic event with choice buttons.
        
        Args:
            event_title: Title of the event
            description: Event description
            choices: List of choice texts
        """
        self.setTitle(f"🎲 {event_title}")
        self.lbl_event.setText(description)
        self.lbl_event.setStyleSheet(
            "color: #FFC107; font-size: 11px; padding: 5px; "
            "background-color: #332200; border-radius: 4px;"
        )
        
        # Clear old buttons
        self._clear_choices()
        
        # Create choice buttons
        layout = self.choices_container.layout()
        for i, choice_text in enumerate(choices):
            btn = QPushButton(f"{i+1}. {choice_text}")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #444;
                    color: white;
                    border: 1px solid #666;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 10px;
                }
                QPushButton:hover {
                    background-color: #555;
                    border-color: #888;
                }
                QPushButton:pressed {
                    background-color: #666;
                }
            """)
            btn.clicked.connect(lambda checked, idx=i: self._on_choice_clicked(idx))
            layout.addWidget(btn)
            self.choice_buttons.append(btn)
        
        # Add dismiss button
        btn_dismiss = QPushButton("Ignora")
        btn_dismiss.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 10px;
            }
            QPushButton:hover {
                color: #aaa;
                border-color: #777;
            }
        """)
        btn_dismiss.clicked.connect(self._on_dismiss_clicked)
        layout.addWidget(btn_dismiss)
        self.choice_buttons.append(btn_dismiss)
        
        self.choices_container.show()
    
    def _clear_choices(self) -> None:
        """Clear all choice buttons."""
        for btn in self.choice_buttons:
            btn.deleteLater()
        self.choice_buttons.clear()
        self.choices_container.hide()
    
    def _on_choice_clicked(self, choice_index: int) -> None:
        """Handle choice button click."""
        self.choice_selected.emit(choice_index)
        self._clear_choices()
    
    def _on_dismiss_clicked(self) -> None:
        """Handle dismiss button click."""
        self.event_dismissed.emit()
        self._clear_choices()
        self.set_event()  # Reset to default state


class StoryLogWidget(QGroupBox):
    """Widget for displaying story text with auto-scroll."""

    def __init__(self, parent=None) -> None:
        """Initialize story log."""
        super().__init__("📖 Story", parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Scroll area for story
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border: none; background: transparent;")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.lbl_story = QLabel("Welcome to Luna RPG v4...")
        self.lbl_story.setWordWrap(True)
        self.lbl_story.setTextFormat(Qt.RichText)  # Enable HTML formatting
        self.lbl_story.setStyleSheet("""
            color: #ddd;
            font-size: 15px;
            line-height: 1.5;
            padding: 10px;
        """)
        self.lbl_story.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.lbl_story.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.scroll.setWidget(self.lbl_story)
        layout.addWidget(self.scroll)
        
        # Enable wheel events for scrolling
        self.scroll.setFocusPolicy(Qt.StrongFocus)

    def scroll_to_bottom(self) -> None:
        """Scroll to the bottom of the story."""
        # Use QTimer to ensure layout is updated before scrolling
        from PySide6.QtCore import QTimer
        
        def do_scroll():
            scrollbar = self.scroll.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        
        # Multiple delays to ensure it works
        QTimer.singleShot(10, do_scroll)
        QTimer.singleShot(50, do_scroll)
        QTimer.singleShot(100, do_scroll)

    def append_text(self, text: str) -> None:
        """Append text to story."""
        current = self.lbl_story.text()
        self.lbl_story.setText(f"{current}\n\n{text}")
        self.scroll_to_bottom()

    def append_system_message(self, text: str) -> None:
        """Append system message (time change, etc)."""
        current = self.lbl_story.text()
        formatted = f'<span style="color: #888; font-style: italic;">[{text}]</span>'
        self.lbl_story.setText(f"{current}\n\n{formatted}")
        self.scroll_to_bottom()

    def append_user_message(self, text: str) -> None:
        """Append user message (chat style)."""
        current = self.lbl_story.text()
        formatted = f'<div style="color: #4CAF50; font-weight: bold; margin: 10px 0;">👤 You: <span style="color: #ddd; font-weight: normal;">{text}</span></div>'
        self.lbl_story.setText(f"{current}\n{formatted}")
        self.scroll_to_bottom()

    def append_character_message(self, text: str, character_name: str = "Narrator") -> None:
        """Append character/narrator message (chat style)."""
        current = self.lbl_story.text()
        icon = "🎭" if character_name == "Narrator" else "👤"
        formatted = f'<div style="color: #E91E63; font-weight: bold; margin: 10px 0;">{icon} {character_name}: <span style="color: #fff; font-weight: normal;">{text}</span></div>'
        self.lbl_story.setText(f"{current}\n{formatted}")
        self.scroll_to_bottom()

    def append_npc_message(self, speaker: str, text: str) -> None:
        """Append NPC message during MultiNPC sequence.
        
        Args:
            speaker: Name of the NPC speaking
            text: Message text
        """
        current = self.lbl_story.text()
        formatted = f'<div style="color: #4FC3F7; font-weight: bold; margin: 10px 0;">👤 {speaker}: <span style="color: #fff; font-weight: normal;">{text}</span></div>'
        self.lbl_story.setText(f"{current}\n{formatted}")
        self.scroll_to_bottom()
    
    def _append_formatted(self, text: str, color: str = "#fff") -> None:
        """Append formatted text with custom color (internal use).
        
        Args:
            text: Text to append
            color: HTML color code
        """
        current = self.lbl_story.text()
        formatted = f'<div style="color: {color}; margin: 5px 0;">{text}</div>'
        self.lbl_story.setText(f"{current}\n{formatted}")
        self.scroll_to_bottom()

    def set_text(self, text: str) -> None:
        """Set story text."""
        self.lbl_story.setText(text)
        self.scroll_to_bottom()
    
    def clear(self) -> None:
        """Clear story log."""
        self.lbl_story.setText("")


class ImageDisplayWidget(QGroupBox):
    """Widget for displaying generated images with zoom/pan support."""

    def __init__(self, parent=None) -> None:
        """Initialize image display."""
        super().__init__("🖼️ Scena", parent)
        self.setMinimumWidth(380)
        self.setMaximumWidth(580)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Use interactive ImageViewer instead of static QLabel
        from luna.ui.image_viewer import ImageViewer
        self.image_viewer = ImageViewer()
        
        layout.addWidget(self.image_viewer)

    def set_image(self, image_path: str) -> None:
        """Set displayed image."""
        self.image_viewer.set_image(image_path)

    def clear(self) -> None:
        """Clear image display."""
        self.image_viewer.clear()


class OutfitWidget(QGroupBox):
    """Widget for displaying and managing character outfit."""
    
    # Signals for button clicks
    change_outfit_requested = Signal()  # "Cambia" button clicked
    modify_outfit_requested = Signal()  # "Modifica" button clicked
    
    def __init__(self, parent=None) -> None:
        """Initialize outfit widget."""
        super().__init__("👗 Outfit", parent)
        self.setMaximumHeight(200)
        self.setMinimumHeight(120)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        
        # Current outfit display
        self.lbl_style = QLabel("Style: --")
        self.lbl_style.setStyleSheet("font-weight: bold; color: #4CAF50;")
        layout.addWidget(self.lbl_style)
        
        self.lbl_description = QLabel("No outfit set")
        self.lbl_description.setWordWrap(True)
        self.lbl_description.setStyleSheet("color: #ccc; font-size: 11px;")
        layout.addWidget(self.lbl_description)
        
        # Components display
        self.lbl_components = QLabel("")
        self.lbl_components.setWordWrap(True)
        self.lbl_components.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(self.lbl_components)
        
        # V4.6: Positive Prompt Preview with Scrollbar
        self.lbl_prompt_header = QLabel("📝 SD Prompt:")
        self.lbl_prompt_header.setStyleSheet("font-weight: bold; color: #2196F3; font-size: 10px;")
        self.lbl_prompt_header.setVisible(False)
        layout.addWidget(self.lbl_prompt_header)
        
        # Use QTextEdit with scrollbar instead of QLabel
        from PySide6.QtWidgets import QTextEdit
        self.txt_positive_prompt = QTextEdit()
        self.txt_positive_prompt.setReadOnly(True)
        self.txt_positive_prompt.setMaximumHeight(80)
        self.txt_positive_prompt.setStyleSheet("""
            QTextEdit {
                color: #aaa;
                font-size: 9px;
                background-color: #1a1a1a;
                border: 1px solid #333;
                border-radius: 3px;
                padding: 4px;
            }
            QScrollBar:vertical {
                background: #2a2a2a;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #555;
                border-radius: 5px;
            }
        """)
        self.txt_positive_prompt.setVisible(False)
        layout.addWidget(self.txt_positive_prompt)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_change = QPushButton("🔄 Cambia")
        self.btn_change.setToolTip("Change outfit style (random)")
        self.btn_change.setEnabled(False)
        self.btn_change.clicked.connect(self.change_outfit_requested.emit)
        
        self.btn_modify = QPushButton("✏️ Modifica")
        self.btn_modify.setToolTip("Modify outfit (custom description)")
        self.btn_modify.setEnabled(False)
        self.btn_modify.clicked.connect(self.modify_outfit_requested.emit)
        
        btn_layout.addWidget(self.btn_change)
        btn_layout.addWidget(self.btn_modify)
        layout.addLayout(btn_layout)
        
        layout.addStretch()
        
        # Style list (hidden by default, shown on change)
        self.style_list: Optional[QListWidget] = None
        
    def set_outfit(self, style: str, description: str, components: Optional[Dict[str, str]] = None,
                   positive_prompt: Optional[str] = None) -> None:
        """Update outfit display.
        
        Args:
            style: Outfit style name
            description: Outfit description
            components: Optional component dict
            positive_prompt: Optional SD positive prompt (visual + tags + LoRA)
        """
        # V4.6: If positive_prompt provided, show ONLY that (hide text descriptions)
        if positive_prompt:
            # Hide text description elements
            self.lbl_style.setVisible(False)
            self.lbl_description.setVisible(False)
            self.lbl_components.setVisible(False)
            self.btn_change.setVisible(False)
            self.btn_modify.setVisible(False)
            
            # Show only positive prompt with scrollbar
            self.lbl_prompt_header.setVisible(True)
            self.txt_positive_prompt.setPlainText(positive_prompt)
            self.txt_positive_prompt.setVisible(True)
        else:
            # Show text description elements
            self.lbl_style.setVisible(True)
            self.lbl_description.setVisible(True)
            self.lbl_components.setVisible(True)
            self.btn_change.setVisible(True)
            self.btn_modify.setVisible(True)
            
            self.lbl_style.setText(f"Style: {style}")
            self.lbl_description.setText(description or "No description")
            
            if components:
                comp_text = " | ".join([f"{k}: {v}" for k, v in components.items()])
                self.lbl_components.setText(comp_text)
            else:
                self.lbl_components.setText("")
            
            # Hide positive prompt
            self.lbl_prompt_header.setVisible(False)
            self.txt_positive_prompt.setVisible(False)
            
    def set_available_styles(self, styles: List[str]) -> None:
        """Set available wardrobe styles.
        
        Args:
            styles: List of available style names
        """
        self._available_styles = styles
        self.btn_change.setEnabled(len(styles) > 0)
        self.btn_modify.setEnabled(True)
        
    def clear(self) -> None:
        """Clear outfit display."""
        # Reset visibility to default (show text, hide prompt)
        self.lbl_style.setVisible(True)
        self.lbl_description.setVisible(True)
        self.lbl_components.setVisible(True)
        self.lbl_prompt_header.setVisible(False)
        self.lbl_positive_prompt.setVisible(False)
        
        self.lbl_style.setText("Style: --")
        self.lbl_description.setText("No outfit set")
        self.lbl_components.setText("")
        self.btn_change.setEnabled(False)
        self.btn_modify.setEnabled(False)


class LocationWidget(QGroupBox):
    """Widget for displaying current location and characters present."""
    
    def __init__(self, parent=None) -> None:
        """Initialize location widget."""
        super().__init__("📍 Location", parent)
        self.setMaximumHeight(200)
        self.setMinimumHeight(160)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        
        # Current location
        self.lbl_location = QLabel("Unknown")
        self.lbl_location.setStyleSheet("font-weight: bold; color: #E91E63; font-size: 14px;")
        layout.addWidget(self.lbl_location)
        
        # Description
        self.lbl_description = QLabel("No location data")
        self.lbl_description.setWordWrap(True)
        self.lbl_description.setStyleSheet("color: #ccc; font-size: 11px;")
        layout.addWidget(self.lbl_description)
        
        # State indicator
        self.lbl_state = QLabel("")
        self.lbl_state.setStyleSheet("color: #FFC107; font-size: 10px;")
        layout.addWidget(self.lbl_state)
        
        # V4: Characters present (instead of exits)
        layout.addWidget(QLabel("<b>👥 Personaggi presenti:</b>"))
        self.list_characters = QListWidget()
        self.list_characters.setMaximumHeight(100)
        self.list_characters.setStyleSheet("""
            QListWidget {
                background-color: #2d2d2d;
                border: 1px solid #444;
                border-radius: 4px;
                color: #4CAF50;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 4px;
            }
        """)
        layout.addWidget(self.list_characters)
        
        layout.addStretch()
    
    def set_location(
        self,
        name: str,
        description: str,
        state: str = "",
        characters: Optional[List[str]] = None,
    ) -> None:
        """Update location display.
        
        Args:
            name: Location name
            description: Location description
            state: Optional state text
            characters: List of character names present (V4: replaces exits)
        """
        self.lbl_location.setText(name)
        self.lbl_description.setText(description)
        
        if state and state != "normal":
            self.lbl_state.setText(f"State: {state}")
        else:
            self.lbl_state.setText("")
        
        self.list_characters.clear()
        if characters:
            for char_name in characters:
                self.list_characters.addItem(f"👤 {char_name}")
        else:
            self.list_characters.addItem("(nessuno presente)")
    
    def clear(self) -> None:
        """Clear location display."""
        self.lbl_location.setText("Unknown")
        self.lbl_description.setText("No location data")
        self.lbl_state.setText("")
        self.list_characters.clear()


class PersonalityArchetypeWidget(QGroupBox):
    """Widget for displaying player personality archetype and impression stats."""
    
    def __init__(self, parent=None) -> None:
        """Initialize personality widget."""
        super().__init__("🎭 Personality Profile", parent)
        self.setMaximumHeight(200)
        self.setMinimumHeight(160)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        
        # Archetype display
        self.lbl_archetype = QLabel("Profile in Analysis...")
        self.lbl_archetype.setStyleSheet("""
            font-weight: bold; 
            color: #FFD700; 
            font-size: 13px;
            padding: 4px;
            background-color: #333;
            border-radius: 4px;
        """)
        self.lbl_archetype.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_archetype)
        
        # Impression stats (5 dimensions)
        self.stats_layout = QVBoxLayout()
        self.stats_layout.setSpacing(4)
        
        self.stat_bars: Dict[str, QProgressBar] = {}
        stat_configs = [
            ("trust", "Trust", "#4CAF50"),
            ("attraction", "Attraction", "#E91E63"),
            ("fear", "Fear", "#9C27B0"),
            ("curiosity", "Curiosity", "#2196F3"),
            ("power", "Power Balance", "#FF9800"),
        ]
        
        for key, label, color in stat_configs:
            row = QHBoxLayout()
            lbl = QLabel(f"{label}:")
            lbl.setStyleSheet("color: #ccc; font-size: 10px; min-width: 70px;")
            lbl.setAlignment(Qt.AlignRight)
            row.addWidget(lbl)
            
            bar = QProgressBar()
            bar.setRange(-100, 100)
            bar.setValue(0)
            bar.setFormat("%v")  # Mostra valore reale (-100 a 100), non percentuale
            bar.setTextVisible(True)
            bar.setMaximumHeight(16)
            bar.setStyleSheet(f"""
                QProgressBar {{
                    background-color: #2d2d2d;
                    border: 1px solid #444;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 9px;
                    color: white;
                }}
                QProgressBar::chunk {{
                    background-color: {color};
                }}
            """)
            self.stat_bars[key] = bar
            row.addWidget(bar, stretch=1)
            self.stats_layout.addLayout(row)
        
        layout.addLayout(self.stats_layout)
        
        # Behavior hints
        self.lbl_behaviors = QLabel("No behaviors detected yet")
        self.lbl_behaviors.setStyleSheet("color: #888; font-size: 10px; font-style: italic;")
        self.lbl_behaviors.setWordWrap(True)
        layout.addWidget(self.lbl_behaviors)
        
        layout.addStretch()
    
    def set_archetype(self, archetype: Optional[str]) -> None:
        """Update displayed archetype.
        
        Args:
            archetype: Player archetype name or None
        """
        if archetype:
            self.lbl_archetype.setText(f"🎭 {archetype}")
        else:
            self.lbl_archetype.setText("Profile in Analysis...")
    
    def set_impressions(
        self,
        trust: int = 0,
        attraction: int = 0,
        fear: int = 0,
        curiosity: int = 0,
        dominance_balance: int = 0,
    ) -> None:
        """Update impression bars.
        
        Args:
            trust: Trust score (-100 to 100)
            attraction: Attraction score (-100 to 100)
            fear: Fear score (-100 to 100)
            curiosity: Curiosity score (-100 to 100)
            dominance_balance: Power balance (-100 = player dominant, +100 = NPC dominant)
        """
        self.stat_bars["trust"].setValue(trust)
        self.stat_bars["attraction"].setValue(attraction)
        self.stat_bars["fear"].setValue(fear)
        self.stat_bars["curiosity"].setValue(curiosity)
        self.stat_bars["power"].setValue(dominance_balance)
        
        # Update power balance label
        if dominance_balance < -20:
            self.stat_bars["power"].setFormat("You Dominant (%v)")
        elif dominance_balance > 20:
            self.stat_bars["power"].setFormat("NPC Dominant (%v)")
        else:
            self.stat_bars["power"].setFormat("Equal (%v)")
    
    def set_behaviors(self, behaviors: List[str]) -> None:
        """Update detected behaviors display.
        
        Args:
            behaviors: List of detected behavior names
        """
        if behaviors:
            self.lbl_behaviors.setText(f"Detected: {', '.join(behaviors)}")
        else:
            self.lbl_behaviors.setText("No behaviors detected yet")
    
    def clear(self) -> None:
        """Reset widget."""
        self.lbl_archetype.setText("Profile in Analysis...")
        for bar in self.stat_bars.values():
            bar.setValue(0)
        self.lbl_behaviors.setText("No behaviors detected yet")
