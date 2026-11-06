#!/usr/bin/env bash
# Запуск автоматических тестов в окружении fluidcalc. Журнал: docs/TEST_REPORT.txt
set -u
APP_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
CONDA_ROOT="${FLUIDCALC_CONDA:-$HOME/miniforge3}"
ENV_NAME="${FLUIDCALC_ENV:-fluidcalc}"
PY="${FLUIDCALC_PYTHON:-$CONDA_ROOT/envs/$ENV_NAME/bin/python}"
[ -x "$PY" ] || { echo "Не найден $PY"; exit 1; }
cd "$APP_DIR"
export QT_QPA_PLATFORM=offscreen
TMPHOME="$(mktemp -d)"
export XDG_DATA_HOME="$TMPHOME"          # тесты не трогают рабочую базу пользователя
REPORT="$APP_DIR/docs/TEST_REPORT.txt"
{
  echo "FluidCalc — журнал автоматических тестов"
  echo "Дата: $(date '+%F %T %Z')"
  "$PY" tools/check_env.py
  echo
  "$PY" -m unittest discover -s tests -v 2>&1 | grep -v 'propagateSizeHints'
} | tee "$REPORT"
rc=${PIPESTATUS[0]}
rm -rf "$TMPHOME"
echo
echo "Сводка по статусам (passed / failed / skipped):"
grep -cE '\.\.\. ok$' "$REPORT" | sed 's/^/  passed:  /'
grep -cE '\.\.\. (FAIL|ERROR)$' "$REPORT" | sed 's/^/  failed:  /'
grep -cE '\.\.\. skipped' "$REPORT" | sed 's/^/  skipped: /'
echo "Напоминание: успешные unit-тесты не являются независимой научной валидацией."
exit "$rc"
