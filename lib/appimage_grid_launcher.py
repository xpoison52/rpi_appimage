#!/usr/bin/env python3
"""
Fullscreen grid launcher for AppImage files on Wayland/X11 (GTK3).
Scans ~/AppImages and optional *.desktop in ~/.local/share/applications
whose Exec line points to an AppImage path.
"""
from __future__ import annotations

import configparser
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, Gtk  # noqa: E402


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
        for p in sorted(appimages_dir.glob("*.AppImage")):
            if os.access(p, os.X_OK) and p.is_file():
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
        super().__init__(application=app, title="AppImage")
        self._launcher = app
        self.set_default_size(1024, 600)
        self.cols = max(1, app.cols)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)

        title = Gtk.Label(label="Applications")
        title.set_markup("<span size='x-large' weight='bold'>Applications</span>")
        outer.pack_start(title, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)

        self.grid = Gtk.Grid()
        self.grid.set_row_spacing(12)
        self.grid.set_column_spacing(12)
        self.grid.set_column_homogeneous(True)
        self.grid.set_row_homogeneous(False)

        scrolled.add(self.grid)
        outer.pack_start(scrolled, True, True, 0)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        refresh = Gtk.Button.new_with_label("Refresh")
        refresh.connect("clicked", lambda *_: self.refresh_grid())
        bar.pack_start(refresh, False, False, 0)
        hint = Gtk.Label(label="F5 refresh · Ctrl+Shift+Q quit launcher")
        hint.set_halign(Gtk.Align.END)
        hint.set_hexpand(True)
        bar.pack_start(hint, True, True, 0)
        outer.pack_start(bar, False, False, 0)

        self.add(outer)
        self._fill_grid(entries)
        self.connect("key-press-event", self._on_key_press)
        # Kiosk: ignore WM close; use Ctrl+Shift+Q to exit launcher
        self.connect("delete-event", lambda *_a: True)

    def _clear_grid(self) -> None:
        for child in self.grid.get_children():
            self.grid.remove(child)
            child.destroy()

    def _fill_grid(self, entries: list[dict]) -> None:
        icon_size = 72
        row, col = 0, 0
        for ent in entries:
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            vbox.set_margin_top(8)
            vbox.set_margin_bottom(8)
            vbox.set_margin_start(8)
            vbox.set_margin_end(8)
            img = _load_icon(ent["icon_name"], icon_size)
            vbox.pack_start(img, False, False, 0)
            lbl = Gtk.Label(label=ent["name"])
            lbl.set_line_wrap(True)
            lbl.set_max_width_chars(16)
            lbl.set_justify(Gtk.Justification.CENTER)
            vbox.pack_start(lbl, False, False, 0)
            btn.add(vbox)
            path = ent["path"]
            btn.connect("clicked", self._on_launch, path)
            self.grid.attach(btn, col, row, 1, 1)
            col += 1
            if col >= self.cols:
                col = 0
                row += 1

    def refresh_grid(self) -> None:
        entries = _discover_apps(self._launcher.appimages_dir, self._launcher.applications_dir)
        self._clear_grid()
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
