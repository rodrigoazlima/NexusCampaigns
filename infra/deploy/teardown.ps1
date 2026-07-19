# Stop + remove local RabbitMQ container. Pass -Purge to also drop the data volume.
param([switch]$Purge)
$ErrorActionPreference = 'Stop'

podman rm -f nexus-rabbitmq 2>$null | Out-Null
if ($Purge) { podman volume rm nexus-rabbitmq-data 2>$null | Out-Null }

Write-Host "RabbitMQ container removed$(if ($Purge) { ' (volume purged)' })."
