"""Sleek Floating Pill overlay for real-time dictation using GTK4 and Layer Shell."""

from __future__ import annotations

import os
import threading
from typing import Optional

# Ensure GTK4 Layer Shell loads before libwayland
os.environ.setdefault("LD_PRELOAD", "/usr/lib/libgtk4-layer-shell.so")

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gdk, Gtk4LayerShell, GLib, Pango


CSS = """
window.dictate-pill {
    background-color: transparent;
}

.pill-container {
    background: rgba(18, 20, 28, 0.92);
    border: 1.5px solid rgba(255, 255, 255, 0.15);
    border-radius: 28px;
    padding: 10px 22px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}

.pill-icon {
    font-size: 18px;
    color: #ef4444; /* red for recording */
    margin-right: 12px;
}

.pill-icon.polishing {
    color: #38bdf8; /* cyan for polishing */
}

.pill-text {
    font-size: 15px;
    font-weight: 500;
    color: #f8fafc;
}

.pill-text.muted {
    color: #94a3b8;
    font-style: italic;
}
"""


class FloatingPillWindow:
    """Floating live transcript pill that hovers above the active window with direct Enter/Esc handling."""

    def __init__(
        self,
        on_close: Optional[callable] = None,
        on_stop: Optional[callable] = None,
        on_cancel: Optional[callable] = None,
    ):
        self.on_close = on_close
        self.on_stop = on_stop
        self.on_cancel = on_cancel
        self._app: Optional[Gtk.Application] = None
        self._win: Optional[Gtk.ApplicationWindow] = None
        self._icon_label: Optional[Gtk.Label] = None
        self._text_label: Optional[Gtk.Label] = None
        self._thread: Optional[threading.Thread] = None
        self._ready_event = threading.Event()

    def start(self) -> None:
        """Start GTK application in a dedicated thread."""
        self._thread = threading.Thread(target=self._run_gtk, daemon=True)
        self._thread.start()
        self._ready_event.wait(timeout=3.0)

    def _run_gtk(self) -> None:
        # Create isolated application
        app_id = f"com.omarchy.dictate.pill_{os.getpid()}"
        self._app = Gtk.Application(application_id=app_id)
        self._app.connect("activate", self._on_activate)
        self._app.run([])

    def _on_activate(self, app: Gtk.Application) -> None:
        # Apply CSS
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._win = Gtk.ApplicationWindow(application=app)
        self._win.add_css_class("dictate-pill")

        # Initialize Layer Shell
        Gtk4LayerShell.init_for_window(self._win)
        Gtk4LayerShell.set_layer(self._win, Gtk4LayerShell.Layer.OVERLAY)
        # EXCLUSIVE keyboard mode directly receives Enter & Escape from physical keyboard
        Gtk4LayerShell.set_keyboard_mode(self._win, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)

        # Add key controller for immediate Enter and Escape handling
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self._win.add_controller(key_ctrl)

        # Anchor bottom-center with 48px margin
        Gtk4LayerShell.set_anchor(self._win, Gtk4LayerShell.Edge.BOTTOM, True)
        Gtk4LayerShell.set_margin(self._win, Gtk4LayerShell.Edge.BOTTOM, 48)
        Gtk4LayerShell.set_anchor(self._win, Gtk4LayerShell.Edge.LEFT, False)
        Gtk4LayerShell.set_anchor(self._win, Gtk4LayerShell.Edge.RIGHT, False)
        Gtk4LayerShell.set_anchor(self._win, Gtk4LayerShell.Edge.TOP, False)

        # Container box
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.add_css_class("pill-container")

        self._icon_label = Gtk.Label(label="󰍬")
        self._icon_label.add_css_class("pill-icon")
        box.append(self._icon_label)

        self._text_label = Gtk.Label(label="Listening... (Enter to finish, Esc to cancel)")
        self._text_label.add_css_class("pill-text")
        self._text_label.add_css_class("muted")
        # Max width & wrap with start-ellipsize so long speech (e.g. 10+ sentences) stays readable & compact
        self._text_label.set_max_width_chars(64)
        self._text_label.set_wrap(True)
        self._text_label.set_lines(3)
        self._text_label.set_ellipsize(Pango.EllipsizeMode.START)
        box.append(self._text_label)

        self._win.set_child(box)
        self._win.present()
        self._ready_event.set()

    def update_text(self, text: str) -> None:
        """Update the live text display safely from any thread."""
        GLib.idle_add(self._do_update_text, text)

    def _do_update_text(self, text: str) -> bool:
        if self._text_label:
            clean = text.strip()
            if clean:
                self._text_label.remove_css_class("muted")
                self._text_label.set_text(clean)
            else:
                self._text_label.add_css_class("muted")
                self._text_label.set_text("Listening... (Enter to finish, Esc to cancel)")
        return False

    def set_polishing(self) -> None:
        """Transition the pill into polishing state."""
        GLib.idle_add(self._do_set_polishing)

    def _do_set_polishing(self) -> bool:
        if self._icon_label:
            self._icon_label.set_text("󱚟")
            self._icon_label.add_css_class("polishing")
        if self._text_label:
            self._text_label.remove_css_class("muted")
            self._text_label.set_lines(1)
            self._text_label.set_text("Polishing transcript...")
        return False

    def close(self) -> None:
        """Close the floating pill window and quit GTK."""
        GLib.idle_add(self._do_close)

    def _do_close(self) -> bool:
        if self._win:
            self._win.close()
            self._win = None
        if self._app:
            self._app.quit()
            self._app = None
        if self.on_close:
            self.on_close()
        return False

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        name = Gdk.keyval_name(keyval) or ""
        if (
            keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter)
            or name in ("Return", "KP_Enter", "ISO_Enter")
            or keycode in (36, 104)
        ):
            self._trigger_stop()
            return True
        elif keyval == Gdk.KEY_Escape or name in ("Escape", "Esc") or keycode == 9:
            self._trigger_cancel()
            return True
        return False

    def _trigger_stop(self) -> None:
        self.set_polishing()
        if self.on_stop:
            self.on_stop()

    def _trigger_cancel(self) -> None:
        self.close()
        if self.on_cancel:
            self.on_cancel()
