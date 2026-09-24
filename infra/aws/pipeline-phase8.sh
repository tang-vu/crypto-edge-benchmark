#!/usr/bin/env bash
# Phase 8 pipeline — strengthen submission with raw traces + ramp sensitivity + cold n=3.
# Designed for unattended overnight execution.
# ETA: ~5h wallclock (burst re-run ~150min + ramp variants ~60min + cold n=3 ~120min).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)/benchmark/results/r1-revision"
LOG="${RESULTS_DIR}/_pipeline-phase8-$(date -u +%Y%m%dT%H%M%SZ).log"

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "${LOG}"; }
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/vm-inventory.env"

mkdir -p "${RESULTS_DIR}"
log "===== PHASE 8 PIPELINE START ====="

# 8.2 — burst matrix re-run with CSV per-request output (replaces 0-len rawLatencies)
log "===== Stage 8.2: burst matrix re-run (CSV per-request) ====="
rm -f "${RESULTS_DIR}/_matrix-burst.done"
bash "${SCRIPT_DIR}/run-matrix.sh" --subset burst --runs 3 >>"${LOG}" 2>&1 || log "WARN: burst rerun non-zero"
[[ -f "${RESULTS_DIR}/_matrix-burst.done" ]] && log "Burst rerun done." || log "WARN: burst .done marker missing"

# 8.3 — burst ramp-rate variants (slow + fast) from VN local for control
log "===== Stage 8.3: burst ramp variants ====="
for ramp in slow fast; do
  for plat in cf vercel; do
    log "Ramp=${ramp} platform=${plat} runs=3"
    bash "${SCRIPT_DIR}/run-experiment.sh" \
         --client local --platform "${plat}" --scenario "burst-${ramp}" \
         --mode mock --runs 3 >>"${LOG}" 2>&1 \
       || log "WARN: ramp ${ramp}/${plat} non-zero"
  done
done
touch "${RESULTS_DIR}/_matrix-ramp.done"
log "Ramp matrix done."

# 8.4 — cold-start cross-region n=3 (was n=1)
log "===== Stage 8.4: cold-start n=3 expansion ====="
for client in local us-east-1 eu-west-1 ap-southeast-1; do
  for plat in cf vercel; do
    log "Cold ${client}/${plat} runs=3"
    bash "${SCRIPT_DIR}/run-experiment.sh" \
         --client "${client}" --platform "${plat}" --scenario cold \
         --mode mock --runs 3 >>"${LOG}" 2>&1 \
       || log "WARN: cold ${client}/${plat} non-zero"
  done
done
touch "${RESULTS_DIR}/_matrix-cold-n3.done"
log "Cold n=3 expansion done."

log "===== PHASE 8 PIPELINE COMPLETE ====="
touch "${RESULTS_DIR}/_pipeline-phase8.done"
