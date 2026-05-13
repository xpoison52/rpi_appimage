#!/bin/sh
# Install launcher and Cage Wayland session files under PREFIX (default /usr/local).
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
PREFIX="${PREFIX:-/usr/local}"

echo "Installing rpi-appimage-launcher to $PREFIX (sudo required)..."
sudo install -d "$PREFIX/lib/rpi-appimage-launcher" \
  "$PREFIX/bin" \
  "$PREFIX/share/wayland-sessions" \
  "$PREFIX/share/applications" \
  "$PREFIX/share/xsessions"

sudo install -m644 "$ROOT/lib/appimage_grid_launcher.py" "$PREFIX/lib/rpi-appimage-launcher/"
sudo install -m755 "$ROOT/bin/rpi-appimage-cage-session" "$PREFIX/bin/"
sudo install -m755 "$ROOT/bin/rpi-appimage-openbox-session" "$PREFIX/bin/"
sudo install -m644 "$ROOT/share/wayland-sessions/cage-appimage-grid.desktop" "$PREFIX/share/wayland-sessions/"
sudo install -m644 "$ROOT/share/applications/appimage-grid-launcher.desktop" "$PREFIX/share/applications/"
sudo install -m644 "$ROOT/share/xsessions/openbox-appimage-grid.desktop" "$PREFIX/share/xsessions/"

echo "Done."
echo ""
echo "On Raspberry Pi OS, install dependencies:"
echo "  sudo apt update"
echo "  sudo apt install -y cage python3-gi gir1.2-gtk-3.0 dbus-x11"
echo ""
echo "Per-user setup (run as kiosk user):"
echo "  sh $ROOT/scripts/setup-user-apps.sh"
echo ""
echo "Autologin into the grid session (lightdm): copy"
echo "  $ROOT/share/lightdm/lightdm.conf.d/90-appimage-kiosk.conf.example"
echo "to /etc/lightdm/lightdm.conf.d/90-appimage-kiosk.conf and edit autologin-user."
echo "Set autologin-session=cage-appimage-grid (Wayland) or openbox-appimage-grid (X11)."
