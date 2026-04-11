"""Luna RPG - Main Window Package.

Refactored from a 2715-line monolith into 6 focused components:
- MainWindow      (coordinator, ~200 lines)
- LayoutManager   (UI layout and widgets)
- GameController  (game loop and turn execution)
- EventHandler    (UI event processing)
- DisplayManager  (UI updates and rendering)
- MediaManager    (save/load, audio, video)

Backward compatibility: ``from luna.ui.main_window import MainWindow`` unchanged.
"""
from .main_window import MainWindow

__all__ = ["MainWindow"]
