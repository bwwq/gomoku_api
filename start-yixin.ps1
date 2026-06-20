$appDir = Join-Path $PSScriptRoot 'Rapfi-YixinBoard'
$exe = Join-Path $appDir 'Yixin.exe'

Start-Process -FilePath $exe -WorkingDirectory $appDir
