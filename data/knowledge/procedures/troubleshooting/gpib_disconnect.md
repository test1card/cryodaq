# GPIB Disconnect Troubleshooting

Восстановление связи с LakeShore 218S термометрами через GPIB-USB
adapter после потери heartbeat.

## Симптомы

- Каналы Т1-Т24 показывают stale data («data dropped» warnings в логах).
- Alarm batch на одном instrument'е (`LS218_1` / `LS218_2` / `LS218_3`).
- `SafetyManager` → FAULT через stale critical channel (Т11/Т12).
- В GUI: 0/16 либо partial counter в TopWatchBar.

## Diagnosis

1. Verify GPIB-USB-HS adapter подключён физически:
   ```bash
   lsusb | grep "National Instruments"
   ```
2. Check linux-gpib kernel module loaded:
   ```bash
   lsmod | grep gpib
   ```
3. Verify gpib0 device node:
   ```bash
   ls -l /dev/gpib0
   ```
4. Check user в группе gpib:
   ```bash
   groups | grep gpib
   ```

## Recovery

1. Restart engine с force flag:
   ```bash
   cryodaq-engine --force
   ```
   (kills lock, restarts cleanly. SafetyManager стартует в `SAFE_OFF`,
   operator должен `acknowledge_fault` вручную.)

2. Если persists — physically reseat GPIB connectors на adapter и
   instruments. Screw-lock каждый коннектор после восстановления —
   push-only contact накапливает оксид и periodic dropout reappears.

3. Если still fails — kernel module reload:
   ```bash
   sudo modprobe -r ni_usb_gpib
   sudo modprobe ni_usb_gpib
   ```

4. Если kernel module не загружается — проверить dmesg:
   ```bash
   dmesg | tail -50 | grep -i gpib
   ```

## Prevention

- GPIB cables должны быть screw-locked (не push-only).
- Avoid hot-plugging USB adapter when engine running.
- USB hub between adapter и host увеличивает probability dropout —
  prefer direct USB port на mainboard.
- На дашборде включить sensor diagnostics с alert на stale Т11/Т12
  (default since v0.55.5).
