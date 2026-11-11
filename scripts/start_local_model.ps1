$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
# Loopback only; no external requests or public listener.
& .tools/llama/bin/llama-server.exe -m models/qwen2.5-1.5b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8087 --alias regnav-local -c 4096 -t 4 -ngl 0
exit $LASTEXITCODE
