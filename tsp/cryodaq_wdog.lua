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
--   2. verify  — print(CRYODAQ_WDOG_VERSION)  (host refuses to arm on mismatch)
--   3. set     — CRYODAQ_WDOG_TIMEOUT_S = <seconds>   (deadline, default 5.0)
--   4. run     — cryodaq_wdog_run()                    (NON-blocking arm)
--   5. confirm — print(cryodaq_wdog_active) == 1 and print(cryodaq_wdog_tripped) == 0
--   pet        — cryodaq_wdog_pet()                    (called on every poll)
--   disarm     — cryodaq_wdog_disarm()                 (clean release)
--
-- On a missed deadline BOTH outputs go OFF and the persistent global
-- cryodaq_wdog_tripped is latched to 1 so the host can read it back on the
-- next connect (SafetyManager reconcile also polls it mid-session).
--
-- VERSION STAMP: CRYODAQ_WDOG_VERSION is read back by the host immediately
-- after upload. The script is re-uploaded from repo tsp/ on every arm, so a
-- truncated or stale upload would otherwise pass the fire-and-forget writes
-- silently. Firmware gets no CI — this stamp is its integrity check. BUMP this
-- integer on ANY change to the globals/protocol below and update
-- _WDOG_SCRIPT_VERSION in keithley_2604b.py to match.
CRYODAQ_WDOG_VERSION = 2

-- COVERAGE (honest — TSP is single-threaded):
--   The autonomous trigger.timer[1] dead-man below is THE SINGLE REMAINING
--   BENCH-VERIFIED UPGRADE: it is meant to fire with NO host alive (a hardware
--   timer, independent of the command FIFO, kills both outputs on expiry). Its
--   timer→output-off action binding is firmware-timing dependent and CANNOT be
--   proven without a Keithley on the bench — it is armed defensively (pcall) and
--   reported via cryodaq_wdog_timer_armed so a bench run can confirm it took.
--   Until it is bench-verified, cryodaq_wdog_pet() ALSO runs the software
--   deadline check, which kills outputs on a STALL-THEN-RECOVER (a pet that
--   arrives late) and latches for the reconcile. The pet-based check does NOT
--   cover full host death (a host that stops petting entirely is never
--   re-evaluated by pet); that is exactly what the autonomous timer is for.
--   Until the timer path is bench-verified, the host-side crash-recovery
--   force-OFF on the next connect (keithley_2604b.py) is the host-death backstop.
--   NEVER claim the autonomous path verified from host-side tests alone.

cryodaq_wdog_tripped = 0
cryodaq_wdog_last_pet = os.time()
cryodaq_wdog_active = 0
cryodaq_wdog_timer_armed = 0

local function cryodaq_wdog_shutdown()
    smua.source.levelv = 0
    smua.source.output = smua.OUTPUT_OFF
    smub.source.levelv = 0
    smub.source.output = smub.OUTPUT_OFF
    cryodaq_wdog_tripped = 1
    cryodaq_wdog_active = 0
end

-- AUTONOMOUS DEAD-MAN (trigger.timer[1]) — AWAITING BENCH VERIFICATION.
-- trigger.timer[1] runs in hardware, independent of the host command FIFO, so
-- it fires even when the host is dead and never calls pet(). run() arms it for
-- one shot at CRYODAQ_WDOG_TIMEOUT_S; every pet() re-arms it (restart before
-- expiry). On expiry with no re-arm, the bound source-idle action drops both
-- outputs. The stimulus routing / coexistence with host-side DC sourcing is
-- the firmware-timing detail that must be proven on a real 2604B.
local function cryodaq_wdog_arm_timer()
    trigger.timer[1].reset()
    trigger.timer[1].delay = CRYODAQ_WDOG_TIMEOUT_S or 5.0
    trigger.timer[1].count = 1
    trigger.timer[1].passthrough = false
    -- On expiry drive both SMUs to their output-off idle state (bench-verify
    -- the trigger-model action coexists with the host's DC P=const source).
    smua.trigger.source.action = smua.SOURCE_IDLE
    smub.trigger.source.action = smub.SOURCE_IDLE
    trigger.timer[1].stimulus = 0
    trigger.timer[1].enable = 1
end

local function cryodaq_wdog_kick_timer()
    -- Re-arm the hardware timer (host proved alive) — restart reloads the delay.
    trigger.timer[1].enable = 0
    trigger.timer[1].enable = 1
end

function cryodaq_wdog_pet()
    -- (1) Re-arm the autonomous hardware timer if it armed on run().
    if cryodaq_wdog_timer_armed == 1 then
        pcall(cryodaq_wdog_kick_timer)
    end
    -- (2) Software deadline check rides the host poll loop — the working
    -- backstop until the autonomous timer path is bench-verified. Kills on a
    -- STALL-THEN-RECOVER (a pet that arrives late) and latches for reconcile.
    local timeout = CRYODAQ_WDOG_TIMEOUT_S or 5.0
    if cryodaq_wdog_active == 1 and (os.time() - cryodaq_wdog_last_pet) > timeout then
        cryodaq_wdog_shutdown()
        return
    end
    cryodaq_wdog_last_pet = os.time()
end

function cryodaq_wdog_disarm()
    cryodaq_wdog_active = 0
    if cryodaq_wdog_timer_armed == 1 then
        pcall(function() trigger.timer[1].enable = 0 end)
        cryodaq_wdog_timer_armed = 0
    end
end

function cryodaq_wdog_run()
    -- NON-blocking arm: set state, arm the hardware timer, return immediately.
    -- Do NOT loop — a loop would own the single-threaded command FIFO and
    -- starve every pet, then spurious-trip.
    cryodaq_wdog_tripped = 0
    cryodaq_wdog_last_pet = os.time()
    cryodaq_wdog_active = 1
    -- Arm the autonomous timer defensively: if the firmware rejects any call
    -- (bench-unverified trigger-model routing), degrade to the pet-based
    -- deadline check rather than failing the whole arm. cryodaq_wdog_timer_armed
    -- reports whether the hardware timer took (for the bench trip-test).
    cryodaq_wdog_timer_armed = 0
    if pcall(cryodaq_wdog_arm_timer) then
        cryodaq_wdog_timer_armed = 1
    end
end
