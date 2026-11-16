@echo off
:: Newly Windows Installer Script
:: ================================
:: This script helps users install Newly on Windows
:: It will download and install the pre-built version

@echo on

echo ╔════════════════════════════════════════════════════════════════╗
echo ║              Newly Windows Installer                          ║
echo ║   De Browser Die Werkt VOOR Jou                                ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.

:: Check if running as admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠️  This script requires administrator privileges
    echo.
    echo Please right-click and select "Run as Administrator"
    echo.
    pause
    exit /b 1
)

:: Check for curl
where curl >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠️  curl not found, trying with powershell...
    goto :USE_POWERSELL
)

:USE_CURL
:: Download the latest release
set REPO=igthubjnrcnrunnhuygfieucbhwihbrcy/Newly
set DOWNLOAD_URL=https://github.com/%REPO%/releases/latest/download/Newly-Setup-win32-x64.exe
set INSTALLER=newly-installer.exe

echo 📥 Downloading Newly installer...
echo From: %DOWNLOAD_URL%
echo.

curl -L -o %INSTALLER% %DOWNLOAD_URL%
if errorlevel 1 (
    echo ❌ Failed to download installer
    echo.
    echo Please download manually from:
    echo https://github.com/%REPO%/releases
    pause
    exit /b 1
)

goto :RUN_INSTALLER

:USE_POWERSELL
:: Use PowerShell to download
set REPO=igthubjnrcnrunnhuygfieucbhwihbrcy/Newly
set DOWNLOAD_URL=https://github.com/%REPO%/releases/latest/download/Newly-Setup-win32-x64.exe
set INSTALLER=newly-installer.exe

echo 📥 Downloading Newly installer with PowerShell...
echo From: %DOWNLOAD_URL%
echo.

powershell -Command "(New-Object Net.WebClient).DownloadFile('%DOWNLOAD_URL%', '%INSTALLER%')"
if errorlevel 1 (
    echo ❌ Failed to download installer
    echo.
    echo Please download manually from:
    echo https://github.com/%REPO%/releases
    pause
    exit /b 1
)

:RUN_INSTALLER
echo ✅ Installer downloaded: %INSTALLER%
echo.
echo 🚀 Starting installation...
echo.

start /wait %INSTALLER%

if exist %INSTALLER% (
    del %INSTALLER%
)

echo.
echo ✅ Newly has been installed!
echo.
echo You can now start Newly from:
echo   - Start Menu: Newly
echo   - Desktop: Newly shortcut
echo.
echo Enjoy your privacy-first browsing experience!
echo.
pause
