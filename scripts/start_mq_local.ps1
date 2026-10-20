param(
  [string]$InfraRoot = $env:GONGWEI_ACPS_INFRA_ROOT,
  [switch]$Stop
)

$ErrorActionPreference = 'Stop'
if (-not $InfraRoot) {
  throw '请设置 GONGWEI_ACPS_INFRA_ROOT 指向官方 acps-infra 源码目录；不会自动猜测或下载基础设施。'
}
$devInfra = Join-Path $InfraRoot 'dev-infra\dev-infra.sh'
if (-not (Test-Path $devInfra)) { throw "官方 acps-infra 路径无效：$devInfra" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw 'Docker CLI 不存在；官方 acps-infra RabbitMQ 不能启动。'
}

if ($Stop) {
  & bash $devInfra down
  exit $LASTEXITCODE
}
& bash $devInfra up redis rabbitmq
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& bash $devInfra wait redis rabbitmq
exit $LASTEXITCODE
