"""System-tray integration for the hub.

When the operator closes the main window with the X button, instead of
quitting we hide the window and keep the tray icon visible. The tray
icon's right-click menu lets them re-open the window or quit the app for
real.

Lifecycle (from `app.main`):
  1. `MainWindow` is constructed.
  2. `TrayController.attach(window, on_quit)` is called — installs the
     `WM_DELETE_WINDOW` protocol handler and starts the tray icon in a
     daemon thread.
  3. When user picks "Quit" from the tray, `on_quit` runs in the Tk main
     thread (via `window.after(0, ...)`) and the icon thread is stopped.

The whole module degrades gracefully if `pystray` / `Pillow` aren't
present — it just logs and skips, leaving the original
"X = exit" behavior.
"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional


class TrayController:
    def __init__(self, app_name: str = "Aventus Bot Hub") -> None:
        self._app_name = app_name
        self._icon = None  # pystray.Icon or None
        self._window: Optional[tk.Tk] = None
        self._on_quit: Optional[Callable[[], None]] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_lock = threading.Lock()
        self._installed = False

    def attach(
        self,
        window: tk.Tk,
        icon_png_path: Path,
        on_quit: Callable[[], None],
    ) -> bool:
        """Install the close-to-tray hook and start the tray icon thread.
        Returns True if tray is active, False if pystray is unavailable
        (fallback: the X button keeps its default "exit" behavior).
        """
        try:
            import pystray  # noqa: F401
            from PIL import Image
        except ImportError:
            return False

        self._window = window
        self._on_quit = on_quit

        try:
            image = Image.open(str(icon_png_path))
        except Exception:
            return False

        # Install the close-to-tray handler in Tk's main thread.
        window.protocol("WM_DELETE_WINDOW", self._on_close_window)

        # Build the tray icon + its menu.
        from pystray import Icon, Menu, MenuItem
        self._icon = Icon(
            "aventus-bot-hub",
            image,
            self._app_name,
            menu=Menu(
                MenuItem(
                    "Open",
                    self._on_open,
                    default=True,  # double-click on tray = Open
                ),
                Menu.SEPARATOR,
                MenuItem("Quit", self._on_quit_menu),
            ),
        )

        # pystray.run is blocking — run on a daemon thread so it doesn't
        # interfere with the Tk mainloop.
        self._thread = threading.Thread(
            target=self._icon.run, name="tray-icon", daemon=True,
        )
        self._thread.start()
        self._installed = True
        return True

    # ------------------------------------------------------------------
    # Window-close handler
    # ------------------------------------------------------------------

    def _on_close_window(self) -> None:
        """Called by Tk when the user clicks X on the main window. Hide
        instead of destroy; the tray icon remains active."""
        if self._window is None:
            return
        try:
            self._window.withdraw()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Tray-menu actions (run on the tray thread, must dispatch to Tk)
    # ------------------------------------------------------------------

    def _on_open(self, icon=None, item=None) -> None:  # noqa: ARG002
        win = self._window
        if win is None:
            return
        def back() -> None:
            try:
                win.deiconify()
                win.state("zoomed")
                win.lift()
                win.focus_force()
            except tk.TclError:
                pass
        try:
            win.after(0, back)
        except tk.TclError:
            pass

    def _on_quit_menu(self, icon=None, item=None) -> None:  # noqa: ARG002
        # Stop the icon first (returns from icon.run, freeing the thread),
        # then dispatch the actual quit into the Tk main thread.
        with self._stop_lock:
            if self._icon is not None:
                try:
                    self._icon.stop()
                except Exception:
                    pass
        win = self._window
        cb = self._on_quit
        if cb is None or win is None:
            return
        def back() -> None:
            try:
                cb()
            except Exception:
                pass
        try:
            win.after(0, back)
        except tk.TclError:
            pass

    def shutdown(self) -> None:
        """Stop the tray icon. Call from main when the app is exiting
        through some other path (e.g. mainloop ended)."""
        with self._stop_lock:
            if self._icon is not None:
                try:
                    self._icon.stop()
                except Exception:
                    pass
            self._icon = None
