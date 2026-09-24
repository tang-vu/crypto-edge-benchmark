#!/bin/bash
# EC2 user-data — runs once at first boot via cloud-init.
# Installs k6, clones the benchmark repo, validates prerequisites.
set -euo pipefail
exec > >(tee -a /var/log/bootstrap.log) 2>&1
echo "[bootstrap] start $(date -u)"

# Base packages
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  curl git ca-certificates gnupg wget jq unzip

# k6 binary (avoid apt repo flakiness)
K6_VERSION="v0.49.0"
curl -fsSL "https://github.com/grafana/k6/releases/download/${K6_VERSION}/k6-${K6_VERSION}-linux-amd64.tar.gz" \
  | tar xz -C /tmp
install -m 0755 "/tmp/k6-${K6_VERSION}-linux-amd64/k6" /usr/local/bin/k6

# Node.js 20 (for helper scripts in repo)
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs

# Clone benchmark repo (public HTTPS)
REPO_URL="https://github.com/tang-vu/crypto-edge-benchmark.git"
DEST="/home/ubuntu/crypto-edge-benchmark"
if [[ ! -d "${DEST}" ]]; then
  sudo -u ubuntu git clone "${REPO_URL}" "${DEST}"
fi

# Validation summary in log
echo "[bootstrap] k6: $(k6 version 2>&1 | head -1)"
echo "[bootstrap] node: $(node --version)"
echo "[bootstrap] git: $(git --version)"
echo "[bootstrap] repo files: $(ls -1 ${DEST} | wc -l)"
echo "[bootstrap] DONE $(date -u)"
