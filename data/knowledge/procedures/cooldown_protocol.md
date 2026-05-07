# Протокол захолаживания криостата

Стандартный workflow запуска криогенного эксперимента на стенде CryoDAQ.

## Подготовка

1. Проверить вакуум: давление < 1e-5 mbar (видно в TopWatchBar).
2. Verify термометры подключены и report'ят (16/16 норма в статус-баре).
3. Verify заполнение жидким азотом — Т5 «Экран 77К» должен быть на температуре азота (≈77 K).
4. Открыть GUI: `Эксперимент` → создать новый.

## Запуск

1. Включить компрессор (manual operator action).
2. В GUI: `Эксперимент` → перейти в фазу «Захолаживание».
3. Контроль захолаживания auto-arm активируется при переходе в фазу
   (см. `CooldownAlarm` в `alarms_v3.yaml`, начиная с v0.55.4 — manual
   arm/disarm UI убран в v0.55.6.1).

## Мониторинг

- **Т11 «Теплообменник 1»** — 1st stage GM-cooler (positionally fixed).
- **Т12 «Теплообменник 2»** — 2nd stage GM-cooler (positionally fixed).
- `SteadyStatePredictor` показывает ETA в Analytics view (measurement
  phase widget с v0.55.6.1 — `temperature_steady_state` headline).
- Cold rate matching через ML predictor (`cooldown_v5/*` training data).

## Завершение фазы захолаживания

Эксперимент переходит в фазу «Измерение» автоматически когда:
- Т11/Т12 выходят на стационар (settle ≥ 30%).
- σ < threshold per F-X channel taxonomy alarm bands.

## Связанные процедуры

- `emergency_shutdown.md` — при сбое.
- `troubleshooting/gpib_disconnect.md` — при потере связи с термометрами.
