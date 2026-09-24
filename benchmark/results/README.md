# Published benchmark data

`r1-revision/` contains the measurements released with the associated *Computing* article.

## Layout

The main hierarchy is:

```text
r1-revision/<client-region>/<platform>/<scenario>/<measurement-file>
```

Client regions include the local Vietnam client and AWS clients in EU-West-1, US-East-1, and AP-Southeast-1. Scenario directories distinguish warm, cold, burst, ramp-sensitivity, no-op, memory-configuration, and response-header measurements.

JSON filenames encode the scenario, platform, tier, data mode, run number, and UTC timestamp. Large response-header trace logs are retained because they support the isolate-routing analysis reported in the article.

## Interpretation

- `mock` runs use deterministic local input data to isolate platform and network behavior.
- `live` runs access the external market-data API and therefore include upstream variability.
- US-East-1 live experiments were unavailable because the upstream API returned HTTP 451 from that region.
- Absolute latency depends on client location, routing, platform state, and measurement date.

Derived CSV summaries are available in `../analysis/output/`. Analysis programs are available in `../analysis/`.

When reusing these measurements, cite DOI `10.1007/s00607-026-01734-w`.
