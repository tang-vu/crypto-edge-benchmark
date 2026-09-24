#!/usr/bin/env bash
# Push local repo contents to each provisioned VM via tar-over-ssh.
# Avoids needing GitHub credentials on VMs (repo is private until acceptance).
# Excludes: .git, node_modules, results/, dist/, *.log
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INVENTORY="${SCRIPT_DIR}/vm-inventory.env"

[[ -f "${INVENTORY}" ]] || { echo "ERROR: ${INVENTORY} not found"; exit 1; }
# shellcheck source=/dev/null
source "${INVENTORY}"

declare -A IPS=(
  [us-east-1]="${US_EAST_1_IP:-}"
  [eu-west-1]="${EU_WEST_1_IP:-}"
  [ap-southeast-1]="${AP_SOUTHEAST_1_IP:-}"
)

REMOTE_DIR="/home/ubuntu/crypto-edge-benchmark"

# Build tarball locally once (faster than per-VM tar)
TARBALL="$(mktemp -t repo-bundle-XXXX.tar.gz)"
trap 'rm -f "${TARBALL}"' EXIT

echo "[sync] bundling repo from ${REPO_ROOT}"
tar -czf "${TARBALL}" \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='benchmark/results' \
  --exclude='benchmark/analysis/output' \
  --exclude='benchmark/analysis/figures' \
  --exclude='dist' \
  --exclude='build' \
  --exclude='.next' \
  --exclude='*.log' \
  --exclude='*.aux' \
  --exclude='*.pdf' \
  --exclude='*.zip' \
  --exclude='infra/aws/vm-inventory.env' \
  -C "${REPO_ROOT}" .
SIZE=$(stat -c%s "${TARBALL}" 2>/dev/null || stat -f%z "${TARBALL}")
echo "[sync] tarball: ${SIZE} bytes"

for REGION in "${!IPS[@]}"; do
  IP="${IPS[$REGION]}"
  if [[ -z "${IP}" || "${IP}" == "None" ]]; then
    echo "[sync] ${REGION}: NO IP — skipping"; continue
  fi
  echo "----- ${REGION} (${IP}) -----"
  # Stream tarball via ssh, extract on remote
  ssh -i ~/.ssh/crypto-bench \
      -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o LogLevel=ERROR \
      ubuntu@"${IP}" "rm -rf ${REMOTE_DIR} && mkdir -p ${REMOTE_DIR}"
  # shellcheck disable=SC2002
  cat "${TARBALL}" | ssh -i ~/.ssh/crypto-bench \
      -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o LogLevel=ERROR \
      ubuntu@"${IP}" "tar -xzf - -C ${REMOTE_DIR}"
  # Verify
  ssh -i ~/.ssh/crypto-bench \
      -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o LogLevel=ERROR \
      ubuntu@"${IP}" "ls ${REMOTE_DIR}/benchmark/k6/scenarios/ | wc -l | xargs -I{} echo '[sync] ${REGION} scenarios on VM: {}'"
done

echo ""
echo "[sync] DONE"
