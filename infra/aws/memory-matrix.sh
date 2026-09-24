#!/usr/bin/env bash
# Memory variation matrix for Vercel Edge — R2.2 explicit empirical answer.
# Tests memory configs: 256MB, 512MB, 1024MB, 3072MB
# Each: edit vercel.json → redeploy → cold-start n=3 → move outputs
# Final: restore vercel.json (remove memory key)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VERCEL_DIR="${REPO_ROOT}/apps/vercel-edge"
RESULTS_DIR="${REPO_ROOT}/benchmark/results/r1-revision/local/vercel-memory"
LOG="${REPO_ROOT}/benchmark/results/r1-revision/_memory-matrix-$(date -u +%Y%m%dT%H%M%SZ).log"

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "${LOG}"; }
mkdir -p "${RESULTS_DIR}"

CONFIGS=(256 512 1024 3072)

log "===== MEMORY MATRIX START ====="

# Backup current vercel.json
cp "${VERCEL_DIR}/vercel.json" "${VERCEL_DIR}/vercel.json.bak"

for MEM in "${CONFIGS[@]}"; do
  log "----- memory=${MEM}MB -----"

  # Rewrite vercel.json from scratch with this memory config (avoid python3 dependency on Windows).
  cat > "${VERCEL_DIR}/vercel.json" <<EOF
{
  "rewrites": [
    { "source": "/health", "destination": "/api/health" },
    { "source": "/api/crypto-analytics", "destination": "/api/crypto-analytics" }
  ],
  "headers": [
    {
      "source": "/api/(.*)",
      "headers": [
        { "key": "Access-Control-Allow-Origin", "value": "*" },
        { "key": "Access-Control-Allow-Methods", "value": "GET, OPTIONS" },
        { "key": "Access-Control-Allow-Headers", "value": "Content-Type" }
      ]
    }
  ],
  "functions": {
    "api/crypto-analytics.ts": { "memory": ${MEM} }
  }
}
EOF

  # Redeploy
  log "Deploying mem=${MEM}MB..."
  ( cd "${VERCEL_DIR}" && npx --yes vercel@latest --prod --yes 2>&1 | tail -3 ) >>"${LOG}" 2>&1 || log "WARN: deploy non-zero"

  # Brief settle
  sleep 5

  # Cold-start n=3
  log "Cold-start n=3 at mem=${MEM}MB..."
  for r in 1 2 3; do
    ts=$(date -u +%Y%m%dT%H%M%SZ)
    fname="cold-vercel-mem${MEM}-paid-mock-run${r}-${ts}.json"
    csv_name="cold-vercel-mem${MEM}-paid-mock-run${r}-${ts}.csv"
    ( cd "${REPO_ROOT}" && k6 run \
        -e "ENDPOINT_URL=https://vercel-edge-murex.vercel.app/api/crypto-analytics?symbol=BTCUSDT&interval=1h" \
        -e "PLATFORM=vercel-mem${MEM}" \
        -e "RUN_NUMBER=${r}" \
        -e "ITERATIONS=5" \
        -e "COLD_START_WAIT=60" \
        --out "csv=${RESULTS_DIR}/${csv_name}" \
        benchmark/k6/scenarios/cold-start-improved.js 2>&1 | tail -2 ) >>"${LOG}" 2>&1 || true
    # Move newest k6 JSON output
    newest="$(ls -t "${REPO_ROOT}/benchmark/results/cold-start-improved-vercel-mem${MEM}-run${r}-"*.json 2>/dev/null | head -1 || true)"
    [[ -n "${newest}" ]] && mv "${newest}" "${RESULTS_DIR}/${fname}" || log "WARN: no output for mem=${MEM} run=${r}"
  done
  log "mem=${MEM}MB done."
done

# Restore vercel.json (remove memory config)
log "Restoring vercel.json..."
mv "${VERCEL_DIR}/vercel.json.bak" "${VERCEL_DIR}/vercel.json"
( cd "${VERCEL_DIR}" && npx --yes vercel@latest --prod --yes 2>&1 | tail -3 ) >>"${LOG}" 2>&1 || log "WARN: revert deploy non-zero"

touch "${REPO_ROOT}/benchmark/results/r1-revision/_memory-matrix.done"
log "===== MEMORY MATRIX DONE ====="
