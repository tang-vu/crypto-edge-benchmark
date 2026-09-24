#!/usr/bin/env bash
# Verify each provisioned VM is reachable + benchmark-ready.
# Source vm-inventory.env (produced by provision-vms.sh) and ssh into each.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY="${SCRIPT_DIR}/vm-inventory.env"

[[ -f "${INVENTORY}" ]] || { echo "ERROR: ${INVENTORY} not found. Run provision-vms.sh first."; exit 1; }
# shellcheck source=/dev/null
source "${INVENTORY}"

CF_URL="${CF_URL:-https://crypto-analytics-worker.8ndwvxvrgt.workers.dev}"
VERCEL_URL="${VERCEL_URL:-https://crypto-edge-benchmark.vercel.app}"

declare -A IPS=(
  [us-east-1]="${US_EAST_1_IP:-}"
  [eu-west-1]="${EU_WEST_1_IP:-}"
  [ap-southeast-1]="${AP_SOUTHEAST_1_IP:-}"
)

PASS=0; FAIL=0
for REGION in "${!IPS[@]}"; do
  IP="${IPS[$REGION]}"
  if [[ -z "${IP}" || "${IP}" == "None" ]]; then
    echo "[smoke] ${REGION}: NO IP — skipping"; FAIL=$((FAIL+1)); continue
  fi
  echo "----- ${REGION} (${IP}) -----"
  if ssh -i ~/.ssh/crypto-bench \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=10 \
        -o LogLevel=ERROR \
        ubuntu@"${IP}" "
    set -e
    echo 'k6:        '\$(k6 version 2>&1 | head -1)
    echo 'cf-edge:    '\$(curl -s -o /dev/null -w '%{http_code}' ${CF_URL}/health)
    echo 'vercel:     '\$(curl -s -o /dev/null -w '%{http_code}' ${VERCEL_URL}/health)
    echo 'binance:    '\$(curl -s -o /dev/null -w '%{http_code}' https://api.binance.com/api/v3/ping)
    echo 'repo:       '\$(ls /home/ubuntu/crypto-edge-benchmark/benchmark/k6/scenarios/ 2>&1 | wc -l)' scenarios'
  "; then
    PASS=$((PASS+1))
  else
    echo "[smoke] ${REGION}: SSH/exec failed (cloud-init may still be running — wait 2-3 min and retry)"
    FAIL=$((FAIL+1))
  fi
done

echo ""
echo "[smoke] PASS=${PASS} FAIL=${FAIL}"
[[ ${FAIL} -eq 0 ]] || exit 1
