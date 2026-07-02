# Local latest setup helper for Windows PowerShell.
# The project does not pin component versions. It uses what is installed locally;
# if a component is missing, it installs the latest package through winget when available.

$ErrorActionPreference = "Stop"

function Ensure-WingetPackage($Command, $PackageId) {
  if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
      winget install --id $PackageId --source winget --accept-package-agreements --accept-source-agreements
    } else {
      Write-Host "winget not found. Install $PackageId manually from the official website."
    }
  }
}

Ensure-WingetPackage "docker" "Docker.DockerDesktop"
Ensure-WingetPackage "git" "Git.Git"
Ensure-WingetPackage "node" "OpenJS.NodeJS"
Ensure-WingetPackage "python" "Python.Python.3"

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
  Write-Host "Codex CLI not found. Install the current Codex CLI according to the official OpenAI Codex documentation."
}

python scripts/local/check_local_environment.py
