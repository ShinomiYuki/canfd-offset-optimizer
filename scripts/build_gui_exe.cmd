@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "REPO_ROOT=%~dp0.."
pushd "%REPO_ROOT%" >nul

for /f "usebackq delims=" %%V in (`python -c "import PyInstaller; print(PyInstaller.__version__)" 2^>nul`) do set "PYINSTALLER_VERSION=%%V"
if not "%PYINSTALLER_VERSION%"=="6.21.0" (
    echo PyInstaller 6.21.0 is required in the build environment.
    echo Current version: %PYINSTALLER_VERSION%
    echo Run: python -m pip install -e ".[gui,packaging]"
    popd >nul
    exit /b 1
)

for /f "usebackq delims=" %%A in (`python -c "import struct; print(struct.calcsize('P') * 8)"`) do set "PYTHON_BITS=%%A"
if not "%PYTHON_BITS%"=="64" (
    echo A 64-bit Python build environment is required.
    popd >nul
    exit /b 1
)

for /f "usebackq delims=" %%V in (`python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"`) do set "APP_VERSION=%%V"
if not defined APP_VERSION (
    echo Failed to read project version from pyproject.toml.
    popd >nul
    exit /b 1
)

set "PYI_WORK=build\pyinstaller-work"
set "PYI_DIST=build\pyinstaller-dist"
set "PACKAGE_NAME=CANFDOffsetOptimizer-%APP_VERSION%-win-x64"
set "PACKAGE_DIR=release\%PACKAGE_NAME%"
set "ZIP_PATH=release\%PACKAGE_NAME%.zip"

if exist "%PYI_WORK%" rmdir /s /q "%PYI_WORK%"
if exist "%PYI_DIST%" rmdir /s /q "%PYI_DIST%"
if exist "%PACKAGE_DIR%" rmdir /s /q "%PACKAGE_DIR%"
if exist "%ZIP_PATH%" del /q "%ZIP_PATH%"
if exist "%ZIP_PATH%.sha256" del /q "%ZIP_PATH%.sha256"

python -m PyInstaller --noconfirm --clean --workpath "%PYI_WORK%" --distpath "%PYI_DIST%" "packaging\CANFDOffsetOptimizer.spec"
if errorlevel 1 goto :failed

if not exist "release" mkdir "release"
robocopy "%PYI_DIST%\CANFDOffsetOptimizer" "%PACKAGE_DIR%" /E >nul
if errorlevel 8 goto :failed

copy /y "LICENSE" "%PACKAGE_DIR%\LICENSE" >nul
copy /y "packaging\README_运行说明.txt" "%PACKAGE_DIR%\README_运行说明.txt" >nul

pushd "%TEMP%" >nul
start "" /wait "%REPO_ROOT%\%PACKAGE_DIR%\CANFDOffsetOptimizer.exe" --portable-smoke-test
set "SMOKE_EXIT=%ERRORLEVEL%"
popd >nul
if not "%SMOKE_EXIT%"=="0" goto :failed
if not exist "%PACKAGE_DIR%\user_input" goto :failed
if not exist "%PACKAGE_DIR%\user_output" goto :failed

powershell -NoProfile -Command "$ErrorActionPreference='Stop'; for($i=1; $i -le 5; $i++){ try { Compress-Archive -LiteralPath '%PACKAGE_DIR%' -DestinationPath '%ZIP_PATH%' -CompressionLevel Optimal -Force; exit 0 } catch { if(Test-Path -LiteralPath '%ZIP_PATH%'){ Remove-Item -LiteralPath '%ZIP_PATH%' -Force }; if($i -eq 5){ throw }; Start-Sleep -Seconds 2 } }"
if errorlevel 1 goto :failed
if not exist "%ZIP_PATH%" goto :failed

powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $p='%ZIP_PATH%'; $h=(Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash; Set-Content -LiteralPath ($p + '.sha256') -Value ($h + '  ' + [IO.Path]::GetFileName($p)) -Encoding ascii"
if errorlevel 1 goto :failed

echo.
echo Portable GUI package created:
echo   %PACKAGE_DIR%
echo   %ZIP_PATH%
echo   %ZIP_PATH%.sha256
popd >nul
exit /b 0

:failed
echo.
echo GUI packaging failed.
popd >nul
exit /b 1
