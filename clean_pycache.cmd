@echo off
setlocal

for /d /r "%~dp0" %%D in (__pycache__) do (
    if exist "%%~fD" rd /s /q "%%~fD"
)

echo Removed all __pycache__ directories under "%~dp0".
endlocal
