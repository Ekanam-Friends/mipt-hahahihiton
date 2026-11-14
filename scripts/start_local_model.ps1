param([switch]$Baseline, [switch]$Large, [switch]$Small)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
# Loopback only; no external requests or public listener.
if ($Baseline) {
    & .tools/llama/bin/llama-server.exe -m models/qwen2.5-1.5b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8087 --alias regnav-local -c 4096 -t 4 -ngl 0
} elseif (-not $Small) {
    & .tools/llama/bin/llama-server.exe -m models/qwen3-4b-instruct-2507-q4_k_m.gguf --host 127.0.0.1 --port 8087 --alias regnav-local -c 12288 -t 4 -ngl 0 --parallel 1 -b 128 -ub 64 -ctk q4_0 -ctv q4_0 -fa on
} else {
    & .tools/llama/bin/llama-server.exe -m models/qwen3-1.7b-q4_k_m.gguf --host 127.0.0.1 --port 8087 --alias regnav-local -c 8192 -t 4 -ngl 0 --parallel 1 -b 256 -ub 128 -ctk q8_0 -ctv q8_0 -fa on --reasoning-budget 0
}
exit $LASTEXITCODE
