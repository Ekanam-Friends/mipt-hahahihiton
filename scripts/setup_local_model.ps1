$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force .tools/llama, models | Out-Null
$runtimeUrl = 'https://github.com/ggml-org/llama.cpp/releases/download/b12284/llama-b12284-bin-win-cpu-x64.zip'
$runtimeHash = '6b3d2c7034b0c0bac65aa0524ddf01ba9c2b622ce7e32675976df642627defa9'
$modelUrl = 'https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true'
$modelHash = '6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e'

function Get-CheckedFile($url, $path, $hash) {
    if ((Test-Path -LiteralPath $path) -and ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -eq $hash)) { return }
    & curl.exe -4 -L --fail --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 1800 $url -o "$path.part"
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $url" }
    if ((Get-FileHash -LiteralPath "$path.part" -Algorithm SHA256).Hash -ne $hash) { throw "SHA256 mismatch: $path" }
    Move-Item -LiteralPath "$path.part" -Destination $path -Force
}

Get-CheckedFile $runtimeUrl '.tools/llama/runtime.zip' $runtimeHash
Expand-Archive -LiteralPath .tools/llama/runtime.zip -DestinationPath .tools/llama/bin -Force
Get-CheckedFile $modelUrl 'models/qwen2.5-1.5b-instruct-q4_k_m.gguf' $modelHash
Write-Output 'Runtime and model verified. Start with scripts/start_local_model.ps1.'
