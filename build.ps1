# Compile BindHook.dll with TinyCC and generate the app icon.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Tools = Join-Path $Root "tools"
$TccDir = Join-Path $Tools "tcc"
$TccExe = Join-Path $TccDir "tcc.exe"
New-Item -ItemType Directory -Force -Path $Tools, (Join-Path $Root "native"), (Join-Path $Root "assets") | Out-Null

if (-not (Test-Path $TccExe)) {
    Write-Host "Downloading TinyCC 0.9.27 ..."
    $zip = Join-Path $Tools "tcc-0.9.27-win64-bin.zip"
    $hdr = Join-Path $Tools "winapi-full-for-0.9.27.zip"
    Invoke-WebRequest -Uri "https://download.savannah.gnu.org/releases/tinycc/tcc-0.9.27-win64-bin.zip" -OutFile $zip -UseBasicParsing
    Invoke-WebRequest -Uri "https://download.savannah.gnu.org/releases/tinycc/winapi-full-for-0.9.27.zip" -OutFile $hdr -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $Tools -Force
    Expand-Archive -Path $hdr -DestinationPath $Tools -Force
    $extracted = Get-ChildItem $Tools -Directory | Where-Object { $_.Name -like "tcc*" } | Select-Object -First 1
    if ($extracted -and $extracted.FullName -ne $TccDir) {
        if (Test-Path $TccDir) { Remove-Item $TccDir -Recurse -Force }
        Rename-Item $extracted.FullName $TccDir
    }
    $apiDir = Get-ChildItem $Tools -Directory | Where-Object { $_.Name -like "winapi*" } | Select-Object -First 1
    if ($apiDir) {
        Copy-Item -Path (Join-Path $apiDir.FullName "*") -Destination $TccDir -Recurse -Force
    }
}

if (-not (Test-Path $TccExe)) {
    throw "tcc.exe not found after download"
}

$src = Join-Path $Root "native\bindhook.c"
$dll = Join-Path $Root "native\BindHook.dll"
Write-Host "Compiling BindHook.dll ..."
& $TccExe -shared -o $dll $src -lkernel32 -lntdll
if ($LASTEXITCODE -ne 0) { throw "tcc failed with $LASTEXITCODE" }
Write-Host "OK  $dll"

Write-Host "Generating icon ..."
python -c @"
from PIL import Image, ImageDraw
import os
img = Image.new('RGBA', (256, 256), (15, 20, 25, 255))
d = ImageDraw.Draw(img)
d.rounded_rectangle((18, 18, 238, 238), 36, fill=(26, 35, 50, 255))
d.ellipse((48, 88, 118, 158), outline=(34, 197, 94, 255), width=10)
d.ellipse((138, 88, 208, 158), outline=(56, 189, 248, 255), width=10)
d.line((118, 123, 138, 123), fill=(59, 130, 246, 255), width=10)
d.rectangle((122, 70, 134, 176), fill=(59, 130, 246, 255))
path = os.path.join(r'$Root', 'assets', 'icon.ico')
img.save(path, sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
print('icon', path)
"@

Write-Host "Build finished."
