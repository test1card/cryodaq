-- CryoDAQ dead-man watchdog for the Keithley 2604B — BOTH SMU channels.
--
-- Pure firmware backstop that sits BELOW the host SafetyManager. It carries
-- no regulation logic (the host owns P=const): its only job is to kill both
-- outputs if the host stops proving it is alive. Heartbeat mechanics are
-- salvaged from the old p_const.lua draft; all constant-power control was
-- dropped.
--
-- Host protocol (see keithley_2604b.py):
--   1. upload  — send this script (defines the globals + functions below)
--   2. set     — CRYODAQ_WDOG_TIMEOUT_S = <seconds>   (deadline, default 5.0)
--   3. run     — cryodaq_wdog_run()                    (enters the watch loop)
--   pet        — cryodaq_wdog_pet()                    (called on every poll)
--   disarm     — cryodaq_wdog_disarm()                 (clean release)
--
-- On a missed deadline BOTH outputs go OFF and the persistent global
-- cryodaq_wdog_tripped is latched to 1 so the host can read it back and
-- REFUSE to silently re-arm over a firmware kill (that is worse than having
-- no watchdog at all — see SafetyManager reconcile).
--
-- NOTE (bench gate / Codex D3): TSP is single-threaded and cryodaq_wdog_run()
-- blocks the command FIFO while it loops, so cryodaq_wdog_pet() cannot be
-- serviced from the same interface while the loop owns the interpreter. This
-- file is host PLUMBING only, inert behind a default-OFF flag; the go-live
-- run mechanism (trigger.timer-driven, or a non-blocking arming that leaves
-- the FIFO free for pets) is a separate bench-verified phase.

cryodaq_wdog_tripped = 0
cryodaq_wdog_last_pet = os.time()
cryodaq_wdog_active = 0

function cryodaq_wdog_pet()
    cryodaq_wdog_last_pet = os.time()
end

function cryodaq_wdog_disarm()
    cryodaq_wdog_active = 0
end

local function cryodaq_wdog_shutdown()
    smua.source.levelv = 0
    smua.source.output = smua.OUTPUT_OFF
    smub.source.levelv = 0
    smub.source.output = smub.OUTPUT_OFF
end

function cryodaq_wdog_run()
    local timeout = CRYODAQ_WDOG_TIMEOUT_S or 5.0
    cryodaq_wdog_tripped = 0
    cryodaq_wdog_last_pet = os.time()
    cryodaq_wdog_active = 1
    while cryodaq_wdog_active == 1 do
        if (os.time() - cryodaq_wdog_last_pet) > timeout then
            cryodaq_wdog_shutdown()
            cryodaq_wdog_tripped = 1
            cryodaq_wdog_active = 0
            break
        end
        delay(0.1)
    end
end
