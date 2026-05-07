# Аварийное отключение

Безопасный shutdown стенда CryoDAQ при срабатывании автоматики или
ручном действии оператора.

## Triggers (auto-fault)

- Превышение температурных пределов (interlock в `interlocks.yaml`).
- Утечка вакуума (pressure spike детект, `vacuum_loss_cold` в
  `alarms_v3.yaml`).
- Heartbeat timeout с критическим прибором (LakeShore, Keithley,
  Thyracont).
- dT/dt > 5 K/min (rate limit в `safety.yaml`).
- Stale data на critical channel > `stale_timeout_s`.

## Triggers (manual)

- Кнопка EMERGENCY OFF в GUI (Keithley overlay → «АВАР. ОТКЛ. A+B»).
- Команда `experiment.emergency_off` через Telegram (`/shutdown`).

## Действия системы

1. `SafetyManager` → `FAULT_LATCHED` state.
2. Источник тока (Keithley) → OFF (`output_off` на оба канала).
3. Логирование в `operator_log` + alarm history.
4. Notification через Telegram (если configured) — one-shot, не
   повторяется (политика v0.55.5).
5. GUI показывает FAULT banner (красный) в bottom status bar.

## Восстановление

1. Operator явно `acknowledge_fault`, указывая причину
   (`require_reason: true` в `safety.yaml`).
2. Cooldown 60 секунд перед re-arm (`cooldown_before_rearm_s`).
3. Precondition re-check — все critical channels должны быть live
   (heartbeat OK + value в physical band).
4. `SafetyManager` → `SAFE_OFF`, ready для повторного `RUN_PERMITTED`.

## Что NOT делается

- Compressor НЕ выключается автоматически (manual action — может
  потребоваться поддерживать ступень холодной во время диагностики
  fault).
- Жидкий азот НЕ дренируется (passive boil-off).
- Эксперимент НЕ финализируется автоматически — operator решает
  finalize / abort / continue после восстановления.
