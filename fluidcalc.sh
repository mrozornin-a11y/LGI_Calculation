#!/usr/bin/env bash
# Запуск FluidCalc в conda-окружении «fluidcalc» (Miniforge). Системный Python не используется.
# Переопределения: FLUIDCALC_CONDA=/путь/к/miniforge3  FLUIDCALC_ENV=имя_окружения
set -u
APP_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
CONDA_ROOT="${FLUIDCALC_CONDA:-$HOME/miniforge3}"
ENV_NAME="${FLUIDCALC_ENV:-fluidcalc}"
LOG_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/fluidcalc/logs"
mkdir -p "$LOG_DIR"
LAUNCH_LOG="$LOG_DIR/launcher.log"

fail() {
    echo "FluidCalc: $1" >&2
    echo "$(date '+%F %T') ОШИБКА: $1" >> "$LAUNCH_LOG"
    if command -v kdialog >/dev/null 2>&1; then
        kdialog --title "FluidCalc" --error "$1"
    elif command -v zenity >/dev/null 2>&1; then
        zenity --error --title="FluidCalc" --text="$1"
    elif command -v xmessage >/dev/null 2>&1; then
        xmessage -center "FluidCalc: $1"
    fi
    exit 1
}

# Активация окружения (настраивает переменные пакетов conda-forge); только для этого процесса.
if [ -f "$CONDA_ROOT/etc/profile.d/conda.sh" ]; then
    # shellcheck disable=SC1091
    source "$CONDA_ROOT/etc/profile.d/conda.sh"
    conda activate "$ENV_NAME" 2>>"$LAUNCH_LOG" || fail "Не удалось активировать окружение «$ENV_NAME» в $CONDA_ROOT"
    PY="$(command -v python)"
else
    PY="$CONDA_ROOT/envs/$ENV_NAME/bin/python"
fi
[ -x "$PY" ] || fail "Не найден Python окружения «$ENV_NAME» ($CONDA_ROOT). См. README.md, раздел «Установка»."

# Работа строго без сети: matplotlib хранит кэш шрифтов локально.
export MPLBACKEND=QtAgg
cd "$APP_DIR" || fail "Нет доступа к каталогу программы $APP_DIR"
echo "$(date '+%F %T') запуск: $PY -m fluid_app $*" >> "$LAUNCH_LOG"
"$PY" -m fluid_app "$@" 2>>"$LAUNCH_LOG"
rc=$?
[ $rc -eq 0 ] || fail "Программа завершилась с ошибкой (код $rc). Подробности: $LAUNCH_LOG"
