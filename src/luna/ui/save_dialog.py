"""Save dialog with custom name input."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QDialogButtonBox,
)
from PySide6.QtCore import Qt


class SaveDialog(QDialog):
    """Dialog for saving game with custom name."""
    
    def __init__(self, default_name: str = "", parent=None) -> None:
        """Initialize save dialog.
        
        Args:
            default_name: Default save name suggestion
            parent: Parent widget
        """
        super().__init__(parent)
        self.setWindowTitle("💾 Salva Partita")
        self.setMinimumWidth(400)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("Salva la partita")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #E91E63;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Description
        desc = QLabel("Inserisci un nome per questo salvataggio:")
        desc.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(desc)
        
        # Name input
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Es: Prima dell'esame, Capitolo 1...")
        self.txt_name.setText(default_name)
        self.txt_name.setStyleSheet("""
            QLineEdit {
                background-color: #2d2d2d;
                border: 2px solid #444;
                border-radius: 8px;
                padding: 10px;
                color: #fff;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #E91E63;
            }
        """)
        self.txt_name.selectAll()
        layout.addWidget(self.txt_name)
        
        # Info label
        info = QLabel("💡 Se lasci vuoto, verrà usato il nome predefinito")
        info.setStyleSheet("color: #666; font-size: 11px; font-style: italic;")
        layout.addWidget(info)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_cancel = QPushButton("Annulla")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: #fff;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_save = QPushButton("💾 Salva")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #E91E63;
                color: #fff;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D81B60;
            }
        """)
        self.btn_save.clicked.connect(self.accept)
        self.btn_save.setDefault(True)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        
        layout.addLayout(btn_layout)
    
    def get_save_name(self) -> str:
        """Get the entered save name.
        
        Returns:
            Save name entered by user
        """
        return self.txt_name.text().strip()
    
    @staticmethod
    def get_save_name_dialog(default_name: str = "", parent=None) -> tuple[str, bool]:
        """Static method to show dialog and get result.
        
        Args:
            default_name: Default name suggestion
            parent: Parent widget
            
        Returns:
            Tuple of (save_name, accepted)
        """
        dialog = SaveDialog(default_name, parent)
        result = dialog.exec()
        
        if result == QDialog.DialogCode.Accepted:
            return dialog.get_save_name(), True
        return "", False
