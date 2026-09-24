#!/usr/bin/env bash
# Provision 3 EC2 t3.micro VMs across regions as k6 benchmark clients.
# Idempotent: re-running creates additional instances; use teardown-vms.sh first.
# Output: vm-inventory.env with public IPs sourced by downstream scripts.
set -euo pipefail

REGIONS=(us-east-1 eu-west-1 ap-southeast-1)
KEY_NAME="crypto-bench"
SG_NAME="crypto-bench-sg"
PROJECT_TAG="crypto-bench-r1"
INSTANCE_TYPE="t3.micro"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUB_KEY="${HOME}/.ssh/crypto-bench.pub"
USER_DATA="${SCRIPT_DIR}/bootstrap-benchmark-vm.sh"

# Preflight
[[ -f "${PUB_KEY}" ]] || {
  echo "ERROR: ${PUB_KEY} not found. Run:"
  echo "  ssh-keygen -t ed25519 -f ~/.ssh/crypto-bench -C crypto-bench-r1 -N ''"
  exit 1
}
[[ -f "${USER_DATA}" ]] || { echo "ERROR: ${USER_DATA} not found"; exit 1; }

# AWS CLI on Windows is native exe — needs Windows-style paths for fileb://
if command -v cygpath >/dev/null 2>&1; then
  PUB_KEY_AWS="$(cygpath -w "${PUB_KEY}")"
  USER_DATA_AWS="$(cygpath -w "${USER_DATA}")"
else
  PUB_KEY_AWS="${PUB_KEY}"
  USER_DATA_AWS="${USER_DATA}"
fi
aws sts get-caller-identity >/dev/null 2>&1 || {
  echo "ERROR: AWS credentials invalid/expired. Run: aws configure"
  exit 1
}

# Public IP detection — multiple fallbacks (Git Bash on Windows often has SSL cert issues)
AUTHOR_IP="${AUTHOR_IP:-}"
if [[ -z "${AUTHOR_IP}" ]]; then
  for url in https://checkip.amazonaws.com https://api.ipify.org https://ifconfig.me; do
    AUTHOR_IP="$(curl -fsS --max-time 5 -k "${url}" 2>/dev/null | tr -d '[:space:]' || true)"
    [[ -n "${AUTHOR_IP}" ]] && break
  done
fi
if [[ -z "${AUTHOR_IP}" ]] && command -v powershell >/dev/null 2>&1; then
  AUTHOR_IP="$(powershell -NoProfile -Command "(Invoke-WebRequest -Uri https://checkip.amazonaws.com -UseBasicParsing).Content.Trim()" 2>/dev/null | tr -d '\r\n[:space:]')"
fi
[[ -n "${AUTHOR_IP}" ]] || { echo "ERROR: failed to detect public IP. Override: AUTHOR_IP=x.x.x.x bash provision-vms.sh"; exit 1; }
echo "[provision] author IP: ${AUTHOR_IP}/32"

declare -A INSTANCE_IPS

for REGION in "${REGIONS[@]}"; do
  echo "----- ${REGION} -----"

  # Resolve latest Ubuntu 22.04 AMI (Canonical owner 099720109477)
  AMI_ID="$(aws ec2 describe-images --region "${REGION}" --owners 099720109477 \
    --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
              "Name=state,Values=available" \
              "Name=architecture,Values=x86_64" \
    --query 'sort_by(Images, &CreationDate)[-1].ImageId' --output text)"
  [[ "${AMI_ID}" != "None" && -n "${AMI_ID}" ]] || { echo "ERROR: no Ubuntu 22.04 AMI found in ${REGION}"; exit 1; }
  echo "[provision] AMI: ${AMI_ID}"

  # Import keypair (idempotent)
  if ! aws ec2 describe-key-pairs --region "${REGION}" --key-names "${KEY_NAME}" >/dev/null 2>&1; then
    aws ec2 import-key-pair --region "${REGION}" \
      --key-name "${KEY_NAME}" \
      --public-key-material "fileb://${PUB_KEY_AWS}" >/dev/null
    echo "[provision] imported key"
  fi

  # Default VPC
  VPC_ID="$(aws ec2 describe-vpcs --region "${REGION}" \
    --filters Name=isDefault,Values=true \
    --query 'Vpcs[0].VpcId' --output text)"

  # SG: create or reuse
  SG_ID="$(aws ec2 describe-security-groups --region "${REGION}" \
    --filters "Name=group-name,Values=${SG_NAME}" "Name=vpc-id,Values=${VPC_ID}" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo None)"
  if [[ "${SG_ID}" == "None" || -z "${SG_ID}" ]]; then
    SG_ID="$(aws ec2 create-security-group --region "${REGION}" \
      --group-name "${SG_NAME}" \
      --description "crypto-bench-r1 SSH from author IP" \
      --vpc-id "${VPC_ID}" \
      --query 'GroupId' --output text)"
    aws ec2 authorize-security-group-ingress --region "${REGION}" \
      --group-id "${SG_ID}" --protocol tcp --port 22 \
      --cidr "${AUTHOR_IP}/32" >/dev/null
    echo "[provision] created SG: ${SG_ID}"
  else
    echo "[provision] reusing SG: ${SG_ID}"
  fi

  # Launch
  INSTANCE_ID="$(aws ec2 run-instances --region "${REGION}" \
    --image-id "${AMI_ID}" \
    --instance-type "${INSTANCE_TYPE}" \
    --key-name "${KEY_NAME}" \
    --security-group-ids "${SG_ID}" \
    --user-data "file://${USER_DATA_AWS}" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=project,Value=${PROJECT_TAG}},{Key=region,Value=${REGION}},{Key=Name,Value=crypto-bench-${REGION}}]" \
    --query 'Instances[0].InstanceId' --output text)"
  echo "[provision] launched: ${INSTANCE_ID}"

  aws ec2 wait instance-running --region "${REGION}" --instance-ids "${INSTANCE_ID}"
  PUBLIC_IP="$(aws ec2 describe-instances --region "${REGION}" \
    --instance-ids "${INSTANCE_ID}" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
  INSTANCE_IPS[${REGION}]="${PUBLIC_IP}"
  echo "[provision] public IP: ${PUBLIC_IP}"
done

# Inventory file (sourced by smoke-test + downstream phase scripts)
OUT="${SCRIPT_DIR}/vm-inventory.env"
{
  echo "# Generated $(date -u) by provision-vms.sh"
  for r in "${!INSTANCE_IPS[@]}"; do
    VAR="$(echo "${r}" | tr 'a-z-' 'A-Z_')_IP"
    echo "export ${VAR}=${INSTANCE_IPS[${r}]}"
  done
} > "${OUT}"

echo ""
echo "============================================"
echo "PROVISIONED (project=${PROJECT_TAG})"
echo "============================================"
for r in "${!INSTANCE_IPS[@]}"; do
  printf "  %-20s %s\n" "${r}" "${INSTANCE_IPS[${r}]}"
done
echo ""
echo "Inventory: ${OUT}"
echo "Wait ~3-5min for cloud-init, then run: ${SCRIPT_DIR}/smoke-test.sh"
