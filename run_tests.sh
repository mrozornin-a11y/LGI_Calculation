#!/usr/bin/env bash
# Запуск в окружении fluidcalc:
#   1) программных и регрессионных тестов (tests/)         → docs/TEST_REPORT.txt
#   2) научной валидации по контрольным точкам (validation/) → validation/VALIDATION_REPORT.md
# Код возврата: 0 — всё прошло; 1 — есть FAIL/ERROR в любом из наборов.
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
UNIT_LOG="$TMPHOME/unit.log"
VAL_LOG="$TMPHOME/validation.log"

"$PY" -m unittest discover -s tests -v >"$UNIT_LOG" 2>&1
rc_unit=$?
"$PY" -m unittest discover -s validation -t . -v >"$VAL_LOG" 2>&1
rc_val_tests=$?
VAL_RUN="$("$PY" -m validation 2>&1)"
rc_val=$?

count() { grep -cE "$1" "$2"; }
summary() {
  echo "  passed:  $(count '\.\.\. ok$' "$1")"
  echo "  failed:  $(count '\.\.\. (FAIL|ERROR)$' "$1")"
  echo "  skipped: $(count '\.\.\. skipped' "$1")"
}

{
  echo "FluidCalc — журнал автоматических проверок"
  echo "Дата: $(date '+%F %T %Z')"
  "$PY" tools/check_env.py
  echo
  echo "================ 1. Программные и регрессионные тесты (tests/) ================"
  grep -v 'propagateSizeHints' "$UNIT_LOG"
  echo
  echo "================ 2. Научная валидация: тесты контрольных точек (validation/) ================"
  cat "$VAL_LOG"
  echo
  echo "================ 3. Научная валидация: python -m validation ================"
  echo "$VAL_RUN"
  echo
  echo "================ Сводка ================"
  echo "Программные тесты (tests/):"
  summary "$UNIT_LOG"
  echo "Тесты контрольных точек (validation/):"
  summary "$VAL_LOG"
  echo "Отчёт о научной валидации: validation/VALIDATION_REPORT.md"
  echo "Напоминание: программные тесты и пересчёт тех же уравнений не являются независимой"
  echo "экспериментальной проверкой; см. docs/VALIDATION_STATUS.md."
} | tee "$REPORT"
rm -rf "$TMPHOME"
if [ $rc_unit -ne 0 ] || [ $rc_val_tests -ne 0 ] || [ $rc_val -ne 0 ]; then
  echo "ИТОГ: ЕСТЬ ОШИБКИ (tests=$rc_unit, validation-tests=$rc_val_tests, validation=$rc_val)"
  exit 1
fi
echo "ИТОГ: все проверки пройдены"
exit 0
