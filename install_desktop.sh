#!/usr/bin/env bash
# Создаёт ярлык FluidCalc в меню приложений и на рабочем столе текущего пользователя.
# Права администратора не нужны; системные настройки OSNova не изменяются.
set -eu
APP_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
chmod +x "$APP_DIR/fluidcalc.sh" "$APP_DIR/run_tests.sh" 2>/dev/null || true

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
DESKTOP_FILE="$APPS/fluidcalc.desktop"
cat > "$DESKTOP_FILE" <<DESK
[Desktop Entry]
Type=Application
Version=1.0
Name=FluidCalc
Name[ru]=FluidCalc — флюидные включения
GenericName=Fluid inclusion microthermometry
GenericName[ru]=Микротермометрия флюидных включений
Comment[ru]=Расчёт солёности и плотности CO₂ по данным микротермометрии (исследовательский прототип)
Exec="$APP_DIR/fluidcalc.sh"
Path=$APP_DIR
Icon=$APP_DIR/fluid_app/resources/fluidcalc.svg
Terminal=false
Categories=Science;Education;Geology;
StartupNotify=true
StartupWMClass=fluidcalc
DESK
chmod +x "$DESKTOP_FILE"
echo "Ярлык меню: $DESKTOP_FILE"

DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
if [ -z "$DESKTOP_DIR" ] || [ "$DESKTOP_DIR" = "$HOME" ]; then
    for d in "$HOME/Рабочий стол" "$HOME/Desktop"; do [ -d "$d" ] && DESKTOP_DIR="$d" && break; done
fi
if [ -n "${DESKTOP_DIR:-}" ] && [ -d "$DESKTOP_DIR" ]; then
    cp "$DESKTOP_FILE" "$DESKTOP_DIR/fluidcalc.desktop"
    chmod +x "$DESKTOP_DIR/fluidcalc.desktop"
    # GNOME-подобные оболочки; в KDE достаточно бита исполнения
    command -v gio >/dev/null 2>&1 && gio set "$DESKTOP_DIR/fluidcalc.desktop" metadata::trusted true 2>/dev/null || true
    echo "Ярлык на рабочем столе: $DESKTOP_DIR/fluidcalc.desktop"
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null || true
echo "Готово. Запуск: двойной щелчок по ярлыку FluidCalc (или $APP_DIR/fluidcalc.sh)."
