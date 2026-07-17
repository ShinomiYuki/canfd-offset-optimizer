@echo off
setlocal

set "REPO_ROOT=%~dp0.."
pushd "%REPO_ROOT%" >nul
set "PYTHONPATH=%REPO_ROOT%\src;%PYTHONPATH%"
set "PYTHONUTF8=1"

where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
) else (
    where py >nul 2>&1
    if errorlevel 1 (
        echo Python 3 was not found in PATH.
        echo Install Python 3.11 or newer, then try again.
        pause
        popd >nul
        exit /b 1
    )
    set "PYTHON_CMD=py -3"
)

%PYTHON_CMD% -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo GUI dependencies are not installed.
    echo Run: %PYTHON_CMD% -m pip install -e ".[gui]"
    pause
    popd >nul
    exit /b 1
)

%PYTHON_CMD% -m canfd_offset_optimizer.gui
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo GUI exited with code %EXIT_CODE%.
    pause
)

popd >nul
exit /b %EXIT_CODE%
