param([switch]$Large, [switch]$Small)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
# Qwen original: https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
# Quantization publisher metadata checked 12.11.2026, pinned commit and LFS digest.
if (-not $Small) {
    $modelUrl = 'https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/ae44f08e1392f39c0e474af10c3ff8355c8b6688/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf?download=true'
    $modelHash = '2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e'
    $modelPath = Join-Path (Get-Location) 'models/qwen3-4b-instruct-2507-q4_k_m.gguf'
} else {
    $modelUrl = 'https://huggingface.co/bartowski/Qwen_Qwen3-1.7B-GGUF/resolve/dcb19155b962dbb6389f4691a982043a8e651022/Qwen_Qwen3-1.7B-Q4_K_M.gguf?download=true'
    $modelHash = '72c5c3cb38fa32d5256e2fe30d03e7a64c6c79e668ad84057e3bd66e250b24fb'
    $modelPath = Join-Path (Get-Location) 'models/qwen3-1.7b-q4_k_m.gguf'
}
if ((Test-Path -LiteralPath $modelPath) -and ((Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash -eq $modelHash)) {
    Write-Output 'E3 model SHA256 verified.'
    exit 0
}
& curl.exe -4 -L --fail --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 1800 $modelUrl -o "$modelPath.part"
if ($LASTEXITCODE -ne 0) { throw 'E3 model download failed.' }
if ((Get-FileHash -LiteralPath "$modelPath.part" -Algorithm SHA256).Hash -ne $modelHash) { throw 'E3 model SHA256 mismatch.' }
Move-Item -LiteralPath "$modelPath.part" -Destination $modelPath -Force
Write-Output 'E3 model downloaded and SHA256 verified.'
