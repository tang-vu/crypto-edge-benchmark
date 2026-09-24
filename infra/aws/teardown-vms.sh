#!/usr/bin/env bash
# Terminate all VMs tagged project=crypto-bench-r1 across configured regions.
# Run AFTER all benchmarks captured to avoid orphaned hourly bills.
set -euo pipefail

REGIONS=(us-east-1 eu-west-1 ap-southeast-1)
PROJECT_TAG="crypto-bench-r1"

for REGION in "${REGIONS[@]}"; do
  echo "----- ${REGION} -----"
  IDS="$(aws ec2 describe-instances --region "${REGION}" \
    --filters "Name=tag:project,Values=${PROJECT_TAG}" \
              "Name=instance-state-name,Values=pending,running,stopped,stopping" \
    --query 'Reservations[].Instances[].InstanceId' --output text)"
  if [[ -z "${IDS}" || "${IDS}" == "None" ]]; then
    echo "[teardown] no instances"
    continue
  fi
  echo "[teardown] terminating: ${IDS}"
  # shellcheck disable=SC2086
  aws ec2 terminate-instances --region "${REGION}" --instance-ids ${IDS} >/dev/null
  # shellcheck disable=SC2086
  aws ec2 wait instance-terminated --region "${REGION}" --instance-ids ${IDS}
  echo "[teardown] done"
done

echo ""
echo "[teardown] ALL DONE — verify final cost in AWS Billing console."
echo "[teardown] (Security groups + key pairs left in place; safe to remove manually if desired)"
