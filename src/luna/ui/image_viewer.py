"""Interactive image viewer with zoom and pan.

Based on v3 implementation - supports mouse wheel zoom and click-drag pan.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QPoint, QRectF
from PySide6.QtGui import QPixmap, QPainter, QWheelEvent, QMouseEvent, QKeyEvent


class ImageViewer(QWidget):
    """Interactive image viewer with zoom and pan support.
    
    Features:
    - Mouse wheel: zoom in/out
    - Click + drag: pan image
    - Double click: reset view
    - Buttons: zoom in/out, fit to window, original size
    """
    
    def __init__(self, parent=None) -> None:
        """Initialize image viewer."""
        super().__init__(parent)
        
        self._pixmap: Optional[QPixmap] = None
        self._scale: float = 1.0
        self._offset: QPoint = QPoint(0, 0)
        self._dragging: bool = False
        self._last_mouse_pos: QPoint = QPoint(0, 0)
        self._min_scale: float = 0.1
        self._max_scale: float = 10.0
        
        self._setup_ui()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
    
    def _setup_ui(self) -> None:
        """Setup UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Image display area
        self.lbl_display = QLabel()
        self.lbl_display.setAlignment(Qt.AlignCenter)
        self.lbl_display.setStyleSheet("""
            QLabel {
                background-color: #1a1a1a;
                border: 2px solid #444;
            }
        """)
        layout.addWidget(self.lbl_display, stretch=1)
        
        # Controls toolbar
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(5, 5, 5, 5)
        
        # Zoom out button
        btn_zoom_out = QPushButton("🔍-")
        btn_zoom_out.setToolTip("Zoom Out (-)")
        btn_zoom_out.clicked.connect(self.zoom_out)
        controls_layout.addWidget(btn_zoom_out)
        
        # Zoom label
        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setStyleSheet("color: #fff; min-width: 50px;")
        self.lbl_zoom.setAlignment(Qt.AlignCenter)
        controls_layout.addWidget(self.lbl_zoom)
        
        # Zoom in button
        btn_zoom_in = QPushButton("🔍+")
        btn_zoom_in.setToolTip("Zoom In (+)")
        btn_zoom_in.clicked.connect(self.zoom_in)
        controls_layout.addWidget(btn_zoom_in)
        
        controls_layout.addSpacing(20)
        
        # Fit to window button
        btn_fit = QPushButton("⬜ Fit")
        btn_fit.setToolTip("Fit to Window (F)")
        btn_fit.clicked.connect(self.fit_to_window)
        controls_layout.addWidget(btn_fit)
        
        # Original size button
        btn_original = QPushButton("1:1")
        btn_original.setToolTip("Original Size (O)")
        btn_original.clicked.connect(self.reset_zoom)
        controls_layout.addWidget(btn_original)
        
        controls_layout.addStretch()
        
        # Info label
        self.lbl_info = QLabel("No image loaded")
        self.lbl_info.setStyleSheet("color: #888; font-size: 11px;")
        controls_layout.addWidget(self.lbl_info)
        
        layout.addWidget(controls)
    
    def set_image(self, image_path: str) -> None:
        """Load and display image.
        
        Args:
            image_path: Path to image file
        """
        self._pixmap = QPixmap(image_path)
        if self._pixmap.isNull():
            self.lbl_info.setText("Failed to load image")
            return
        
        self.lbl_info.setText(
            f"{self._pixmap.width()}x{self._pixmap.height()}"
        )
        
        # Initial fit to window
        self.fit_to_window()
    
    def clear(self) -> None:
        """Clear displayed image."""
        self._pixmap = None
        self._scale = 1.0
        self._offset = QPoint(0, 0)
        self.lbl_display.clear()
        self.lbl_display.setText("No image")
        self.lbl_info.setText("No image loaded")
        self.lbl_zoom.setText("100%")
    
    def zoom_in(self) -> None:
        """Zoom in by 20%."""
        self._set_zoom(self._scale * 1.2)
    
    def zoom_out(self) -> None:
        """Zoom out by 20%."""
        self._set_zoom(self._scale / 1.2)
    
    def reset_zoom(self) -> None:
        """Reset to original size."""
        self._set_zoom(1.0)
        self._offset = QPoint(0, 0)
    
    def fit_to_window(self) -> None:
        """Fit image to window size."""
        if not self._pixmap or self._pixmap.isNull():
            return
        
        # Calculate scale to fit
        widget_rect = self.lbl_display.rect()
        img_width = self._pixmap.width()
        img_height = self._pixmap.height()
        
        scale_x = widget_rect.width() / img_width
        scale_y = widget_rect.height() / img_height
        
        # Use smaller scale to fit entirely
        self._scale = min(scale_x, scale_y) * 0.95  # 95% for margin
        self._offset = QPoint(0, 0)
        self._update_display()
    
    def _set_zoom(self, scale: float) -> None:
        """Set zoom level with clamping.
        
        Args:
            scale: New scale factor
        """
        old_scale = self._scale
        self._scale = max(self._min_scale, min(self._max_scale, scale))
        
        # Adjust offset to zoom toward center
        if self._pixmap:
            center_x = self.lbl_display.width() / 2
            center_y = self.lbl_display.height() / 2
            
            # Calculate offset adjustment
            factor = self._scale / old_scale
            self._offset = QPoint(
                int(center_x - (center_x - self._offset.x()) * factor),
                int(center_y - (center_y - self._offset.y()) * factor)
            )
        
        self._update_display()
    
    def _update_display(self) -> None:
        """Update the displayed image with current transform."""
        if not self._pixmap or self._pixmap.isNull():
            return
        
        # Create transformed pixmap
        scaled_width = int(self._pixmap.width() * self._scale)
        scaled_height = int(self._pixmap.height() * self._scale)
        
        if scaled_width <= 0 or scaled_height <= 0:
            return
        
        # Scale pixmap
        scaled = self._pixmap.scaled(
            scaled_width,
            scaled_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        
        # Create display pixmap with widget size
        display_pixmap = QPixmap(self.lbl_display.size())
        display_pixmap.fill(Qt.transparent)
        
        # Paint scaled image at offset
        painter = QPainter(display_pixmap)
        painter.drawPixmap(self._offset, scaled)
        painter.end()
        
        self.lbl_display.setPixmap(display_pixmap)
        
        # Update zoom label
        self.lbl_zoom.setText(f"{int(self._scale * 100)}%")
    
    # ====================================================================
    # Event handlers
    # ====================================================================
    
    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle mouse wheel for zoom."""
        if not self._pixmap:
            return
        
        # Zoom factor
        delta = event.angleDelta().y()
        if delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        
        event.accept()
    
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse press for pan start."""
        if event.button() == Qt.LeftButton and self._pixmap:
            self._dragging = True
            self._last_mouse_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
        
        event.accept()
    
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handle mouse move for panning."""
        if self._dragging and self._pixmap:
            delta = event.pos() - self._last_mouse_pos
            self._last_mouse_pos = event.pos()
            
            # Update offset
            self._offset += delta
            self._update_display()
        
        event.accept()
    
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Handle mouse release for pan end."""
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)
        
        event.accept()
    
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Handle double click to reset view."""
        if event.button() == Qt.LeftButton:
            self.fit_to_window()
        
        event.accept()
    
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard shortcuts."""
        key = event.key()
        
        if key == Qt.Key_Plus or key == Qt.Key_Equal:
            self.zoom_in()
        elif key == Qt.Key_Minus:
            self.zoom_out()
        elif key == Qt.Key_0:
            self.reset_zoom()
        elif key == Qt.Key_F:
            self.fit_to_window()
        else:
            super().keyPressEvent(event)
    
    def resizeEvent(self, event) -> None:
        """Handle resize to update display."""
        super().resizeEvent(event)
        if self._pixmap:
            self._update_display()
