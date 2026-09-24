# infra/aws — Multi-Region Benchmark Clients

Provision 3 throwaway AWS EC2 t3.micro VMs (US-East-1, EU-West-1, AP-Southeast-1) as k6 benchmark clients for the Springer revision (R1.2 multi-region demand).

## Prerequisites

- AWS CLI v2 with valid creds — verify: `aws sts get-caller-identity`
- ~$5 budget headroom (free tier covers most or all)
- Local SSH client + dedicated keypair (created below)

## Setup

```bash
# 1. (if needed) configure / refresh AWS creds
aws configure

# 2. generate dedicated keypair (no passphrase)
ssh-keygen -t ed25519 -f ~/.ssh/crypto-bench -C crypto-bench-r1 -N ""

# 3. make scripts executable
chmod +x infra/aws/*.sh
```

## Workflow

```bash
# Provision (~3 min wallclock; cloud-init another ~3 min)
./infra/aws/provision-vms.sh

# Verify after waiting for cloud-init
./infra/aws/smoke-test.sh

# Teardown (mandatory before week 2 close to stop billing)
./infra/aws/teardown-vms.sh
```

After provisioning, `vm-inventory.env` is written with public IPs:

```bash
source infra/aws/vm-inventory.env
ssh -i ~/.ssh/crypto-bench ubuntu@${US_EAST_1_IP} \
  'cd ~/crypto-edge-benchmark && k6 run -e ENDPOINT_URL=https://... \
   benchmark/k6/scenarios/warm-performance.js'
```

## Cost estimate (worst case, no free-tier)

| Item | Rate | 24h × 3 VMs | Total |
|------|------|-------------|-------|
| t3.micro | $0.0104/h | 72h | $0.75 |
| EBS gp2 8GB | $0.0011/h | 72h | $0.08 |
| Egress (~5GB) | $0.09/GB | 5GB | $0.45 |
| **~$1.30** | | | |

Free tier (750 t3.micro hours / month for first 12 months) covers entire test window if eligible.

## Region rationale

- **us-east-1 (N. Virginia):** Vercel default region — addresses **R2.1** US→US verification
- **eu-west-1 (Ireland):** Diverse-continent client — broad multi-region coverage
- **ap-southeast-1 (Singapore):** Geographic peer of existing VN baseline — sanity check
- (existing VN local client retained as 4th measurement point)

## Files

- `bootstrap-benchmark-vm.sh` — cloud-init user-data (k6 + node + repo clone)
- `provision-vms.sh` — launch all 3 VMs, write `vm-inventory.env`
- `smoke-test.sh` — ssh into each VM, validate k6 + endpoints
- `teardown-vms.sh` — terminate by tag (`project=crypto-bench-r1`)
- `vm-inventory.env` — generated; public IPs sourced by downstream scripts (gitignored)
