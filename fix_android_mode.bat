@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   PreSonus Revelator Android Fix (Windows Single -^> Multi)
echo   Zero AI / Zero API cost - Pure local Python script
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.9+ not found in PATH.
    echo Install Python from https://www.python.org/downloads/ and check "Add Python to PATH".
    pause
    exit /b 1
)

echo [Step 1/3] Running read-only diagnostic...
python scripts\revelator_mode.py diag
echo.

echo [Step 2/3] Closing Universal Control (if open) and disarming PaeDSPUSB.sys auto-revert trap...
taskkill /IM "Universal Control.exe" /F >nul 2>&1
python scripts\revelator_mode.py disarm --elevate --backup trap-backup.json
echo.

echo [Step 3/3] Switching Revelator to Android Multi Mode (PID_0D09)...
python scripts\revelator_mode.py switch multi
if %errorlevel% equ 0 (
    echo.
    echo [SUCCESS] Revelator is locked in Multi Mode (PID_0D09^).
    echo Unplug it from Windows and plug it straight into your Android phone!
    pause
    exit /b 0
)

if %errorlevel% equ 4 (
    echo.
    echo [INFO] First time switching on this USB port: Windows just created a fresh RestartDeviceRequest key.
    echo Disarming the newly created key and retrying switch automatically...
    python scripts\revelator_mode.py disarm --elevate --backup trap-backup.json
    python scripts\revelator_mode.py switch multi
    if %errorlevel% equ 0 (
        echo.
        echo [SUCCESS] Revelator is locked in Multi Mode (PID_0D09^).
        echo Unplug it from Windows and plug it straight into your Android phone!
        pause
        exit /b 0
    )
)

echo.
echo [ERROR] Switch did not complete. Check the output above or run:
echo   python scripts\revelator_mode.py diag
pause
exit /b 1
