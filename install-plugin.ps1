# install-plugin.ps1 – Install the AI Video Agent CEP panel into Premiere Pro (Windows)
# Run from the Agent-1 directory:  powershell -ExecutionPolicy Bypass -File install-plugin.ps1

$ErrorActionPreference = "Stop"
try {
$BundleId   = "com.videoagent.plugin"
$PluginSrc  = Join-Path $PSScriptRoot "premiere-plugin"
$CepDir     = Join-Path $env:APPDATA "Adobe\CEP\extensions"
$Dest       = Join-Path $CepDir $BundleId

Write-Host "────────────────────────────────────────────────"
Write-Host "  AI Video Agent – Premiere Pro Plugin Installer"
Write-Host "────────────────────────────────────────────────"
Write-Host ""
Write-Host "Source : $PluginSrc"
Write-Host "Dest   : $Dest"
Write-Host ""

# ── Check source ──────────────────────────────────────────────────────────────
if (-not (Test-Path "$PluginSrc\CSXS\manifest.xml")) {
    Write-Error "ERROR: premiere-plugin\CSXS\manifest.xml not found. Run from the Agent-1 directory."
    exit 1
}
if (-not (Test-Path "$PluginSrc\CSInterface.js")) {
    Write-Error "ERROR: premiere-plugin\CSInterface.js not found."
    exit 1
}

# ── Warn if Premiere is running ───────────────────────────────────────────────
if (Get-Process "Adobe Premiere Pro" -ErrorAction SilentlyContinue) {
    Write-Warning "Premiere Pro is currently running. Restart it after installation."
    Write-Host ""
}

# ── Install ───────────────────────────────────────────────────────────────────
if (-not (Test-Path $CepDir)) {
    New-Item -ItemType Directory -Path $CepDir -Force | Out-Null
}

if (Test-Path $Dest) {
    Write-Host "Removing existing installation..."
    Remove-Item $Dest -Recurse -Force
}

Write-Host "Copying plugin files..."
Copy-Item $PluginSrc -Destination $Dest -Recurse

Write-Host "Done. Plugin installed to:"
Write-Host "  $Dest"
Write-Host ""

# ── Enable unsigned extensions ────────────────────────────────────────────────
Write-Host "Enabling unsigned CEP extensions (required for development)..."
foreach ($ver in 9,10,11,12) {
    $regPath = "HKCU:\Software\Adobe\CSXS.$ver"
    if (-not (Test-Path $regPath)) {
        New-Item -Path $regPath -Force | Out-Null
    }
    Set-ItemProperty -Path $regPath -Name "PlayerDebugMode" -Value "1" -Type String
}
Write-Host "  PlayerDebugMode set in registry for CSXS 9-12."
Write-Host ""

Write-Host "────────────────────────────────────────────────"
Write-Host "  Installation complete!"
Write-Host ""
Write-Host "  Next steps:"
Write-Host "  1. Start (or restart) Adobe Premiere Pro"
Write-Host "  2. Go to  Window -> Extensions -> AI Video Agent"
Write-Host "  3. Start the agent server:  python server.py"
Write-Host "  4. The panel status dot will turn green when connected"
Write-Host "────────────────────────────────────────────────"
} catch {
    Write-Host ""
    Write-Host "ERROR: $_" -ForegroundColor Red
    Write-Host ""
}
Read-Host "Press Enter to close"
