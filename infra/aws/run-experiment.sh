#!/usr/bin/env bash
# Run a single benchmark cell: client × platform × scenario × dataMode × N runs.
# Saves results to benchmark/results/r1-revision/{client}/{platform}/{scenario}/
# with filename suffix encoding tier+mode+run number.
#
# Usage:
#   ./run-experiment.sh --client local --platform cf --scenario warm --mode mock --runs 3
#   ./run-experiment.sh --client us-east-1 --platform vercel --scenario burst --mode live --runs 1
#
# Clients: local (VN), us-east-1, eu-west-1, ap-southeast-1
# Platforms: cf | vercel
# Scenarios: cold | warm | load | burst
# Modes: mock | live
set -euo pipefail

# --- Parse args -------------------------------------------------------------
CLIENT=""; PLATFORM=""; SCENARIO=""; MODE="mock"; RUNS=3; TIER="paid"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --client)   CLIENT="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --scenario) SCENARIO="$2"; shift 2 ;;
    --mode)     MODE="$2"; shift 2 ;;
    --runs)     RUNS="$2"; shift 2 ;;
    --tier)     TIER="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done
[[ -n "${CLIENT}" && -n "${PLATFORM}" && -n "${SCENARIO}" ]] || {
  echo "Usage: $0 --client <local|us-east-1|eu-west-1|ap-southeast-1> --platform <cf|vercel> --scenario <cold|warm|load|burst> --mode <mock|live> [--runs N] [--tier paid|free]"
  exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# --- Endpoint URLs ----------------------------------------------------------
case "${PLATFORM}" in
  cf|cloudflare)   BASE_URL="https://crypto-analytics-worker.8ndwvxvrgt.workers.dev"; PLAT_TAG="cloudflare" ;;
  vercel)          BASE_URL="https://vercel-edge-murex.vercel.app"; PLAT_TAG="vercel" ;;
  *) echo "Bad platform: ${PLATFORM}"; exit 2 ;;
esac

# Append data-mode toggle to URL (default mock; ?mockData=false → live)
QUERY="?symbol=BTCUSDT&interval=1h"
[[ "${MODE}" == "live" ]] && QUERY="${QUERY}&mockData=false"
ENDPOINT_URL="${BASE_URL}${QUERY}"

# --- Scenario → k6 script path ----------------------------------------------
case "${SCENARIO}" in
  cold|cold-start)     K6_SCRIPT="benchmark/k6/scenarios/cold-start-improved.js"; FILE_PREFIX="cold-start-improved" ;;
  warm|warm-performance) K6_SCRIPT="benchmark/k6/scenarios/warm-performance.js"; FILE_PREFIX="warm-performance" ;;
  load|load-test)      K6_SCRIPT="benchmark/k6/scenarios/load-test.js"; FILE_PREFIX="load-test" ;;
  burst|burst-test)    K6_SCRIPT="benchmark/k6/scenarios/burst-test.js"; FILE_PREFIX="burst-test" ;;
  burst-slow)          K6_SCRIPT="benchmark/k6/scenarios/burst-test-slow.js"; FILE_PREFIX="burst-test-slow" ;;
  burst-fast)          K6_SCRIPT="benchmark/k6/scenarios/burst-test-fast.js"; FILE_PREFIX="burst-test-fast" ;;
  *) echo "Bad scenario: ${SCENARIO}"; exit 2 ;;
esac

# Cold supplemental: shorter for matrix runs (override-able via env).
COLD_ITERATIONS="${COLD_ITERATIONS:-5}"
COLD_WAIT_SEC="${COLD_WAIT_SEC:-60}"

# --- Output dir -------------------------------------------------------------
OUT_DIR="benchmark/results/r1-revision/${CLIENT}/${PLAT_TAG}/${SCENARIO}"
LABEL="${TIER}-${MODE}"
mkdir -p "${REPO_ROOT}/${OUT_DIR}"

echo "============================================="
echo "[experiment] client=${CLIENT} platform=${PLAT_TAG} scenario=${SCENARIO} mode=${MODE} tier=${TIER} runs=${RUNS}"
echo "[experiment] endpoint=${ENDPOINT_URL}"
echo "[experiment] out=${OUT_DIR}/"
echo "============================================="

# --- SSH wrapper for remote clients -----------------------------------------
SSH_KEY="${HOME}/.ssh/crypto-bench"
SSH_OPTS=(-i "${SSH_KEY}" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)
declare -A REMOTE_IPS=(
  [us-east-1]="${US_EAST_1_IP:-}"
  [eu-west-1]="${EU_WEST_1_IP:-}"
  [ap-southeast-1]="${AP_SOUTHEAST_1_IP:-}"
)

run_local() {
  local run_num="$1"
  local ts; ts="$(date -u +%Y%m%dT%H%M%SZ)"
  local fname="${SCENARIO}-${PLAT_TAG}-${LABEL}-run${run_num}-${ts}.json"
  local csv_name="${SCENARIO}-${PLAT_TAG}-${LABEL}-run${run_num}-${ts}.csv"
  # k6 --out csv= captures per-request metrics from ALL VUs (works for high-VU burst
  # where in-script requestData[] doesn't aggregate across VU contexts).
  # k6 exits 99 when thresholds fail — soft-fail, NOT real benchmark failure.
  ( cd "${REPO_ROOT}" && k6 run \
      -e "ENDPOINT_URL=${ENDPOINT_URL}" \
      -e "PLATFORM=${PLAT_TAG}" \
      -e "RUN_NUMBER=${run_num}" \
      -e "ITERATIONS=${COLD_ITERATIONS}" \
      -e "COLD_START_WAIT=${COLD_WAIT_SEC}" \
      --out "csv=${OUT_DIR}/${csv_name}" \
      "${K6_SCRIPT}" 2>&1 | tail -3 ) || true
  # k6 handleSummary writes filename `${FILE_PREFIX}-${platform}-run${N}-${TS}.json` in benchmark/results/
  # Pick the NEWEST matching file (avoids matching Jan 2026 baseline files with same prefix).
  local newest
  newest="$(ls -t "${REPO_ROOT}/benchmark/results/${FILE_PREFIX}-${PLAT_TAG}-run${run_num}-"*.json 2>/dev/null | head -1 || true)"
  if [[ -n "${newest}" ]]; then
    mv "${newest}" "${REPO_ROOT}/${OUT_DIR}/${fname}"
    echo "[experiment] saved: ${OUT_DIR}/${fname}"
  else
    echo "[experiment] WARN: no k6 output found matching ${FILE_PREFIX}-${PLAT_TAG}-run${run_num}-*.json"
  fi
}

run_remote() {
  local ip="$1"; local run_num="$2"
  local ts; ts="$(date -u +%Y%m%dT%H%M%SZ)"
  local fname="${SCENARIO}-${PLAT_TAG}-${LABEL}-run${run_num}-${ts}.json"
  ssh "${SSH_OPTS[@]}" ubuntu@"${ip}" "
    cd /home/ubuntu/crypto-edge-benchmark
    mkdir -p benchmark/results
    k6 run \
      -e ENDPOINT_URL='${ENDPOINT_URL}' \
      -e PLATFORM='${PLAT_TAG}' \
      -e RUN_NUMBER='${run_num}' \
      -e ITERATIONS='${COLD_ITERATIONS}' \
      -e COLD_START_WAIT='${COLD_WAIT_SEC}' \
      --out csv=/tmp/k6-perreq-${run_num}.csv \
      ${K6_SCRIPT} 2>&1 | tail -3
    true
  " || true
  # Resolve newest file path on remote, then scp it back
  local remote_path
  remote_path="$(ssh "${SSH_OPTS[@]}" ubuntu@"${ip}" \
    "ls -t /home/ubuntu/crypto-edge-benchmark/benchmark/results/${FILE_PREFIX}-${PLAT_TAG}-run${run_num}-*.json 2>/dev/null | head -1")"
  if [[ -n "${remote_path}" ]]; then
    scp "${SSH_OPTS[@]}" ubuntu@"${ip}":"${remote_path}" "${REPO_ROOT}/${OUT_DIR}/${fname}" 2>&1 | tail -1
    echo "[experiment] saved: ${OUT_DIR}/${fname}"
    # Also retrieve per-request CSV (graceful if missing — older runs)
    local csv_name="${SCENARIO}-${PLAT_TAG}-${LABEL}-run${run_num}-${ts}.csv"
    scp "${SSH_OPTS[@]}" ubuntu@"${ip}":"/tmp/k6-perreq-${run_num}.csv" \
       "${REPO_ROOT}/${OUT_DIR}/${csv_name}" 2>/dev/null || true
  else
    echo "[experiment] WARN: no remote k6 output for run ${run_num}"
  fi
}

# --- Dispatch ---------------------------------------------------------------
for r in $(seq 1 "${RUNS}"); do
  echo ""
  echo "[experiment] --- run ${r}/${RUNS} ---"
  if [[ "${CLIENT}" == "local" ]]; then
    run_local "${r}"
  else
    IP="${REMOTE_IPS[${CLIENT}]:-}"
    [[ -n "${IP}" ]] || { echo "ERROR: no IP for ${CLIENT} (source vm-inventory.env first)"; exit 1; }
    run_remote "${IP}" "${r}"
  fi
done

echo ""
echo "[experiment] DONE — ${RUNS} runs saved to ${OUT_DIR}/"
