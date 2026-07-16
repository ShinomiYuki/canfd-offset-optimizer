@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_canfd_offset_optimizer.ps1" %*
pause
