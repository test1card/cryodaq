# Desktop launcher

`tools/cryodaq-desktop-launch.sh` starts the stack from a GNOME icon with no
terminal. Installed as `~/.local/share/applications/cryodaq.desktop`, with a
trusted copy on the desktop.

Install (or reinstall after moving the repo):

    mkdir -p ~/.local/share/icons/hicolor/256x256/apps
    cp docs/assets/cryodaq-icon.png ~/.local/share/icons/hicolor/256x256/apps/cryodaq.png
    sed "s|@REPO@|$PWD|" tools/cryodaq.desktop.in > ~/.local/share/applications/cryodaq.desktop
    chmod +x ~/.local/share/applications/cryodaq.desktop
    cp ~/.local/share/applications/cryodaq.desktop "$(xdg-user-dir DESKTOP)/cryodaq.desktop"
    chmod +x "$(xdg-user-dir DESKTOP)/cryodaq.desktop"
    gio set "$(xdg-user-dir DESKTOP)/cryodaq.desktop" metadata::trusted true
    update-desktop-database ~/.local/share/applications

## Why the wrapper is not just `Exec=start.sh`

A terminal launch shows the operator what went wrong; an icon launch shows
nothing. The wrapper takes over the two jobs the terminal was doing.

**It refuses to start a second stack.** Two engines would open the same SQLite
database and the same instruments, and the second one's `stop()` removes the
first one's WAL — the exact accident that cost this stand about five minutes of
live persistence on 2026-09-01. A double click must not be able to do that. A
leftover engine with no launcher is reported rather than started over, because
that state means the previous stack did not exit cleanly and only an operator
can say why.

**It makes a failed start visible.** Without it, a start that dies after three
seconds looks exactly like one that worked, and the operator finds out hours
later that nothing was recording. The wrapper waits for the engine process to
appear (40 s budget, since the engine connects instruments before it settles),
returns early if the launcher dies first, and shows a blocking `zenity` dialog
with the tail of `logs/launcher_console.log` when it does not come up.
