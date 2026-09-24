# Deployment Guide

> **Version:** 1.0.0  
> **Last Updated:** January 16, 2026

This guide covers deployment to Cloudflare Workers and Vercel Edge Functions.

## Prerequisites

### Required Tools

| Tool | Version | Installation |
|------|---------|--------------|
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) |
| npm | 9+ | Included with Node.js |
| k6 | Latest | [k6.io/docs/getting-started](https://k6.io/docs/getting-started/installation/) |
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |

### Platform Accounts

| Platform | Tier | Sign Up |
|----------|------|---------|
| Cloudflare | Free | [dash.cloudflare.com](https://dash.cloudflare.com/sign-up) |
| Vercel | Hobby (Free) | [vercel.com/signup](https://vercel.com/signup) |

### CLI Tools

```bash
# Install Wrangler (Cloudflare)
npm install -g wrangler

# Install Vercel CLI
npm install -g vercel
```

## Initial Setup

### 1. Clone and Install

```bash
# Clone repository
git clone https://github.com/your-username/crypto-edge-benchmark.git
cd crypto-edge-benchmark

# Install dependencies
npm install
```

### 2. Build Shared Package

```bash
npm run build:shared
```

This step is **required** before deploying Cloudflare Worker.

## Cloudflare Workers Deployment

### Step 1: Authenticate

```bash
wrangler login
```

This opens a browser for OAuth authentication.

### Step 2: Configure (Optional)

Edit `apps/cloudflare-worker/wrangler.toml` if needed:

```toml
name = "crypto-analytics-worker"
main = "src/index.ts"
compatibility_date = "2024-01-01"
compatibility_flags = ["nodejs_compat"]

[vars]
PLATFORM = "cloudflare-worker"

[dev]
port = 8787
```

### Step 3: Deploy

```bash
# From root directory
npm run deploy:worker

# Or from app directory
cd apps/cloudflare-worker
npm run deploy
```

### Step 4: Verify Deployment

```bash
# Get your worker URL from the deployment output
curl https://crypto-analytics-worker.<your-subdomain>.workers.dev/health
```

Expected response:
```json
{
  "status": "healthy",
  "platform": "cloudflare-worker",
  "timestamp": 1705420800000,
  "coldStart": true
}
```

### Cloudflare Troubleshooting

| Issue | Solution |
|-------|----------|
| `wrangler: command not found` | Run `npm install -g wrangler` |
| Authentication error | Run `wrangler login` again |
| Build error | Ensure `npm run build:shared` completed |
| Compatibility error | Check `compatibility_date` in wrangler.toml |

## Vercel Edge Deployment

### Step 1: Authenticate

```bash
vercel login
```

### Step 2: Link Project

```bash
cd apps/vercel-edge
vercel link
```

Follow prompts to:
1. Set up new project or link existing
2. Choose scope (personal/team)
3. Link to repository

### Step 3: Deploy

```bash
# From root directory
npm run deploy:vercel

# Or from app directory
cd apps/vercel-edge
vercel --prod
```

### Step 4: Verify Deployment

```bash
# Get your deployment URL from the output
curl https://your-project.vercel.app/api/crypto-analytics?symbol=BTCUSDT
```

### Vercel Troubleshooting

| Issue | Solution |
|-------|----------|
| `vercel: command not found` | Run `npm install -g vercel` |
| Edge runtime error | Verify `export const config = { runtime: 'edge' }` in file |
| 404 on deployment | Check `vercel.json` rewrites configuration |
| Build timeout | Increase timeout in project settings |

## Local Development

### Cloudflare Worker (localhost:8787)

```bash
npm run dev:worker
```

Test locally:
```bash
curl "http://localhost:8787/api/crypto-analytics?symbol=ETHUSDT&interval=1h"
```

### Vercel Edge (localhost:3000)

```bash
npm run dev:vercel
```

Test locally:
```bash
curl "http://localhost:3000/api/crypto-analytics?symbol=ETHUSDT&interval=1h"
```

## Environment Variables

### Cloudflare Workers

Set via `wrangler.toml`:
```toml
[vars]
PLATFORM = "cloudflare-worker"
```

Or via CLI:
```bash
wrangler secret put API_KEY
```

### Vercel Edge

Set via Vercel Dashboard or CLI:
```bash
vercel env add PLATFORM
```

## Deployment Scripts

### Deploy Both Platforms

```bash
npm run deploy:all
```

This runs:
1. `npm run deploy:worker` (Cloudflare)
2. `npm run deploy:vercel` (Vercel)

### Automated Benchmarking

After deployment, run benchmarks:

```bash
# Set your deployed URLs
export CF_URL="https://crypto-analytics-worker.your-subdomain.workers.dev"
export VERCEL_URL="https://your-project.vercel.app"

# Run warm performance test on Cloudflare
k6 run -e ENDPOINT_URL=$CF_URL benchmark/k6/scenarios/warm-performance.js

# Run warm performance test on Vercel
k6 run -e ENDPOINT_URL=$VERCEL_URL benchmark/k6/scenarios/warm-performance.js
```

## Production Checklist

### Before Deployment

- [ ] Build shared package: `npm run build:shared`
- [ ] Type check: `npm run typecheck`
- [ ] Lint: `npm run lint`
- [ ] Test locally: `npm run dev:worker` / `npm run dev:vercel`

### After Deployment

- [ ] Verify health endpoint returns 200
- [ ] Verify analytics endpoint returns data
- [ ] Check cold start behavior (first request)
- [ ] Run warmup requests before benchmarking

## Monitoring

### Cloudflare

Access via [dash.cloudflare.com](https://dash.cloudflare.com):
- Workers & Pages → your worker → Metrics
- View requests, errors, CPU time

### Vercel

Access via [vercel.com/dashboard](https://vercel.com/dashboard):
- Project → Analytics
- View function invocations, errors, duration

## Rollback

### Cloudflare

```bash
# List deployments
wrangler deployments list

# Rollback to previous version
wrangler rollback
```

### Vercel

```bash
# List deployments
vercel ls

# Promote previous deployment
vercel promote <deployment-url>
```

## Cost Considerations

### Cloudflare Workers

| Tier | Requests/Day | Requests/Month | Price |
|------|--------------|----------------|-------|
| Free | 100,000 | ~3M | $0 |
| Paid | Unlimited | 10M included | $5/mo |

### Vercel Edge

| Tier | Edge Requests | Price |
|------|---------------|-------|
| Hobby | 100,000/day | $0 |
| Pro | 1M included | $20/mo |

### Benchmark Usage Estimate

| Scenario | Requests | Runs/Day | Daily Usage |
|----------|----------|----------|-------------|
| Warm (1000 iter) | 1,000 | 5 | 5,000 |
| Load (30s, 10 VU) | ~500 | 3 | 1,500 |
| Burst (60s, 100 VU) | ~3,000 | 2 | 6,000 |
| **Total** | | | **~12,500/day** |

Free tier is sufficient for development and testing.
