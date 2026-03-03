$ImageName = "finally"
$ContainerName = "finally-app"

if (-not (docker image inspect $ImageName 2>$null)) {
  docker build -t $ImageName .
}

$existing = docker ps -a --format "{{.Names}}" | Select-String -SimpleMatch $ContainerName
if ($existing) {
  docker rm -f $ContainerName | Out-Null
}

docker run -d --name $ContainerName -p 8000:8000 -v "${PWD}/db:/app/db" --env-file .env $ImageName | Out-Null
Write-Host "FinAlly running at http://localhost:8000"
