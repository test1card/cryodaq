-- CryoDAQ software late-pet watchdog for the Keithley 2604B — BOTH channels.
--
-- This script is deliberately limited to a documented, testable mechanism:
-- a host pet that arrives after its deadline turns both outputs OFF and latches
-- the trip. It has ZERO coverage for complete host death because no later TSP
-- command arrives to evaluate the deadline. It is not an autonomous safety
-- function and must not be represented as one.
--
-- Host protocol (see keithley_2604b.py):
--   0. read       — print(cryodaq_wdog_tripped) before upload resets the latch
--   1. upload     — send this script
--   2. verify     — read CRYODAQ_WDOG_VERSION and cryodaq_wdog_autonomous
--   3. set        — CRYODAQ_WDOG_TIMEOUT_S = <seconds>
--   4. activate   — cryodaq_wdog_run()
--   pet           — cryodaq_wdog_pet() on every host poll
--   disarm        — cryodaq_wdog_disarm()
--   acknowledge   — cryodaq_wdog_acknowledge(), only after host verified OFF
--
-- `cryodaq_wdog_autonomous` is the fail-closed host contract. It stays 0 in
-- this version. Required mode must therefore refuse this script; best_effort
-- may use only its explicitly degraded stall-then-recover behavior.
-- `cryodaq_wdog_timer_armed` is retained for readback compatibility and also
-- stays 0. There is no autonomous timer or output-action binding in this file.
--
-- Bump this integer on ANY globals/protocol change and update
-- _WDOG_SCRIPT_VERSION in keithley_2604b.py to match.
CRYODAQ_WDOG_VERSION = 3

cryodaq_wdog_autonomous = 0
cryodaq_wdog_timer_armed = 0
cryodaq_wdog_tripped = 0
cryodaq_wdog_last_pet = os.time()
cryodaq_wdog_active = 0

function cryodaq_wdog_shutdown()
    smua.source.levelv = 0
    smua.source.output = smua.OUTPUT_OFF
    smub.source.levelv = 0
    smub.source.output = smub.OUTPUT_OFF
    cryodaq_wdog_tripped = 1
    cryodaq_wdog_active = 0
end

function cryodaq_wdog_pet()
    -- os.time() is a documented 2600B API with one-second granularity. The
    -- host validates timeout to finite [1, 300] seconds. Strict `>` means an
    -- elapsed value exactly equal to timeout is not late until the next second.
    local timeout = CRYODAQ_WDOG_TIMEOUT_S or 5.0
    if cryodaq_wdog_active == 1 and (os.time() - cryodaq_wdog_last_pet) > timeout then
        cryodaq_wdog_shutdown()
        return
    end
    cryodaq_wdog_last_pet = os.time()
end

function cryodaq_wdog_disarm()
    cryodaq_wdog_active = 0
    cryodaq_wdog_timer_armed = 0
end

function cryodaq_wdog_acknowledge()
    -- Explicit operator-authorized latch consumption. The host calls this only
    -- after both outputs are independently readback-verified OFF and records
    -- the recovery reason in SafetyManager. Reactivate late-pet checking in the
    -- same TSP command so recovery cannot silently leave it disabled.
    cryodaq_wdog_tripped = 0
    cryodaq_wdog_last_pet = os.time()
    cryodaq_wdog_active = 1
    cryodaq_wdog_autonomous = 0
    cryodaq_wdog_timer_armed = 0
end

function cryodaq_wdog_run()
    -- Activate only the late-pet deadline check and return immediately.
    cryodaq_wdog_tripped = 0
    cryodaq_wdog_last_pet = os.time()
    cryodaq_wdog_active = 1
    cryodaq_wdog_autonomous = 0
    cryodaq_wdog_timer_armed = 0
end
