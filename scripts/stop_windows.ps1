$ContainerName = "finally-app"
$existing = docker ps -a --format "{{.Names}}" | Select-String -SimpleMatch $ContainerName
if ($existing) {
  docker rm -f $ContainerName | Out-Null
  Write-Host "Stopped $ContainerName"
} else {
  Write-Host "$ContainerName not running"
}
