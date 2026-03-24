# disable_usb_suspend.ps1
# Отключает USB Selective Suspend в текущей схеме электропитания Windows.
# Запуск: powershell -ExecutionPolicy Bypass -File scripts\disable_usb_suspend.ps1
#
# ВНИМАНИЕ: требуются права администратора.
# Для серверных/лабораторных ПК, которые работают 24/7.

Write-Host "=== Отключение USB Selective Suspend ===" -ForegroundColor Cyan

# Отключить USB selective suspend в текущей схеме питания
powercfg /SETACVALUEINDEX SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
powercfg /SETACTIVE SCHEME_CURRENT

Write-Host "USB Selective Suspend отключён в текущей схеме питания." -ForegroundColor Green
Write-Host ""
Write-Host "Дополнительно рекомендуется:" -ForegroundColor Yellow
Write-Host "  Device Manager → каждый USB Root Hub → Properties →"
Write-Host "  Power Management → убрать 'Allow the computer to turn off this device'"
Write-Host ""
Write-Host "Готово." -ForegroundColor Green
