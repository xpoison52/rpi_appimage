#!/usr/bin/env python3
"""
Fullscreen grid launcher for AppImage files on Wayland/X11 (GTK3).
Scans ~/AppImages for *.appimage (any case) and optional *.desktop in
~/.local/share/applications whose Exec line points to an AppImage path.
"""
from __future__ import annotations

import configparser
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# Before GTK: AT-SPI over D-Bus breaks some minimal Wayland sessions (black window).
os.environ.setdefault("NO_AT_BRIDGE", "1")

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, Gtk, Pango  # noqa: E402

_LAUNCHER_CSS = b"""
#launcher-shell.app-grid-launcher {
  background-color: #0c0e12;
}
.app-grid-launcher .header-area {
  background-color: #141820;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.app-grid-launcher .footer-area {
  background-color: #0c0e12;
  border-top: 1px solid rgba(255,255,255,0.06);
}
.app-grid-launcher .title-primary {
  color: #f0f3f8;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.02em;
}
.app-grid-launcher .title-secondary {
  color: rgba(240,243,248,0.45);
  font-size: 13px;
  margin-top: 2px;
}
.app-grid-launcher .hint-muted {
  color: rgba(240,243,248,0.38);
  font-size: 12px;
}
.app-grid-launcher .empty-state {
  color: rgba(240,243,248,0.5);
  font-size: 15px;
  padding: 48px;
}
.app-grid-launcher button.refresh-btn {
  color: #e8ecf4;
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px;
  padding: 8px 14px;
  font-weight: 500;
  min-height: 36px;
}
.app-grid-launcher button.refresh-btn:hover {
  background: rgba(255,255,255,0.11);
  border-color: rgba(255,255,255,0.16);
}
.app-grid-launcher button.refresh-btn:active {
  background: rgba(255,255,255,0.05);
}
.app-grid-launcher button.app-tile {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 16px;
  padding: 18px 14px 14px 14px;
  outline: none;
  min-width: 132px;
  min-height: 148px;
}
.app-grid-launcher button.app-tile:hover {
  background: rgba(255,255,255,0.09);
  border-color: rgba(120,160,255,0.35);
}
.app-grid-launcher button.app-tile:active {
  background: rgba(255,255,255,0.06);
}
.app-grid-launcher button.app-tile label {
  color: #e8ecf4;
  font-size: 13px;
  font-weight: 500;
}
.app-grid-launcher scrolledwindow {
  background-color: #0c0e12;
}
.app-grid-launcher viewport {
  background-color: #0c0e12;
}
.app-grid-launcher flowbox {
  background-color: #0c0e12;
}
"""


def _apply_launcher_css() -> None:
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    provider = Gtk.CssProvider()
    try:
        provider.load_from_data(_LAUNCHER_CSS)
    except Exception as e:
        print("appimage_grid_launcher: CSS not applied:", e, file=sys.stderr)
        return
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def _home() -> Path:
    return Path(os.environ.get("HOME", "/"))


def _parse_desktop_file(path: Path) -> dict[str, str] | None:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cp.read_string("[Desktop Entry]\n" + "\n".join(line for line in raw.splitlines() if line.strip()))
    except configparser.Error:
        return None
    if not cp.has_section("Desktop Entry"):
        return None

    def get(k: str) -> str:
        return cp.get("Desktop Entry", k, fallback="").strip()

    typ = get("Type")
    if typ and typ != "Application":
        return None
    name = get("Name") or path.stem
    exec_line = get("Exec")
    if not exec_line:
        return None
    icon = get("Icon")
    parts = shlex.split(exec_line.split("%")[0].strip())
    if not parts:
        return None
    return {"name": name, "exec": parts, "icon": icon, "desktop": str(path)}


def _exec_is_appimage(parts: list[str]) -> Path | None:
    if not parts:
        return None
    candidate = Path(parts[0]).expanduser()
    if candidate.suffix.lower() == ".appimage" and candidate.is_file():
        return candidate
    return None


def _discover_apps(appimages_dir: Path, applications_dir: Path) -> list[dict]:
    apps: dict[str, dict] = {}

    if appimages_dir.is_dir():
        for p in sorted(appimages_dir.iterdir()):
            if not p.is_file() or p.suffix.lower() != ".appimage":
                continue
            if not os.access(p, os.X_OK):
                continue
            key = str(p.resolve())
            apps[key] = {
                "name": p.stem.replace("-", " ").replace("_", " "),
                "path": p,
                "icon_name": "application-x-executable",
            }

    if applications_dir.is_dir():
        for desktop in sorted(applications_dir.glob("*.desktop")):
            meta = _parse_desktop_file(desktop)
            if not meta:
                continue
            img = _exec_is_appimage(meta["exec"])
            if not img or not img.is_file() or not os.access(img, os.X_OK):
                continue
            key = str(img.resolve())
            icon = meta["icon"] or "application-x-executable"
            apps[key] = {"name": meta["name"], "path": img, "icon_name": icon}

    return sorted(apps.values(), key=lambda a: a["name"].lower())


def _load_icon(icon_name: str, size: int) -> Gtk.Image:
    theme = Gtk.IconTheme.get_default()
    pixbuf = None
    if Path(icon_name).is_file():
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(icon_name, size, size)
        except Exception:
            pixbuf = None
    if pixbuf is None:
        for name in (icon_name, "application-x-executable"):
            try:
                pixbuf = theme.load_icon(name, size, Gtk.IconLookupFlags.FORCE_SIZE)
                break
            except Exception:
                continue
    if pixbuf is None:
        img = Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
        img.set_pixel_size(size)
        return img
    return Gtk.Image.new_from_pixbuf(pixbuf)


class AppImageGridLauncher(Gtk.ApplicationWindow):
    def __init__(self, app: "GridLauncherApp", entries: list[dict]) -> None:
        super().__init__(application=app, title="")
        self._launcher = app
        self.cols = max(1, app.cols)
        # Under Wayland (Cage), Gdk.Screen geometry in __init__ is often wrong → black window.
        self.set_default_size(1280, 720)
        self.set_decorated(False)
        self.set_title("")

        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        shell.set_name("launcher-shell")
        shell.get_style_context().add_class("app-grid-launcher")
        shell.set_hexpand(True)
        shell.set_vexpand(True)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.set_hexpand(True)
        root.set_vexpand(True)
        root.set_name("launcher-root")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        header.set_margin_top(20)
        header.set_margin_bottom(18)
        header.set_margin_start(28)
        header.set_margin_end(28)
        header.get_style_context().add_class("header-area")

        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_primary = Gtk.Label(xalign=0)
        title_primary.set_text("Apps")
        title_primary.get_style_context().add_class("title-primary")
        title_secondary = Gtk.Label(xalign=0)
        title_secondary.set_text("Choose an application to launch")
        title_secondary.get_style_context().add_class("title-secondary")
        titles.pack_start(title_primary, False, False, 0)
        titles.pack_start(title_secondary, False, False, 0)

        refresh = Gtk.Button.new_with_label("Refresh")
        refresh.set_relief(Gtk.ReliefStyle.NONE)
        refresh.get_style_context().add_class("refresh-btn")
        refresh.connect("clicked", lambda *_: self.refresh_grid())

        header.pack_start(titles, True, True, 0)
        header.pack_end(refresh, False, False, 0)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(200)

        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_vexpand(True)
        empty_lbl = Gtk.Label(label="No AppImages found.\nPut .AppImage files in your AppImages folder, make them executable,\nthen press Refresh.")
        empty_lbl.set_justify(Gtk.Justification.CENTER)
        empty_lbl.set_line_spacing(6)
        empty_lbl.get_style_context().add_class("empty-state")
        empty_box.pack_start(empty_lbl, True, True, 0)
        self._stack.add_named(empty_box, "empty")

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.set_margin_start(24)
        scrolled.set_margin_end(24)
        scrolled.set_margin_top(4)
        scrolled.set_margin_bottom(8)

        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_activate_on_single_click(True)
        self.flow.set_homogeneous(False)
        self.flow.set_max_children_per_line(self.cols)
        self.flow.set_min_children_per_line(1)
        self.flow.set_row_spacing(16)
        self.flow.set_column_spacing(16)
        self.flow.set_valign(Gtk.Align.START)

        scrolled.add(self.flow)
        self._stack.add_named(scrolled, "grid")

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        footer.set_margin_top(12)
        footer.set_margin_bottom(18)
        footer.set_margin_start(28)
        footer.set_margin_end(28)
        footer.get_style_context().add_class("footer-area")
        hint = Gtk.Label(label="F5 refresh   ·   Ctrl+Shift+Q exit launcher")
        hint.set_halign(Gtk.Align.CENTER)
        hint.set_hexpand(True)
        hint.get_style_context().add_class("hint-muted")
        footer.pack_start(hint, True, True, 0)

        root.pack_start(header, False, False, 0)
        root.pack_start(self._stack, True, True, 0)
        root.pack_start(footer, False, False, 0)

        shell.pack_start(root, True, True, 0)
        self.add(shell)
        self._fill_grid(entries)
        self.connect("key-press-event", self._on_key_press)
        self.connect("delete-event", lambda *_a: True)
        self._map_h = self.connect("map", self._on_first_map)

    def _on_first_map(self, *_args: object) -> None:
        display = Gdk.Display.get_default()
        mon = None
        win = self.get_window()
        if display is not None and win is not None:
            mon = display.get_monitor_at_window(win)
        if mon is None and display is not None:
            mon = display.get_primary_monitor()
        if mon is None and display is not None:
            mon = display.get_monitor(0)
        if mon is not None:
            g = mon.get_geometry()
            if g.width >= 320 and g.height >= 240:
                self.resize(g.width, g.height)
        self.queue_draw()
        if self._map_h is not None:
            self.disconnect(self._map_h)
            self._map_h = None

    def _clear_flow(self) -> None:
        for child in self.flow.get_children():
            self.flow.remove(child)
            child.destroy()

    def _fill_grid(self, entries: list[dict]) -> None:
        self._clear_flow()
        if not entries:
            self._stack.set_visible_child_name("empty")
            return
        self._stack.set_visible_child_name("grid")
        icon_size = 88
        for ent in entries:
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.get_style_context().add_class("app-tile")
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            vbox.set_halign(Gtk.Align.CENTER)
            img = _load_icon(ent["icon_name"], icon_size)
            img.set_halign(Gtk.Align.CENTER)
            lbl = Gtk.Label(label=ent["name"])
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.set_line_wrap(True)
            lbl.set_max_width_chars(14)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_lines(2)
            lbl.set_halign(Gtk.Align.CENTER)
            vbox.pack_start(img, False, False, 0)
            vbox.pack_start(lbl, False, False, 0)
            btn.add(vbox)
            path = ent["path"]
            btn.connect("clicked", self._on_launch, path)
            self.flow.add(btn)
        self.flow.show_all()

    def refresh_grid(self) -> None:
        entries = _discover_apps(self._launcher.appimages_dir, self._launcher.applications_dir)
        self._fill_grid(entries)

    def _on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_F5:
            self.refresh_grid()
            return True
        if event.state & Gdk.ModifierType.CONTROL_MASK and event.state & Gdk.ModifierType.SHIFT_MASK:
            if event.keyval in (Gdk.KEY_q, Gdk.KEY_Q):
                self.get_application().quit()
                return True
        return False

    def _on_launch(self, _btn: Gtk.Widget, path: Path) -> None:
        env = os.environ.copy()
        try:
            subprocess.Popen([str(path)], env=env, start_new_session=True)
        except OSError as e:
            dlg = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.CLOSE,
                text="Failed to start",
            )
            dlg.format_secondary_text(str(e))
            dlg.run()
            dlg.destroy()


class GridLauncherApp(Gtk.Application):
    def __init__(self, appimages_dir: Path, applications_dir: Path, cols: int) -> None:
        super().__init__(application_id="io.cursor.rpi_appimage_grid", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.appimages_dir = appimages_dir
        self.applications_dir = applications_dir
        self.cols = cols
        self._win: AppImageGridLauncher | None = None

    def do_activate(self) -> None:
        if self._win is None:
            settings = Gtk.Settings.get_default()
            if settings is not None:
                settings.set_property("gtk-application-prefer-dark-theme", True)
                settings.set_property("gtk-theme-name", "Adwaita")
            _apply_launcher_css()
            entries = _discover_apps(self.appimages_dir, self.applications_dir)
            self._win = AppImageGridLauncher(self, entries)
            self._win.connect("destroy", self._on_window_destroy)
            self._win.show_all()
        self._win.present()

    def _on_window_destroy(self, *_args: object) -> None:
        self._win = None


def main(argv: Iterable[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(description="GTK grid launcher for AppImages.")
    p.add_argument(
        "--appimages-dir",
        type=Path,
        default=_home() / "AppImages",
        help="Directory containing .AppImage files (default: ~/AppImages)",
    )
    p.add_argument(
        "--applications-dir",
        type=Path,
        default=_home() / ".local" / "share" / "applications",
        help="Desktop entry directory (default: ~/.local/share/applications)",
    )
    p.add_argument("--cols", type=int, default=4, help="Grid columns (default: 4)")
    args = p.parse_args(list(argv)[1:])

    app = GridLauncherApp(args.appimages_dir.expanduser(), args.applications_dir.expanduser(), args.cols)
    return app.run(None)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
