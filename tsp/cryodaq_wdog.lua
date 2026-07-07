-- CryoDAQ dead-man watchdog for the Keithley 2604B — BOTH SMU channels.
--
-- Pure firmware backstop that sits BELOW the host SafetyManager. It carries
-- no regulation logic (the host owns P=const): its only job is to kill both
-- outputs if the host stops proving it is alive. Heartbeat mechanics are
-- salvaged from the old p_const.lua draft; all constant-power control was
-- dropped.
--
-- Host protocol (see keithley_2604b.py):
--   0. read    — print(cryodaq_wdog_tripped)  (latch from a PAST kill; read
--                BEFORE upload, which re-runs `tripped = 0` and wipes it)
--   1. upload  — send this script (defines the globals + functions below)
--   2. set     — CRYODAQ_WDOG_TIMEOUT_S = <seconds>   (deadline, default 5.0)
--   3. run     — cryodaq_wdog_run()                    (NON-blocking arm)
--   pet        — cryodaq_wdog_pet()                    (called on every poll)
--   disarm     — cryodaq_wdog_disarm()                 (clean release)
--
-- On a missed deadline BOTH outputs go OFF and the persistent global
-- cryodaq_wdog_tripped is latched to 1 so the host can read it back on the
-- next connect (SafetyManager reconcile also polls it mid-session).
--
-- COVERAGE (honest, current mechanism — TSP is single-threaded):
--   cryodaq_wdog_run() only ARMS (sets state + returns immediately); it does
--   NOT loop, so it never owns the command FIFO. The deadline is evaluated
--   inside cryodaq_wdog_pet(), which the host calls each poll. This kills
--   outputs on a STALL-THEN-RECOVER (a pet that arrives late) and latches for
--   the reconcile. It does NOT cover full host death: with no autonomous
--   execution, a host that stops petting entirely is never re-evaluated in
--   firmware. The true dead-man (an autonomous loop / trigger.timer-driven
--   mechanism that fires without host calls) is the single remaining
--   bench-verified upgrade. Until then, the host-side crash-recovery force-OFF
--   on the next connect (keithley_2604b.py) is the host-death backstop.

cryodaq_wdog_tripped = 0
cryodaq_wdog_last_pet = os.time()
cryodaq_wdog_active = 0

local function cryodaq_wdog_shutdown()
    smua.source.levelv = 0
    smua.source.output = smua.OUTPUT_OFF
    smub.source.levelv = 0
    smub.source.output = smub.OUTPUT_OFF
end

function cryodaq_wdog_pet()
    -- Deadline check rides the host poll loop (no autonomous firmware timer).
    local timeout = CRYODAQ_WDOG_TIMEOUT_S or 5.0
    if cryodaq_wdog_active == 1 and (os.time() - cryodaq_wdog_last_pet) > timeout then
        cryodaq_wdog_shutdown()
        cryodaq_wdog_tripped = 1
        cryodaq_wdog_active = 0
        return
    end
    cryodaq_wdog_last_pet = os.time()
end

function cryodaq_wdog_disarm()
    cryodaq_wdog_active = 0
end

function cryodaq_wdog_run()
    -- NON-blocking arm: set state and return immediately (do NOT loop — a loop
    -- would own the single-threaded command FIFO and starve every pet).
    cryodaq_wdog_tripped = 0
    cryodaq_wdog_last_pet = os.time()
    cryodaq_wdog_active = 1
end
