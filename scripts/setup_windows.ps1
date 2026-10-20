$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path '.venv\Scripts\python.exe')) {
  Write-Error '缺少项目 .venv。请先按本机依赖管理方式创建环境；脚本不会自动安装大型软件或平台服务。'
}
# Compile project sources only; do not recursively traverse dependencies, user
# data, logs or historical report copies of third-party code.
$sources = @(Get-ChildItem -LiteralPath . -Filter '*.py' -File | ForEach-Object FullName)
$sources += @(Get-ChildItem -LiteralPath scripts,deploy -Filter '*.py' -File | ForEach-Object FullName)
& '.venv\Scripts\python.exe' -m compileall -q @sources
if ($LASTEXITCODE -ne 0) {
  Write-Error '项目源码检查失败，环境未通过检查。'
  exit 1
}
Write-Host 'Gongwei local environment is ready.'
exit 0
