#!/usr/bin/env bash
# Phase 2 matrix orchestrator — Springer revision R1.
# Subsets:
#   warm     : paid×{mock,live}×{4 clients,3 clients no-US for live}×{cf,vercel}×warm        ~14 cells
#   burst    : paid×{mock,live}×{4 clients,3 clients}×{cf,vercel}×burst                       ~14 cells
#   cold     : paid×mock×{4 clients}×{cf,vercel}×cold + paid×live×{3 clients}×{cf,vercel}×cold ~14 cells
#   all      : warm + burst + cold
#
# Usage:
#   ./run-matrix.sh --subset warm --runs 3
#   ./run-matrix.sh --subset all --runs 3
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse args
SUBSET="warm"
RUNS=3
while [[ $# -gt 0 ]]; do
  case "$1" in
    --subset) SUBSET="$2"; shift 2 ;;
    --runs)   RUNS="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/vm-inventory.env"

# Cell definitions (skip US-live per F1 — Binance geo-block from US-East AWS IPs).
ALL_CLIENTS=(local us-east-1 eu-west-1 ap-southeast-1)
LIVE_CLIENTS=(local eu-west-1 ap-southeast-1)
PLATFORMS=(cf vercel)

# Build cells per subset
declare -a CELLS=()
add_cell() { CELLS+=("$1|$2|$3|$4"); }   # client|platform|scenario|mode

case "${SUBSET}" in
  warm|all)
    for client in "${ALL_CLIENTS[@]}"; do
      for plat in "${PLATFORMS[@]}"; do
        add_cell "${client}" "${plat}" "warm" "mock"
      done
    done
    for client in "${LIVE_CLIENTS[@]}"; do
      for plat in "${PLATFORMS[@]}"; do
        add_cell "${client}" "${plat}" "warm" "live"
      done
    done
    ;;
esac
case "${SUBSET}" in
  burst|all)
    for client in "${ALL_CLIENTS[@]}"; do
      for plat in "${PLATFORMS[@]}"; do
        add_cell "${client}" "${plat}" "burst" "mock"
      done
    done
    for client in "${LIVE_CLIENTS[@]}"; do
      for plat in "${PLATFORMS[@]}"; do
        add_cell "${client}" "${plat}" "burst" "live"
      done
    done
    ;;
esac
case "${SUBSET}" in
  cold|all)
    for client in "${ALL_CLIENTS[@]}"; do
      for plat in "${PLATFORMS[@]}"; do
        add_cell "${client}" "${plat}" "cold" "mock"
      done
    done
    for client in "${LIVE_CLIENTS[@]}"; do
      for plat in "${PLATFORMS[@]}"; do
        add_cell "${client}" "${plat}" "cold" "live"
      done
    done
    ;;
esac

[[ ${#CELLS[@]} -gt 0 ]] || { echo "No cells for subset '${SUBSET}'"; exit 2; }

TOTAL=${#CELLS[@]}
LOG="${SCRIPT_DIR}/../../benchmark/results/r1-revision/_matrix-${SUBSET}-$(date -u +%Y%m%dT%H%M%SZ).log"
mkdir -p "$(dirname "${LOG}")"

echo "============================================="
echo "MATRIX RUN: subset=${SUBSET} runs=${RUNS} cells=${TOTAL} total=${TOTAL}*${RUNS}=$((TOTAL*RUNS))"
echo "Log: ${LOG}"
echo "Started: $(date -u)"
echo "============================================="

i=0
for cell in "${CELLS[@]}"; do
  i=$((i+1))
  IFS='|' read -r client plat scenario mode <<< "${cell}"
  echo ""
  echo ">>>>>>>> [${i}/${TOTAL}] client=${client} plat=${plat} sc=${scenario} mode=${mode} runs=${RUNS}"
  bash "${SCRIPT_DIR}/run-experiment.sh" \
       --client "${client}" \
       --platform "${plat}" \
       --scenario "${scenario}" \
       --mode "${mode}" \
       --runs "${RUNS}" \
    2>&1 | tee -a "${LOG}" | grep -E '^\[experiment\] saved|WARN|ERROR' || true
done

echo ""
echo "============================================="
echo "MATRIX DONE: $(date -u)"
echo "Saved to: benchmark/results/r1-revision/"
echo "Log: ${LOG}"
echo "============================================="
# Marker file consumed by pipeline-overnight.sh chain.
touch "$(dirname "${LOG}")/_matrix-${SUBSET}.done"
