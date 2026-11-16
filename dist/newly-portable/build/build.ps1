# Newly Windows App Build Script
# ================================
# This script builds Newly as a Windows application
# Requires: Node.js, npm, electron-builder
#
# Usage: .\build.ps1

Write-Host "`n╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║         Newly Windows App Builder                              ║" -ForegroundColor Cyan
Write-Host "║   De Browser Die Werkt VOOR Jou                                ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Check if Node.js is installed
try {
    $nodeVersion = node --version
    Write-Host "✅ Node.js version: $nodeVersion" -ForegroundColor Green
    
    # Parse version
    $versionParts = $nodeVersion -replace "v","" -split '\.'
    $major = [int]$versionParts[0]
    
    if ($major -lt 18) {
        Write-Host "⚠️  Warning: Node.js version is below 18.0.0" -ForegroundColor Yellow
        Write-Host "   Some features might not work correctly." -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    }
} catch {
    Write-Host "❌ Node.js is not installed!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Node.js from: https://nodejs.org/" -ForegroundColor Yellow
    Write-Host "(Recommended: Node.js 18 or higher)" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# Install dependencies
Write-Host "📦 Installing dependencies..." -ForegroundColor Cyan
try {
    npm install
    Write-Host "✅ Dependencies installed" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to install dependencies" -ForegroundColor Red
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}

# Generate ICO from SVG (if not exists)
if (-not (Test-Path "build\icon.ico")) {
    Write-Host "🎨 Generating icon from SVG..." -ForegroundColor Cyan
    try {
        python build\generate_icon.py
        if ($LASTEXITCODE -ne 0) {
            throw "Icon generation failed"
        }
        Write-Host "✅ Icon generated" -ForegroundColor Green
    } catch {
        Write-Host "⚠️  Could not generate ICO automatically" -ForegroundColor Yellow
        Write-Host "   Using fallback method..." -ForegroundColor Yellow
        
        # Try to use ImageMagick
        if (Get-Command magick -ErrorAction SilentlyContinue) {
            magick build\icon.svg -define icon:auto-resize=256,128,64,48,32,24,16 build\icon.ico
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ Icon generated with ImageMagick" -ForegroundColor Green
            }
        }
        
        if (-not (Test-Path "build\icon.ico")) {
            Write-Host "⚠️  Please manually create build\icon.ico (256x256 pixels)" -ForegroundColor Yellow
            Write-Host "   You can use: https://icoconvert.com/" -ForegroundColor Yellow
            Start-Sleep -Seconds 5
        }
    }
}

# Build the Windows app
Write-Host "🏗️  Building Newly for Windows..." -ForegroundColor Cyan
Write-Host ""
try {
    npm run build:win
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed"
    }
    Write-Host "`n✅ Build complete!" -ForegroundColor Green
    
    Write-Host "`nYour Newly Windows app is ready in the 'dist' folder:" -ForegroundColor Cyan
    Get-ChildItem -Path "dist" -Directory | ForEach-Object {
        Write-Host "   📁 $($_.FullName)" -ForegroundColor Yellow
    }
    
    Write-Host "`nYou can now:" -ForegroundColor Cyan
    Write-Host "  1. Run the installer (Newly Setup x.x.x.exe)" -ForegroundColor Yellow
    Write-Host "  2. Or use the portable version (Newly-win32-x64)" -ForegroundColor Yellow
    
    Write-Host "`nPress any key to open the dist folder..." -ForegroundColor Cyan
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    Invoke-Item "dist"
    
} catch {
    Write-Host "❌ Build failed" -ForegroundColor Red
    Write-Host "Error: $_" -ForegroundColor Red
    Write-Host "`nTroubleshooting:" -ForegroundColor Yellow
    Write-Host "  1. Make sure you have admin rights" -ForegroundColor Yellow
    Write-Host "  2. Check that Node.js is in your PATH" -ForegroundColor Yellow
    Write-Host "  3. Try: npm install -g windows-build-tools" -ForegroundColor Yellow
    Write-Host "  4. Make sure you have Visual Studio Build Tools installed" -ForegroundColor Yellow
    exit 1
}
