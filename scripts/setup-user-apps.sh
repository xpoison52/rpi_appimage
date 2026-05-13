#!/bin/sh
# Creates ~/AppImages and ~/.local/share/applications; optional sample .desktop.
# Run as the kiosk/desktop user (not root), or pass TARGET_USER=myuser sudo -u myuser ...
set -eu

HOME_DIR="${HOME:-$(getent passwd "${TARGET_USER:-$USER}" | cut -d: -f6)}"
APPIMG_DIR="${APPIMAGE_DIR:-$HOME_DIR/AppImages}"
APPS_DIR="$HOME_DIR/.local/share/applications"

mkdir -p "$APPIMG_DIR" "$APPS_DIR"

# Ensure AppImages are executable when copied into this folder (user responsibility).
chmod -f +x "$APPIMG_DIR"/*.AppImage 2>/dev/null || true

SAMPLE="$APPS_DIR/example-myapp.desktop"
if [ ! -f "$SAMPLE" ]; then
  cat >"$SAMPLE" <<'EOF'
[Desktop Entry]
Type=Application
Version=1.0
Name=Example App (edit me)
Comment=Copy this file and set Exec to your AppImage path
Exec=/home/USER/AppImages/ChangeMe-aarch64.AppImage
Icon=application-x-executable
Terminal=false
Categories=Utility;
EOF
  echo "Created sample desktop (edit Exec path): $SAMPLE"
else
  echo "Sample desktop already exists: $SAMPLE"
fi

echo "AppImage directory: $APPIMG_DIR"
echo "Desktop files:      $APPS_DIR"
echo "Place *.AppImage in $APPIMG_DIR and chmod +x each file."
