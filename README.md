# Crypto Edge Benchmark

Reproducibility repository for the article:

> Minh Vu Tang, “An experimental study of edge deployment strategies for cryptocurrency analytics workloads,” *Computing* (2026). https://doi.org/10.1007/s00607-026-01734-w

The repository contains the edge-function implementations, k6 benchmark scenarios, infrastructure scripts, raw measurements, statistical analyses, and generated tabular results used in the study. It intentionally does not contain manuscript, proof, or publisher-produced files.

## Main finding

End-to-end latency is dominated by client-to-edge topology rather than by a universal platform advantage. Cloudflare Workers was faster from the Vietnam client used for the primary baseline, while Vercel Edge Functions was faster from the tested AWS clients in EU-West-1, US-East-1, and AP-Southeast-1. Cloudflare showed lower cold-start latency in all four tested regions under the reported protocol.

These results are specific to the tested workload, platform tiers, dates, and client locations. They should not be interpreted as a global ranking of either platform.

## Repository contents

```text
apps/
  cloudflare-worker/       Cloudflare Workers implementation
  vercel-edge/             Vercel Edge Functions implementation
  lambda-edge/             Experimental AWS implementation
packages/shared/           Shared analytics logic and types
benchmark/
  k6/scenarios/            Load-generation scenarios
  results/r1-revision/     Published raw benchmark measurements
  analysis/                Statistical analysis and visualization code
infra/aws/                 Multi-region AWS client automation
scripts/                   Local benchmark orchestration
docs/                      Technical and deployment documentation
```

## Requirements

- Node.js 18 or later and npm 9 or later
- [k6](https://grafana.com/docs/k6/latest/set-up/install-k6/) for benchmark execution
- Python 3.11 or later for analysis
- Platform accounts and CLIs only when deploying new endpoints

## Install and validate

```bash
npm install
npm run build
npm run typecheck
pip install -r benchmark/analysis/requirements.txt
```

## Run locally

```bash
npm run build:shared
npm run dev:worker
npm run dev:vercel
```

## Deploy

```bash
npm run deploy:worker
npm run deploy:vercel
```

Deployment requires authentication with the respective provider. No credentials are stored in this repository.

## Run benchmarks

Use your own deployed endpoint when reproducing an experiment:

```bash
k6 run \
  -e ENDPOINT_URL=https://your-endpoint.example/api/crypto-analytics \
  benchmark/k6/scenarios/warm-performance.js
```

Convenience commands are also available:

```bash
npm run benchmark:warm
npm run benchmark:load
npm run benchmark:burst
npm run benchmark:cold:improved
```

The orchestration scripts accept explicit Cloudflare and Vercel endpoint URLs:

```bash
node scripts/run-full-benchmark.js \
  --cloudflare https://your-worker.example \
  --vercel https://your-vercel-app.example \
  --runs 5
```

## Data and analysis

The dataset released with the study is under [`benchmark/results/r1-revision`](benchmark/results/r1-revision). Filenames identify the client region, platform, scenario, mode, run, and timestamp. Derived CSV tables are under [`benchmark/analysis/output`](benchmark/analysis/output).

Install the Python dependencies, then validate ingestion of the published multi-region dataset:

```bash
pip install -r benchmark/analysis/requirements.txt
python benchmark/analysis/ingest-r1-revision.py
```

The other programs in `benchmark/analysis/` reproduce the focused cold-start, ramp-sensitivity, memory, framework-overhead, routing, effect-size, cost, and visualization analyses. Derived CSV outputs are included so results can be checked without rerunning every analysis.

See [`benchmark/results/README.md`](benchmark/results/README.md) for the dataset layout and interpretation notes.

## Citation

```bibtex
@article{Tang2026CryptoEdge,
  author  = {Tang, Minh Vu},
  title   = {An experimental study of edge deployment strategies for cryptocurrency analytics workloads},
  journal = {Computing},
  year    = {2026},
  doi     = {10.1007/s00607-026-01734-w}
}
```

Citation metadata is also provided in [`CITATION.cff`](CITATION.cff).

## License

The source code is released under the [MIT License](LICENSE). When reusing the benchmark data or analysis outputs, please cite the associated article.
