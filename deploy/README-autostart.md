# Autostart — what is installed, and the half that is not

Goal, in the operator's words: *"some autostart feature so if pc runs — cryodaq
runs as well."*

There are two halves, and **neither is active yet**. The unit exists and is
correct as far as it goes, but it is parked pending one production fix and one
decision from you. The second half — making the machine log itself in — needs
root and a security decision, and without it the first half cannot achieve the
goal at all.

## STATUS: PARKED AND DISABLED

**This unit is not installed and not enabled.** It was enabled on 2026-09-04 and
disabled the same day on review, which was correct: enabling a unit is a
deployment of machine configuration, and it happened during a watch cycle whose
standing rule is that the operator deploys.

As of 2026-09-07 the code-side conditions are met: the `--tray` correction
landed earlier, the modal-on-startup defect is fixed, and the qualification
condition turned out to describe a tree that no longer exists. What remains is
not a defect — it is one supervised start on the stand, and the operator's
decision to enable. See "Before this is enabled" below.

```
systemctl --user is-enabled cryodaq    # not installed
systemctl --user is-active  cryodaq    # inactive
```

## Half 1 — the unit, corrected but not enabled

`deploy/cryodaq.service`, intended to be symlinked into
`~/.config/systemd/user/` and enabled against `graphical-session.target`.

What it does:

* starts CryoDAQ whenever a graphical session begins;
* restarts it on failure, three attempts inside ten minutes, then stops and
  stays stopped so a human looks rather than letting it hammer the instruments;
* shuts down the way that is known to work — `SIGTERM` to the **launcher only**
  (`KillMode=mixed`), which runs the full `launcher_shutdown` round-trip, with
  two minutes before systemd resorts to force. A `SIGKILL` mid-shutdown is what
  latches a permanent HOLD, so the clean path is given room;
* logs to the journal: `journalctl --user -u cryodaq -f`.

### Correction to an earlier claim in this file

An earlier version of this document said a second launcher "tells the operator
one is running and exits 0", and called a lock collision harmless. **That was
misleading and the code had been read before it was written.** The launcher
opens a *modal* `QMessageBox.critical` and only exits when it is dismissed
(`launcher.py` ~8865). Under systemd, with nobody present to click it, a lock
collision does not exit — it hangs holding the dialog.

`exit 0` not triggering `Restart=on-failure` is true. It is beside the point if
the process never reaches the exit.

### Everyday use

```
systemctl --user status  cryodaq
systemctl --user stop    cryodaq     # clean shutdown, same as kill -TERM
systemctl --user start   cryodaq
systemctl --user disable cryodaq     # stop starting at login
journalctl --user -u cryodaq -f
```

`./start.sh` by hand still works exactly as before and is unaffected.

## Before this is enabled

1. **`--tray`, now used.** `ExecStart` originally invoked a bare `start.sh`.
   The launcher documents `--tray` as *"Только иконка в трее (без полного GUI).
   Полезно для автозагрузки"* — the autostart mode — and in that mode it also
   **defers first-run setup** rather than opening a modal wizard. Without it, a
   first-run condition blocks acquisition on a dialog. Corrected.

2. **Non-modal lock collision — FIXED 2026-09-07, awaiting review.** Both
   refusals on the startup path — a held launcher lock and a failed first-run
   recovery — now go through `_report_startup_refusal`, which always writes the
   log line and opens the modal only when a person is there to dismiss it
   (`attended=not args.tray`, the same flag the first-run wizard already
   respects). Regression: `tests/test_autostart_never_waits_for_a_click.py`,
   including a guard that fails if a bare `QMessageBox.critical` is ever added
   back to `main` — that is how this got disabled the first time.

3. **The qualification override — GONE, this condition is retired.** The claim
   that `start.sh` exports `CRYODAQ_LAB_QUALIFICATION_OVERRIDE=1` was true when
   written and is not any more: the gate was removed from the SafetyManager on
   2026-09-04 and pinned by `tests/core/test_qualification_gate_removed.py`.
   Verified 2026-09-07 — the variable appears **zero** times in `src/`, in
   `start.sh` and in this unit. There is no posture change left to decide here;
   this file was simply describing a version of the tree that no longer exists.

4. **An actual test on the stand.** The unit has never been started. Enabling it
   without one supervised start is guessing.

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

Written 2026-09-04, enabled the same day, and **disabled the same day on
review**. The unit was never started. The running stack was verified untouched
after both the enable and the disable (three PIDs, `dropped=0`). No root action
was taken and `/etc/gdm3/custom.conf` was not modified.
