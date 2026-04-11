"""Video generation dialog for Luna RPG v4.

Allows user to describe motion for Wan2.1 I2V video generation.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit, QMessageBox,
    QProgressBar, QApplication,
)
from PySide6.QtCore import Qt, QTimer
from pathlib import Path
from typing import Optional


class VideoGenerationDialog(QDialog):
    """Dialog for video generation with motion description."""
    
    def __init__(
        self,
        image_path: str,
        character_name: str = "",
        parent=None,
    ) -> None:
        """Initialize video dialog.
        
        Args:
            image_path: Current image to animate
            character_name: Character name for context
            parent: Parent widget
        """
        super().__init__(parent)
        self.setWindowTitle("🎬 Genera Video - Wan2.1 I2V")
        self.setMinimumSize(500, 400)
        
        self.image_path = image_path
        self.character_name = character_name
        self.user_action: str = ""
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Info label
        info = QLabel(
            f"<b>Genera video da immagine corrente</b><br>"
            f"Personaggio: <b>{self.character_name}</b><br>"
            f"Descrivi il movimento che vuoi vedere..."
        )
        info.setWordWrap(True)
        info.setStyleSheet("font-size: 13px; padding: 10px; background: #2d2d2d; border-radius: 4px;")
        layout.addWidget(info)
        
        # Examples
        examples = QLabel(
            "<b>Esempi:</b><br>"
            "• \"Elena sventola la mano sorridendo\"<br>"
            "• \"Si gira lentamente verso la finestra\"<br>"
            "• \"Sorride e fa un passo avanti\"<br>"
            "• \"Gioca nervosamente con i capelli\""
        )
        examples.setWordWrap(True)
        examples.setStyleSheet("color: #888; font-size: 11px; padding: 10px;")
        layout.addWidget(examples)
        
        # Input label
        layout.addWidget(QLabel("<b>Descrivi il movimento:</b>"))
        
        # Action input
        self.txt_action = QTextEdit()
        self.txt_action.setPlaceholderText("Scrivi qui l'azione da animare...")
        self.txt_action.setMaximumHeight(80)
        self.txt_action.setStyleSheet("""
            QTextEdit {
                background-color: #2d2d2d;
                color: #fff;
                border: 2px solid #444;
                border-radius: 4px;
                padding: 10px;
                font-size: 13px;
            }
            QTextEdit:focus {
                border-color: #4CAF50;
            }
        """)
        layout.addWidget(self.txt_action)
        
        # Progress (hidden initially)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate
        self.progress.setTextVisible(True)
        self.progress.setFormat("Generazione in corso... (~5-7 minuti)")
        self.progress.hide()
        layout.addWidget(self.progress)
        
        # Status label
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #4CAF50; font-weight: bold;")
        layout.addWidget(self.lbl_status)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_cancel = QPushButton("❌ Annulla")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #444;
                padding: 10px 20px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        
        self.btn_generate = QPushButton("🎬 Genera Video")
        self.btn_generate.clicked.connect(self._on_generate)
        self.btn_generate.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #333;
                color: #666;
            }
        """)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_generate)
        
        layout.addLayout(btn_layout)
    
    def _on_generate(self) -> None:
        """Handle generate button."""
        action = self.txt_action.toPlainText().strip()
        
        if not action:
            QMessageBox.warning(
                self,
                "Input Richiesto",
                "Per favore descrivi il movimento da animare."
            )
            return
        
        self.user_action = action
        self.accept()
    
    def get_action(self) -> str:
        """Get user action description.
        
        Returns:
            User's motion description
        """
        return self.user_action
    
    def show_generating_state(self) -> None:
        """Show generating state (disable inputs, show progress)."""
        self.txt_action.setEnabled(False)
        self.btn_generate.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.progress.show()
        self.lbl_status.setText("🎬 Generazione video in corso...\nNon chiudere questa finestra (~5-7 minuti)")
        
        # Force UI update
        QApplication.processEvents()
