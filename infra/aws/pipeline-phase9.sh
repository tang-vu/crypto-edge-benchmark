#!/usr/bin/env bash
# Phase 9 pipeline — Stage A: cold-start n=5 expansion + cross-region ramp variants.
# ETA: ~90 min wallclock
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)/benchmark/results/r1-revision"
LOG="${RESULTS_DIR}/_pipeline-phase9-$(date -u +%Y%m%dT%H%M%SZ).log"

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "${LOG}"; }
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/vm-inventory.env"

mkdir -p "${RESULTS_DIR}"
log "===== PHASE 9 STAGE A START ====="

# P9.1 — cold-start n=5 (run 2 more on top of existing n=3, total n=5)
log "===== P9.1: cold-start expansion (8 cells × 2 more runs) ====="
for client in local us-east-1 eu-west-1 ap-southeast-1; do
  for plat in cf vercel; do
    log "Cold ${client}/${plat} +2 runs"
    bash "${SCRIPT_DIR}/run-experiment.sh" \
         --client "${client}" --platform "${plat}" --scenario cold \
         --mode mock --runs 2 >>"${LOG}" 2>&1 \
       || log "WARN: cold ${client}/${plat} non-zero"
  done
done
touch "${RESULTS_DIR}/_p91-cold-n5.done"
log "P9.1 done."

# P9.7 — ramp variants from EU + SG
log "===== P9.7: cross-region ramp variants ====="
for client in eu-west-1 ap-southeast-1; do
  for ramp in slow fast; do
    for plat in cf vercel; do
      log "Ramp=${ramp} client=${client} plat=${plat} runs=3"
      bash "${SCRIPT_DIR}/run-experiment.sh" \
           --client "${client}" --platform "${plat}" --scenario "burst-${ramp}" \
           --mode mock --runs 3 >>"${LOG}" 2>&1 \
         || log "WARN: ramp ${ramp}/${client}/${plat} non-zero"
    done
  done
done
touch "${RESULTS_DIR}/_p97-ramp-cross-region.done"
log "P9.7 done."

log "===== PHASE 9 STAGE A COMPLETE ====="
touch "${RESULTS_DIR}/_pipeline-phase9.done"
