@echo off
:: Newly Portable Browser - Start Script
:: =======================================
:: This script starts the Newly browser in portable mode

@echo on

echo ╔════════════════════════════════════════════════════════════════╗
echo ║              Newly Portable Browser                           ║
echo ║   De Browser Die Werkt VOOR Jou                                ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.

:: Check if Node.js is installed
node --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Node.js is not installed!
    echo.
    echo Newly requires Node.js to run.
    echo.
    echo Please install Node.js 18 or higher from:
    echo   https://nodejs.org/
    echo.
    echo After installation, run this script again.
    echo.
    pause
    exit /b 1
)

:: Check Node.js version
for /f "tokens=*" %%i in ('node --version') do set NODE_VERSION=%%i
set NODE_VERSION=%NODE_VERSION:~1%

for /f "tokens=1,2,3 delims=." %%a in ('echo %NODE_VERSION%') do (
    set MAJOR=%%a
)

if %MAJOR% LSS 18 (
    echo ⚠️  Warning: Node.js version %NODE_VERSION% is below 18.0.0
    echo    Some features might not work correctly.
    echo.
    timeout /t 3 >nul
)

:: Install dependencies if not already installed
if not exist "node_modules" (
    echo 📦 Installing dependencies...
    npm install --production
    if errorlevel 1 (
        echo ❌ Failed to install dependencies
        echo.
        echo Please make sure you have internet connection and try again.
        pause
        exit /b 1
    )
    echo ✅ Dependencies installed
)

:: Start Newly
echo 🚀 Starting Newly...
echo.
echo Press Ctrl+C to exit
start node main.js

exit /b 0
