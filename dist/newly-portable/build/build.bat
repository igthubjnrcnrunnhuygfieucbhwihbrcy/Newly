@echo off
:: Newly Windows App Build Script
:: ================================
:: This script builds Newly as a Windows application
:: Requires: Node.js, npm, electron-builder
::
:: Usage: Double-click this file or run from command prompt

@echo on

echo ╔════════════════════════════════════════════════════════════════╗
echo ║         Newly Windows App Builder                              ║
echo ║   De Browser Die Werkt VOOR Jou                                ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.

:: Check if Node.js is installed
node --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Node.js is not installed!
    echo.
    echo Please install Node.js from: https://nodejs.org/
    echo (Recommended: Node.js 18 or higher)
    echo.
    pause
    exit /b 1
)

:: Check Node.js version
for /f "tokens=*" %%i in ('node --version') do set NODE_VERSION=%%i
set NODE_VERSION=%NODE_VERSION:~1%

for /f "tokens=1,2,3 delims=." %%a in ('echo %NODE_VERSION%') do (
    set MAJOR=%%a
    set MINOR=%%b
)

if %MAJOR% LSS 18 (
    echo ⚠️  Warning: Node.js version %NODE_VERSION% is below 18.0.0
    echo    Some features might not work correctly.
    echo.
    timeout /t 3 >nul
)

:: Install dependencies
echo 📦 Installing dependencies...
npm install
if errorlevel 1 (
    echo ❌ Failed to install dependencies
    pause
    exit /b 1
)
echo ✅ Dependencies installed

:: Generate ICO from SVG (if not exists)
if not exist "build\icon.ico" (
    echo 🎨 Generating icon from SVG...
    python build\generate_icon.py
    if errorlevel 1 (
        echo ⚠️  Could not generate ICO automatically
        echo    Using fallback method...
        :: Try to download a pre-made icon
        curl -o build\icon.ico -L "https://raw.githubusercontent.com/faviconcc/free-icons/master/png/512/rocket.png" 2>nul
        if not exist "build\icon.ico" (
            echo ⚠️  Please manually create build\icon.ico (256x256 pixels)
            echo    You can use: https://icoconvert.com/
            pause
        )
    )
)

:: Build the Windows app
echo 🏗️  Building Newly for Windows...
echo.
npm run build:win
if errorlevel 1 (
    echo ❌ Build failed
    echo.
    echo Troubleshooting:
    echo 1. Make sure you have admin rights
    echo 2. Check that Node.js is in your PATH
    echo 3. Try: npm install -g windows-build-tools
    echo.
    pause
    exit /b 1
)

echo.
echo ✅ Build complete!
echo.
echo Your Newly Windows app is ready in the "dist" folder:
echo.
for /d %%d in (dist\*) do (
    echo   📁 %%d
)
echo.
echo You can now:
echo  1. Run the installer (Newly Setup x.x.x.exe)
echo  2. Or use the portable version (Newly-win32-x64)
echo.
echo Press any key to open the dist folder...
pause >nul
explorer dist
