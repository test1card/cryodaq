#!/bin/bash
# Desktop entry point: start CryoDAQ from an icon, with no terminal.
#
# A terminal launch shows the operator what went wrong. An icon launch shows
# nothing, so this wrapper takes on the two jobs the terminal was doing:
#
#   * refuse to start a SECOND stack. Two engines would open the same SQLite
#     database and the same instruments; the second one's stop() removes the
#     first one's WAL. A double click must not be able to do that.
#   * make a failed start VISIBLE. Without this, a start that dies in three
#     seconds looks exactly like a start that worked, and the operator finds
#     out hours later that nothing was recording.

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1

LOG_DIR="$REPO/logs"
mkdir -p "$LOG_DIR"
CONSOLE_LOG="$LOG_DIR/launcher_console.log"

notify() { command -v notify-send >/dev/null && notify-send -i "$REPO/docs/assets/cryodaq-icon.png" "CryoDAQ" "$1"; }
fail() {
    # zenity blocks until dismissed, so the operator cannot miss it.
    if command -v zenity >/dev/null; then
        zenity --error --width=560 --title="CryoDAQ — запуск не удался" --text="$1" 2>/dev/null
    else
        notify "$1"
    fi
    exit 1
}

# --- already running? -------------------------------------------------------
if pgrep -f "cryodaq\.launcher" >/dev/null 2>&1; then
    notify "CryoDAQ уже запущен — окно должно быть открыто, второй экземпляр не запускается."
    exit 0
fi

# A leftover engine without its launcher means the previous stack did not exit
# cleanly. Starting a second engine over it is exactly the case that cost us a
# live database, so this stops and tells the operator instead of guessing.
if pgrep -f "cryodaq\.engine" >/dev/null 2>&1; then
    fail "Обнаружен engine без launcher — предыдущий запуск завершился некорректно.\n\nCryoDAQ не запущен, чтобы не открыть вторую копию базы данных.\n\nЗакройте оставшийся процесс и повторите запуск:\n    pkill -f cryodaq.engine"
fi

if [ ! -x "$REPO/start.sh" ]; then
    fail "Не найден исполняемый $REPO/start.sh"
fi

# --- start ------------------------------------------------------------------
notify "Запуск CryoDAQ…"
: > "$CONSOLE_LOG"
setsid "$REPO/start.sh" >>"$CONSOLE_LOG" 2>&1 &

# --- verify it actually came up ---------------------------------------------
# The engine connects instruments before it settles, so allow a real budget
# rather than declaring success the moment the process exists.
for _ in $(seq 1 40); do
    sleep 1
    if pgrep -f "cryodaq\.engine" >/dev/null 2>&1; then
        notify "CryoDAQ запущен."
        exit 0
    fi
    if ! pgrep -f "cryodaq\.launcher" >/dev/null 2>&1; then
        break   # launcher died: report immediately instead of waiting out the budget
    fi
done

TAIL="$(tail -n 15 "$CONSOLE_LOG" 2>/dev/null)"
fail "CryoDAQ не запустился.\n\nПоследние строки $CONSOLE_LOG:\n\n$TAIL"
