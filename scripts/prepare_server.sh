#!/bin/sh
set -eu
cd /opt/mipt-regnav
expected_digest=${1:?Pass the SHA-256 from the release inventory}
test "$(sha256sum release.tar.gz | cut -d ' ' -f 1)" = "$expected_digest"
tar -xzf release.tar.gz -C release
chmod -R a+rX release
chown 10001:10001 state
cd release
docker build -t mipt-regnav:release . > ../qa/build.log 2>&1 &
build_pid=$!
model=../models/qwen3-4b-instruct-2507-q4_k_m.gguf
if ! test -f "$model"; then
  curl -fL --retry 3 --connect-timeout 20 'https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/ae44f08e1392f39c0e474af10c3ff8355c8b6688/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf?download=true' -o "$model.part" > ../qa/model-download.log 2>&1
  test "$(sha256sum "$model.part" | cut -d ' ' -f 1)" = 2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e
  mv "$model.part" "$model"
fi
test "$(sha256sum "$model" | cut -d ' ' -f 1)" = 2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e
chmod a+r "$model"
wait "$build_pid"
LLAMA_IMAGE=ghcr.io/ggml-org/llama.cpp@sha256:c7d58273d753d33a352e5c41ab300c5ae040a16fa4b202231bb606478065c124 docker compose -f compose.production.yaml up -d --no-build
docker compose -f compose.production.yaml ps
