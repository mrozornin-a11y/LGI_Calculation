#!/usr/bin/env bash
# Удаляет только ярлыки FluidCalc. База данных и журналы (~/.local/share/fluidcalc) не трогаются.
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
rm -f "$APPS/fluidcalc.desktop"
for d in "$(xdg-user-dir DESKTOP 2>/dev/null)" "$HOME/Рабочий стол" "$HOME/Desktop"; do
    [ -n "$d" ] && rm -f "$d/fluidcalc.desktop"
done
echo "Ярлыки удалены. Данные: ${XDG_DATA_HOME:-$HOME/.local/share}/fluidcalc"
