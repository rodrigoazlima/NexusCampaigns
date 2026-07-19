# Build + run local RabbitMQ via Podman. Ports bound to 127.0.0.1 only (local dev, guest/guest).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

podman build -t nexus-rabbitmq:latest -f "$root\Dockerfile" "$root"
podman volume create nexus-rabbitmq-data | Out-Null

podman run -d `
  --name nexus-rabbitmq `
  --replace `
  -p 127.0.0.1:5672:5672 `
  -p 127.0.0.1:15672:15672 `
  -v nexus-rabbitmq-data:/var/lib/rabbitmq:U `
  nexus-rabbitmq:latest

Write-Host "RabbitMQ up. AMQP: 127.0.0.1:5672  Management UI: http://127.0.0.1:15672 (guest/guest)"
