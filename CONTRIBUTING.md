# Contributing to Crypto Edge Benchmark

Thank you for your interest in contributing to this research project!

## How to Contribute

### Reporting Issues

- Use GitHub Issues to report bugs or suggest improvements
- Include detailed reproduction steps for bugs
- For feature requests, explain the use case

### Code Contributions

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Run tests and linting
5. Commit with clear messages
6. Push to your fork
7. Open a Pull Request

### Adding New Edge Platforms

To add support for a new edge platform:

1. Create a new directory under `apps/` (e.g., `apps/vercel-edge/`)
2. Implement the same API endpoints as existing platforms
3. Use the shared `@crypto-benchmark/shared` package for business logic
4. Add deployment configuration
5. Update benchmark scripts to include the new platform
6. Document the setup process

### Improving Benchmark Methodology

- Suggest new test scenarios in Issues
- Propose additional metrics
- Share real-world workload patterns

## Development Setup

```bash
# Clone the repo
git clone https://github.com/tang-vu/crypto-edge-benchmark.git
cd crypto-edge-benchmark

# Install dependencies
npm install

# Build shared package
npm run build:shared

# Run local development (Cloudflare Worker)
npm run dev:worker

# Run local development (Vercel)
npm run dev:vercel
```

## Code Style

- Use TypeScript for all source code
- Follow existing code formatting
- Add JSDoc comments for public APIs
- Keep functions focused and testable

## Project Scripts

```bash
# Build all packages
npm run build

# Build only shared package
npm run build:shared

# Development
npm run dev:worker    # Start Cloudflare Worker locally
npm run dev:vercel    # Start Vercel locally

# Deployment
npm run deploy:worker # Deploy to Cloudflare
npm run deploy:vercel # Deploy to Vercel
npm run deploy:all    # Deploy both

# Benchmarks
npm run benchmark:cold    # Cold start test
npm run benchmark:warm    # Warm performance test
npm run benchmark:load    # Load test
npm run benchmark:burst   # Burst test
npm run benchmark:all     # All tests

# Analysis
npm run analyze      # Run analysis script
npm run visualize    # Generate charts
```

## Questions?

Open an issue with the "question" label.
