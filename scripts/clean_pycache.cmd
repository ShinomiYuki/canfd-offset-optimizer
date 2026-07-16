@echo off
setlocal

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"

for /d /r "%PROJECT_ROOT%" %%D in (__pycache__) do (
    if exist "%%~fD" rd /s /q "%%~fD"
)

echo Removed all __pycache__ directories under "%PROJECT_ROOT%".
endlocal
