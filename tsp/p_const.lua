-- Parameterized constant-power script for Keithley 2604B.
-- The host replaces {SMU} with "smua" or "smub" before upload.

{SMU}_watchdog_last_heartbeat = os.time()

function {SMU}_heartbeat()
    {SMU}_watchdog_last_heartbeat = os.time()
end

local function {SMU}_safe_shutdown()
    {SMU}.source.levelv = 0
    {SMU}.source.output = {SMU}.OUTPUT_OFF
end

local function {SMU}_init()
    local p_target = _G["{SMU}_P_target"]
    local v_compliance = _G["{SMU}_V_compliance"]
    local i_compliance = _G["{SMU}_I_compliance"]

    {SMU}.reset()
    {SMU}.source.func = {SMU}.OUTPUT_DCVOLTS
    {SMU}.source.autorangev = {SMU}.AUTORANGE_ON
    {SMU}.measure.autorangei = {SMU}.AUTORANGE_ON
    {SMU}.source.limitv = v_compliance
    {SMU}.source.limiti = i_compliance
    {SMU}.source.levelv = 0
    {SMU}.source.output = {SMU}.OUTPUT_ON

    while true do
        if (os.time() - {SMU}_watchdog_last_heartbeat) > 30 then
            break
        end

        local current, voltage = {SMU}.measure.iv()
        if math.abs(current) > 1e-9 then
            local resistance = voltage / current
            if resistance > 0 then
                local target_voltage = math.sqrt(p_target * resistance)
                if target_voltage > v_compliance then
                    target_voltage = v_compliance
                end
                if target_voltage < 0 then
                    target_voltage = 0
                end
                {SMU}.source.levelv = target_voltage
            end
        end
        delay(0.1)
    end
end

local ok, err = pcall({SMU}_init)
{SMU}_safe_shutdown()
if not ok then
    error(err)
end
