#!/usr/bin/env bash
# Overnight chain pipeline for Phase 2 + Phase 3 baselines.
# Waits for the currently-running warm matrix (started 2026-05-07 ~00:11 ICT) to
# finish, then re-runs partially-failed warm cells, then burst, then cold.
#
# Started: 2026-05-07 ~00:45 ICT
# ETA: warm finish ~01:15, re-runs +15min, burst +150min, cold +25min
# Total wallclock: ~3.5h from launch
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)/benchmark/results/r1-revision"
PIPELINE_LOG="${RESULTS_DIR}/_pipeline-overnight-$(date -u +%Y%m%dT%H%M%SZ).log"

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "${PIPELINE_LOG}"; }

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/vm-inventory.env"

mkdir -p "${RESULTS_DIR}"
log "===== PIPELINE START ====="

# --- Phase A: wait for current warm matrix to finish -----------------------
# Warm runs cell 14 (ap-southeast-1 vercel warm live) last. Its run-3 file
# appearing under the canonical path is our "warm done" signal.
LAST_CELL_PATTERN="${RESULTS_DIR}/ap-southeast-1/vercel/warm/warm-vercel-paid-live-run3-*.json"

log "Waiting for warm matrix completion (poll: ${LAST_CELL_PATTERN##*/})..."
while ! ls ${LAST_CELL_PATTERN} >/dev/null 2>&1; do
  sleep 60
done
log "Warm matrix complete (last-cell file detected)."

# --- Phase B: re-run cells that lost runs to set -e bug --------------------
log "===== Re-running failed warm cells (cells 1, 2, 5) ====="
log "Local CF: 1 file → need 2 more runs"
bash "${SCRIPT_DIR}/run-experiment.sh" --client local --platform cf --scenario warm --mode mock --runs 2 \
  >>"${PIPELINE_LOG}" 2>&1 || log "WARN: local-cf re-run failed"

log "Local Vercel: 1 file → need 2 more runs"
bash "${SCRIPT_DIR}/run-experiment.sh" --client local --platform vercel --scenario warm --mode mock --runs 2 \
  >>"${PIPELINE_LOG}" 2>&1 || log "WARN: local-vercel re-run failed"

log "EU-West CF: 1 file → need 2 more runs"
bash "${SCRIPT_DIR}/run-experiment.sh" --client eu-west-1 --platform cf --scenario warm --mode mock --runs 2 \
  >>"${PIPELINE_LOG}" 2>&1 || log "WARN: eu-cf re-run failed"

# --- Phase C: burst matrix --------------------------------------------------
log "===== Starting burst matrix (14 cells × 3 runs) ====="
rm -f "${RESULTS_DIR}/_matrix-burst.done"
bash "${SCRIPT_DIR}/run-matrix.sh" --subset burst --runs 3 >>"${PIPELINE_LOG}" 2>&1 || log "WARN: burst matrix non-zero exit"
[[ -f "${RESULTS_DIR}/_matrix-burst.done" ]] && log "Burst matrix done." || log "WARN: burst .done marker missing"

# --- Phase D: cold matrix --------------------------------------------------
log "===== Starting cold matrix (14 cells × 3 runs) ====="
rm -f "${RESULTS_DIR}/_matrix-cold.done"
bash "${SCRIPT_DIR}/run-matrix.sh" --subset cold --runs 3 >>"${PIPELINE_LOG}" 2>&1 || log "WARN: cold matrix non-zero exit"
[[ -f "${RESULTS_DIR}/_matrix-cold.done" ]] && log "Cold matrix done." || log "WARN: cold .done marker missing"

# --- Done ------------------------------------------------------------------
log "===== PIPELINE COMPLETE ====="
log "Log: ${PIPELINE_LOG}"
touch "${RESULTS_DIR}/_pipeline-overnight.done"
