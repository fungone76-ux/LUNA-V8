"""Main application class for Luna RPG v4.

Integrates startup dialog and main window.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from qasync import QEventLoop

from luna.ui.startup_dialog import StartupDialog
from luna.ui.main_window import MainWindow


def main(debug: bool = False, no_media: bool = False) -> int:
    """Entry point.
    
    Args:
        debug: Enable debug tracing
        no_media: Disable image/video generation
    """
    import os
    
    # Set environment variables based on arguments
    if no_media:
        os.environ["LUNA_DEBUG_NO_MEDIA"] = "1"
        logger.debug("[App] Media generation disabled (--no-media)")
    
    if debug:
        os.environ["LUNA_DEBUG_MODE"] = "1"
    
    # Create QApplication first
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Luna RPG v4")
    qt_app.setApplicationVersion("4.0.0")
    qt_app.setOrganizationName("LunaRPG")
    
    # Don't quit when last window is closed (we manage lifecycle manually)
    qt_app.setQuitOnLastWindowClosed(False)
    
    # Setup dark theme
    qt_app.setStyleSheet("""
        QMainWindow {
            background-color: #1a1a1a;
        }
        QWidget {
            background-color: #1a1a1a;
            color: #e0e0e0;
        }
        QGroupBox {
            border: 1px solid #444;
            border-radius: 4px;
            margin-top: 10px;
            padding-top: 10px;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }
        QPushButton {
            background-color: #333;
            border: 1px solid #555;
            border-radius: 4px;
            padding: 8px 16px;
        }
        QPushButton:hover {
            background-color: #444;
        }
        QLineEdit, QTextEdit, QComboBox {
            background-color: #2d2d2d;
            border: 1px solid #444;
            border-radius: 4px;
            padding: 5px;
        }
        QTabWidget::pane {
            border: 1px solid #444;
            background-color: #1a1a1a;
        }
        QTabBar::tab {
            background-color: #2d2d2d;
            border: 1px solid #444;
            padding: 8px 16px;
        }
        QTabBar::tab:selected {
            background-color: #4CAF50;
        }
        QScrollArea {
            border: none;
        }
    """)
    
    font = QFont("Segoe UI", 10)
    qt_app.setFont(font)
    
    # Create and configure qasync event loop
    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)
    
    # Create application runner
    app_runner = ApplicationRunner(qt_app)
    
    # Run async application
    with loop:
        exit_code = loop.run_until_complete(app_runner.run())
    
    return exit_code


run_app = main


class ApplicationRunner:
    """Application runner with async support."""
    
    def __init__(self, app: QApplication) -> None:
        """Initialize runner.
        
        Args:
            app: QApplication instance
        """
        self.app = app
        self.startup_dialog: StartupDialog | None = None
        self.main_window: MainWindow | None = None
        self._exit_code: int = 0
        self._selection: dict = {}
    
    async def run(self) -> int:
        """Run application.
        
        Returns:
            Exit code
        """
        # Phase 1: Show startup dialog and wait for user
        result = await self._show_startup_dialog()
        
        if not result:
            return 0
        
        # Apply execution settings from dialog
        self._apply_execution_settings()
        
        # Phase 2: Create and show main window, run until closed
        await self._run_main_window()
        
        return self._exit_code
    
    def _apply_execution_settings(self) -> None:
        """Apply execution mode and RunPod settings from dialog selection."""
        import os
        from luna.core.config import reload_settings

        execution_mode = self._selection.get("execution_mode", "LOCAL")
        runpod_id = self._selection.get("runpod_id", "")
        no_media = self._selection.get("no_media", False)

        # Update environment variables
        os.environ["EXECUTION_MODE"] = execution_mode
        if runpod_id:
            os.environ["RUNPOD_ID"] = runpod_id
        if no_media:
            os.environ["LUNA_DEBUG_NO_MEDIA"] = "1"
            logger.debug("[App] Media generation disabled (no_media from UI)")

        # Reload settings to pick up changes
        reload_settings()

        logger.debug(f"[App] Execution mode set to: {execution_mode}")
        if runpod_id:
            logger.debug(f"[App] RunPod ID set to: {runpod_id}")
    
    async def _show_startup_dialog(self) -> bool:
        """Show startup dialog and return True if user accepted.
        
        Returns:
            True if user clicked Start, False otherwise
        """
        self.startup_dialog = StartupDialog()
        
        # Create future to wait for dialog
        future = asyncio.Future()
        
        def on_accepted() -> None:
            if not future.done():
                future.set_result(StartupDialog.Accepted)
        
        def on_rejected() -> None:
            if not future.done():
                future.set_result(StartupDialog.Rejected)
        
        self.startup_dialog.accepted.connect(on_accepted)
        self.startup_dialog.rejected.connect(on_rejected)
        
        # Show dialog (non-blocking)
        self.startup_dialog.show()
        self.startup_dialog.raise_()
        self.startup_dialog.activateWindow()
        
        # Wait for result
        result = await future
        
        # Get selection before cleanup
        selection = self.startup_dialog.get_selection()
        
        # Cleanup
        self.startup_dialog.hide()
        self.startup_dialog.deleteLater()
        self.startup_dialog = None
        
        if result != StartupDialog.Accepted:
            return False
        
        self._selection = selection
        return True
    
    async def _run_main_window(self) -> None:
        """Create, initialize and run main window until closed."""
        self.main_window = MainWindow()
        
        # Initialize game before showing
        try:
            if self._selection["mode"] == "new":
                await self.main_window.initialize_game(
                    world_id=self._selection["world_id"],
                    companion=self._selection["companion"],
                )
            elif self._selection["mode"] == "load":
                await self.main_window.initialize_game(
                    world_id=self._selection["world_id"] or "default",
                    companion=self._selection["companion"] or "Luna",
                    session_id=self._selection["session_id"],
                )
        except Exception as e:
            logger.error(f"[App] Failed to initialize game: {e}")
            self._exit_code = 1
            return
        
        # Show main window
        self.main_window.show()
        
        # Wait for window to close using QEventLoop
        await self._wait_for_close()
    
    async def _wait_for_close(self) -> None:
        """Wait for main window to close."""
        if not self.main_window:
            return
        
        future = asyncio.Future()
        check_timer: Optional[QTimer] = None
        
        # Also connect destroyed signal
        def on_destroyed() -> None:
            try:
                if check_timer and check_timer.isActive():
                    check_timer.stop()
            except RuntimeError:
                pass  # QTimer already deleted by Qt
            if not future.done():
                future.set_result(None)
        
        # Use QTimer to check periodically
        check_timer = QTimer()
        
        def check_visible() -> None:
            if self.main_window and not self.main_window.isVisible():
                if check_timer and check_timer.isActive():
                    check_timer.stop()
                if not future.done():
                    future.set_result(None)
        
        check_timer.timeout.connect(check_visible)
        check_timer.start(100)  # Check every 100ms
        
        self.main_window.destroyed.connect(on_destroyed)
        
        # Wait
        await future


if __name__ == "__main__":
    sys.exit(main())
