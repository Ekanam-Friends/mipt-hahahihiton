#!/bin/sh
# Continue the already-authorized server QA after the operator disconnects.
# Reports remain unaccepted until source review; this script never submits a form.
set -u
base=/opt/mipt-regnav
docker wait mipt-e5-fresh > "$base/qa/fresh-main.exit"
run_check() {
  docker run --rm --no-healthcheck --network mipt-regnav_model --cpus 0.5 --memory 768m \
    -e REGNAV_LOCAL_MODEL_HOSTS=model -e REGNAV_LLM_TIMEOUT=1800 \
    -v "$base/release:/work:ro" -v "$base/models:/work/models:ro" -v "$base/qa:/out" \
    -w /work mipt-regnav:release "$@"
}
run_check python -u scripts/verify_e3.py --base-url http://model:8087/v1 \
  --questions eval/e3-questions.jsonl --model-name 'Qwen3-4B server CPU 3 threads' \
  --output /out/fresh-extra.json > "$base/qa/fresh-extra.log" 2>&1
printf '%s\n' "$?" > "$base/qa/fresh-extra.exit"
run_check python -u scripts/verify_e3.py --base-url http://model:8087/v1 \
  --questions eval/e5-questions.jsonl --model-name 'Qwen3-4B server CPU 3 threads' \
  --output /out/fresh-new.json > "$base/qa/fresh-new.log" 2>&1
printf '%s\n' "$?" > "$base/qa/fresh-new.exit"
run_check python -u scripts/verify_e3_adversarial.py --base-url http://model:8087/v1 \
  --output /out/fresh-adversarial.json > "$base/qa/fresh-adversarial.log" 2>&1
printf '%s\n' "$?" > "$base/qa/fresh-adversarial.exit"
date -u +%Y-%m-%dT%H:%M:%SZ > "$base/qa/server-checks-finished-at.txt"
