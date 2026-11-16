@echo off
:: Newly Portable Installer
:: =========================
:: This script downloads and extracts Newly Portable for Windows

@echo on

echo ╔════════════════════════════════════════════════════════════════╗
echo ║         Newly Portable Windows Installer                     ║
echo ║   De Browser Die Werkt VOOR Jou                                ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.

:: Set variables
set INSTALL_DIR=%~dp0newly-portable
set ZIP_FILE=%~dp0newly-portable.zip

echo 📁 Installing to: %INSTALL_DIR%
echo.

:: Check if already installed
if exist "%INSTALL_DIR%\start-newly.bat" (
    echo ⚠️  Newly Portable is already installed in this directory!
    echo.
    echo To start Newly, run: start-newly.bat
    echo.
    pause
    exit /b 0
)

:: Check for curl
where curl >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠️  curl not found, trying with powershell...
    goto :USE_POWERSELL
)

:USE_CURL
:: Download using curl
if not exist "%ZIP_FILE%" (
    echo 📥 Downloading Newly Portable...
    curl -L -o "%ZIP_FILE%" https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly/raw/main/dist/newly-portable.zip
    if errorlevel 1 (
        echo ❌ Failed to download
        goto :ERROR
    )
) else (
    echo ✅ Using existing ZIP file
)

goto :EXTRACT

:USE_POWERSELL
:: Download using PowerShell
if not exist "%ZIP_FILE%" (
    echo 📥 Downloading Newly Portable with PowerShell...
    powershell -Command "(New-Object Net.WebClient).DownloadFile('https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly/raw/main/dist/newly-portable.zip', '%ZIP_FILE%')"
    if errorlevel 1 (
        echo ❌ Failed to download
        goto :ERROR
    )
) else (
    echo ✅ Using existing ZIP file
)

:EXTRACT
:: Extract ZIP file
echo 📦 Extracting files...
if exist "%INSTALL_DIR%" (
    rmdir /s /q "%INSTALL_DIR%"
)

:: Use PowerShell to extract (works on all Windows versions)
powershell -Command "Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%INSTALL_DIR%' -Force"
if errorlevel 1 (
    echo ❌ Failed to extract ZIP file
    goto :ERROR
)

echo ✅ Files extracted

:: Create desktop shortcut
set SCRIPT="%INSTALL_DIR%\start-newly.bat"
set SHORTCUT=%PUBLIC%\Desktop\Newly.lnk

echo 🔗 Creating desktop shortcut...
powershell -Command "$WshShell = New-Object -comObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%SHORTCUT%'); $Shortcut.TargetPath = '%SCRIPT%'; $Shortcut.WorkingDirectory = '%INSTALL_DIR%'; $Shortcut.IconLocation = '%INSTALL_DIR%\Newly.exe,0'; $Shortcut.Save()"

:: Create start menu shortcut
set STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Newly.lnk
powershell -Command "$WshShell = New-Object -comObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%STARTMENU%'); $Shortcut.TargetPath = '%SCRIPT%'; $Shortcut.WorkingDirectory = '%INSTALL_DIR%'; $Shortcut.IconLocation = '%INSTALL_DIR%\Newly.exe,0'; $Shortcut.Save()"

echo ✅ Shortcuts created

echo.
echo ✅ Newly Portable is installed!
echo.
echo Installation directory: %INSTALL_DIR%
echo.
echo To start Newly:
echo   - Double-click the desktop shortcut
echo   - Or run: %INSTALL_DIR%\start-newly.bat
echo.
echo Note: You need Node.js 18+ installed to run Newly.
echo       Download from: https://nodejs.org/
echo.
pause
goto :EOF

:ERROR
echo.
echo ❌ Installation failed
if exist "%ZIP_FILE%" (
    echo.
    echo You can try manual installation:
    echo 1. Download newly-portable.zip from GitHub
    echo 2. Extract to any folder
    echo 3. Run start-newly.bat
    echo.
    echo GitHub URL:
    echo https://github.com/igthubjnrcnrunnhuygfieucbhwihbrcy/Newly/raw/main/dist/newly-portable.zip
)
pause
exit /b 1
