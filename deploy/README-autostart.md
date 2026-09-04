# Autostart — what is installed, and the half that is not

Goal, in the operator's words: *"some autostart feature so if pc runs — cryodaq
runs as well."*

There are two halves. **One is installed and needs nothing from you. The other
needs root and a decision, and without it the first half does not achieve the
goal.**

## Half 1 — installed and enabled

`deploy/cryodaq.service`, symlinked into `~/.config/systemd/user/` and enabled
against `graphical-session.target`.

```
systemctl --user is-enabled cryodaq    # enabled
systemctl --user is-active  cryodaq    # inactive — deliberately not started
```

It was **enabled but not started**, because the stack was already running when
it was installed. It takes effect at the next graphical login.

What it does:

* starts CryoDAQ whenever a graphical session begins;
* restarts it on failure, three attempts inside ten minutes, then stops and
  stays stopped so a human looks rather than letting it hammer the instruments;
* shuts down the way that is known to work — `SIGTERM` to the **launcher only**
  (`KillMode=mixed`), which runs the full `launcher_shutdown` round-trip, with
  two minutes before systemd resorts to force. A `SIGKILL` mid-shutdown is what
  latches a permanent HOLD, so the clean path is given room;
* logs to the journal: `journalctl --user -u cryodaq -f`.

Starting it while the stack is already up is harmless: a second launcher tells
the operator one is running and exits 0 (`launcher.py`, `.launcher.lock`), and
exit 0 does not trigger `Restart=on-failure`.

### Everyday use

```
systemctl --user status  cryodaq
systemctl --user stop    cryodaq     # clean shutdown, same as kill -TERM
systemctl --user start   cryodaq
systemctl --user disable cryodaq     # stop starting at login
journalctl --user -u cryodaq -f
```

`./start.sh` by hand still works exactly as before and is unaffected.

## Half 2 — NOT done: the machine does not log itself in

**This is the part that decides whether the goal is actually met.**

The launcher is a Qt application. It needs a real X display, so it cannot start
before somebody is logged in — there is nothing to draw on. Checked on this
machine, 2026-09-04:

```
/etc/gdm3/custom.conf   [daemon] section EMPTY — no AutomaticLoginEnable
loginctl show-user lab53 → Linger=no
```

So after a reboot or a power cut the machine boots to the **GDM login screen**
and stays there. The user unit never activates, because `graphical-session.target`
never activates. Acquisition does not resume until somebody physically logs in.

### Why lingering is not the answer

`loginctl enable-linger lab53` makes user units start at boot without a login.
It is the wrong tool here: it would start the unit with no graphical session and
no display, and the launcher would fail and burn its three restart attempts.

### What would actually close it

GDM autologin — three lines, as root:

```ini
# /etc/gdm3/custom.conf
[daemon]
AutomaticLoginEnable=true
AutomaticLogin=lab53
```

Then a reboot brings up the session, `graphical-session.target` activates, and
the unit starts CryoDAQ. That genuinely delivers "if pc runs, cryodaq runs".

**The cost, stated plainly so it is a decision and not a default:** anyone with
physical access who reboots the machine gets a logged-in desktop with no
password. For a locked lab room that is usually an acceptable trade for not
losing acquisition. It is not a trade software should make on the operator's
behalf, which is why it has not been made.

## What this does not protect against

* **The window before login.** Even with autologin, boot to session is tens of
  seconds. Nothing acquires during it.
* **A wedged machine.** A kernel panic that never reboots is not covered by
  anything here; that is a watchdog question.
* **The Keithley.** If the PC dies while the source is energised, the source
  keeps sourcing — the TSP watchdog is `best_effort` and script version 3 is
  explicitly non-autonomous. Autostart does not touch this.

## Provenance

Installed 2026-09-04. The unit was enabled, never started; the running stack was
verified untouched afterwards (three PIDs, `dropped=0`). No root action was
taken and `/etc/gdm3/custom.conf` was not modified.
