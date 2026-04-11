"""Luna RPG - Layout Manager.

Builds and manages all UI widgets and layout for the main window.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLineEdit, QPushButton, QStatusBar,
    QLabel, QToolBar,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction

from luna.core.config import get_settings
from luna.ui.widgets import (
    CompanionStatusWidget,
    GlobalEventWidget,
    StoryLogWidget,
    OutfitWidget,
    LocationWidget,
    PersonalityArchetypeWidget,
)
from luna.ui.quest_journal_widget import QuestJournalWidget
from luna.ui.narrative_compass_widget import NarrativeCompassWidget
from luna.ui.action_bar import QuickActionBar
from luna.ui.npc_actions_widget import NpcActionsWidget
from luna.ui.feedback_visualizer import FeedbackVisualizer
from luna.ui.quest_choice_widget import QuestChoiceWidget, PendingChoiceManager
from luna.media.lora_mapping import LoraMapping

if TYPE_CHECKING:
    from .main_window import MainWindow


class LayoutManager:
    """Builds and manages all UI widgets and layout."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window

        # Widget references (set during setup_all)
        self.personality_widget: Optional[PersonalityArchetypeWidget] = None
        self.event_widget: Optional[GlobalEventWidget] = None
        self.location_widget: Optional[LocationWidget] = None
        self.outfit_widget: Optional[OutfitWidget] = None
        self.compass_widget: Optional[NarrativeCompassWidget] = None
        self.image_display = None
        self.quest_journal: Optional[QuestJournalWidget] = None
        self.companion_status: Optional[CompanionStatusWidget] = None
        self.quick_actions: Optional[QuickActionBar] = None
        self.choice_widget: Optional[QuestChoiceWidget] = None
        self.story_log: Optional[StoryLogWidget] = None
        self.txt_input: Optional[QLineEdit] = None
        self.btn_send: Optional[QPushButton] = None
        self.btn_interrupt: Optional[QPushButton] = None
        self.lbl_companion: Optional[QLabel] = None
        self.lbl_archetype: Optional[QLabel] = None
        self.lbl_status: Optional[QLabel] = None
        self.lbl_turn: Optional[QLabel] = None
        self.lbl_location: Optional[QLabel] = None
        self.lbl_time: Optional[QLabel] = None
        self.btn_advance_phase: Optional[QPushButton] = None  # v8: pulsante avanzamento fase manuale
        self.statusbar: Optional[QStatusBar] = None
        self.act_audio: Optional[QAction] = None
        self.act_video: Optional[QAction] = None
        self._lora_toggle_action: Optional[QAction] = None
        self.feedback: Optional[FeedbackVisualizer] = None
        self.choice_manager: Optional[PendingChoiceManager] = None
        self.lora_mapping: Optional[LoraMapping] = None
        self.npc_actions_widget: Optional[NpcActionsWidget] = None

    def setup_all(self) -> None:
        """Build complete UI — widgets, toolbar, statusbar."""
        w = self.window

        # Non-widget objects
        self.feedback = FeedbackVisualizer(w)
        self.choice_manager = PendingChoiceManager()
        self.lora_mapping = LoraMapping()
        self.lora_mapping.set_enabled(False)  # default OFF

        self._setup_ui()
        self._setup_toolbar()
        self._setup_statusbar()

        # Timer for async updates
        w.update_timer = QTimer()
        w.update_timer.timeout.connect(w._on_update)
        w.update_timer.start(100)

    def _setup_ui(self) -> None:
        """Setup main UI layout."""
        w = self.window
        central = QWidget()
        w.setCentralWidget(central)

        main_splitter = QSplitter(Qt.Horizontal)

        # === LEFT PANEL ===
        left_panel = QWidget()
        left_panel.setMinimumWidth(200)
        left_panel.setMaximumWidth(280)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(6)
        left_layout.setContentsMargins(6, 6, 6, 6)

        self.personality_widget = PersonalityArchetypeWidget()
        left_layout.addWidget(self.personality_widget, stretch=1)

        self.event_widget = GlobalEventWidget()
        self.event_widget.setMinimumHeight(100)
        self.event_widget.setMaximumHeight(180)
        self.event_widget.choice_selected.connect(w.event_handler._on_event_choice_selected)
        self.event_widget.event_dismissed.connect(w.event_handler._on_event_dismissed)
        left_layout.addWidget(self.event_widget)

        self.location_widget = LocationWidget()
        self.location_widget.setMaximumHeight(160)
        left_layout.addWidget(self.location_widget)

        self.outfit_widget = OutfitWidget()
        self.outfit_widget.setMinimumHeight(130)
        self.outfit_widget.setMaximumHeight(180)
        self.outfit_widget.change_outfit_requested.connect(w.event_handler._on_change_outfit)
        self.outfit_widget.modify_outfit_requested.connect(w.event_handler._on_modify_outfit)
        left_layout.addWidget(self.outfit_widget)

        self.compass_widget = NarrativeCompassWidget()
        left_layout.addWidget(self.compass_widget)

        main_splitter.addWidget(left_panel)

        # === CENTER PANEL (Image) ===
        center_panel = QWidget()
        center_panel.setMinimumWidth(450)
        center_panel.setMaximumWidth(650)
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(8, 8, 8, 8)

        from luna.ui.image_navigator import ImageNavigator
        self.image_display = ImageNavigator()
        center_layout.addWidget(self.image_display)

        main_splitter.addWidget(center_panel)

        # === RIGHT PANEL ===
        right_panel = QWidget()
        right_panel.setMinimumWidth(500)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(8)
        right_layout.setContentsMargins(8, 8, 8, 8)

        self.quest_journal = QuestJournalWidget()
        self.quest_journal.setMaximumHeight(120)
        right_layout.addWidget(self.quest_journal)

        # v8: NPC Actions Widget — wide horizontal layout
        self.npc_actions_widget = NpcActionsWidget()
        self.npc_actions_widget.setMaximumHeight(160)
        right_layout.addWidget(self.npc_actions_widget)

        self.companion_status = CompanionStatusWidget()
        self.companion_status.setMaximumHeight(140)
        right_layout.addWidget(self.companion_status)

        self.quick_actions = QuickActionBar()
        self.quick_actions.action_triggered.connect(w.event_handler._on_action_triggered)
        self.quick_actions.hide()  # rimosso su richiesta — usare input testuale

        self.choice_widget = QuestChoiceWidget()
        self.choice_widget.choice_made.connect(w.event_handler._on_choice_made)
        self.choice_widget.cancelled.connect(w.event_handler._on_choice_cancelled)
        right_layout.addWidget(self.choice_widget)

        # Story + input container
        story_container = QWidget()
        story_layout = QVBoxLayout(story_container)
        story_layout.setSpacing(6)
        story_layout.setContentsMargins(0, 0, 0, 0)

        self.story_log = StoryLogWidget()
        story_layout.addWidget(self.story_log, stretch=1)

        input_group = QWidget()
        input_layout = QHBoxLayout(input_group)
        input_layout.setSpacing(8)
        input_layout.setContentsMargins(0, 0, 0, 0)

        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("Scrivi qui il tuo messaggio...")
        self.txt_input.returnPressed.connect(w.game_controller._on_send)
        self.txt_input.setMinimumHeight(42)
        self.txt_input.setStyleSheet("""
            QLineEdit {
                padding: 10px 15px;
                font-size: 14px;
                border: 2px solid #555;
                border-radius: 6px;
                background-color: #2d2d2d;
                color: #fff;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
                background-color: #333;
            }
        """)

        self.btn_send = QPushButton("▶ Invia", input_group)
        self.btn_send.clicked.connect(w.game_controller._on_send)
        self.btn_send.setMinimumHeight(42)
        self.btn_send.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 6px;
                padding: 0 20px;
                min-width: 90px;
            }
            QPushButton:hover { background-color: #43A047; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)

        self.btn_interrupt = QPushButton("⏹ Interrompi", input_group)
        self.btn_interrupt.clicked.connect(w.event_handler._on_interrupt_multi_npc)
        self.btn_interrupt.hide()

        input_layout.addWidget(self.txt_input, stretch=1)
        input_layout.addWidget(self.btn_send)

        story_layout.addWidget(input_group)
        right_layout.addWidget(story_container, stretch=1)

        main_splitter.addWidget(right_panel)

        main_splitter.setSizes([220, 550, 630])
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 0)
        main_splitter.setStretchFactor(2, 1)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(main_splitter)

    def _setup_toolbar(self) -> None:
        """Setup main toolbar."""
        w = self.window
        toolbar = QToolBar()
        w.addToolBar(toolbar)

        self.act_audio = QAction("🔊 Audio", w)
        self.act_audio.setCheckable(True)
        self.act_audio.setChecked(True)
        self.act_audio.triggered.connect(w.event_handler._on_toggle_audio)
        toolbar.addAction(self.act_audio)

        self.lbl_companion = QLabel("👤 Companion")
        self.lbl_companion.setStyleSheet("color: #fff; padding: 0 10px;")
        toolbar.addWidget(self.lbl_companion)

        self.lbl_archetype = QLabel("🎭 Analyzing...")
        self.lbl_archetype.setStyleSheet(
            "color: #FFD700; padding: 0 10px; font-weight: bold;"
        )
        self.lbl_archetype.setToolTip(
            "Your personality profile is being analyzed based on your actions"
        )
        toolbar.addWidget(self.lbl_archetype)

        self.act_video = QAction("🎬 Video", w)
        self.act_video.triggered.connect(w.event_handler._on_toggle_video)
        toolbar.addAction(self.act_video)

        toolbar.addSeparator()

        act_new = QAction("🎮 New Game", w)
        act_new.triggered.connect(w.event_handler._on_new_game)
        toolbar.addAction(act_new)

        act_save = QAction("💾 Save", w)
        act_save.triggered.connect(w.media_manager._on_save)
        toolbar.addAction(act_save)

        act_load = QAction("📂 Load", w)
        act_load.triggered.connect(w.media_manager._on_load)
        toolbar.addAction(act_load)

        toolbar.addSeparator()

        act_settings = QAction("⚙️ Settings", w)
        act_settings.triggered.connect(w.event_handler._on_settings)
        toolbar.addAction(act_settings)

        toolbar.addSeparator()

        act_debug = QAction("🔧 Debug", w)
        act_debug.triggered.connect(w.event_handler._on_open_debug)
        toolbar.addAction(act_debug)

        self._lora_toggle_action = QAction("🎭 LoRA OFF", w)
        self._lora_toggle_action.setCheckable(True)
        self._lora_toggle_action.setChecked(False)
        self._lora_toggle_action.triggered.connect(w.event_handler._on_toggle_lora)
        toolbar.addAction(self._lora_toggle_action)

    def _setup_statusbar(self) -> None:
        """Setup status bar."""
        w = self.window
        self.statusbar = QStatusBar()
        self.statusbar.setStyleSheet("""
            QStatusBar {
                background-color: #2d2d2d;
                border-top: 2px solid #4CAF50;
                min-height: 30px;
            }
        """)
        w.setStatusBar(self.statusbar)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setStyleSheet("color: #ccc; padding: 0 10px;")

        self.lbl_turn = QLabel("🎲 TURN: 0")
        self.lbl_turn.setStyleSheet("""
            color: #4CAF50;
            padding: 0 15px;
            font-weight: bold;
            font-size: 14px;
            background-color: #1a1a1a;
            border-radius: 4px;
            border: 1px solid #4CAF50;
        """)

        self.lbl_location = QLabel("📍 Unknown")
        self.lbl_location.setStyleSheet("color: #4CAF50; padding: 0 10px;")

        self.lbl_time = QLabel("☀️ MORNING")
        self.lbl_time.setStyleSheet("""
            color: #FFD700;
            padding: 0 15px;
            font-size: 13px;
            font-weight: bold;
            min-width: 120px;
        """)
        self.lbl_time.setToolTip("8 turni per fase.")

        # v8: Pulsante "Avanza Fase" al posto degli indicatori di turno
        self.btn_advance_phase = QPushButton("🌅 Avanza Fase")
        self.btn_advance_phase.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #F57C00;
                border-radius: 6px;
                padding: 6px 16px;
                min-width: 140px;
            }
            QPushButton:hover { background-color: #F57C00; }
            QPushButton:disabled { 
                background-color: #555; 
                color: #888; 
                border-color: #444;
            }
        """)
        self.btn_advance_phase.setToolTip("Passa alla fase successiva (Mattina→Pomeriggio→Sera→Notte)")
        self.btn_advance_phase.clicked.connect(w.event_handler._on_advance_phase)

        self.statusbar.addWidget(self.lbl_status, stretch=1)
        self.statusbar.addWidget(self.lbl_turn)
        self.statusbar.addWidget(self.lbl_location)
        self.statusbar.addWidget(self.lbl_time)
        self.statusbar.addWidget(self.btn_advance_phase)

        self.lbl_turn.setMinimumWidth(100)
        self.lbl_turn.setAlignment(Qt.AlignCenter)
