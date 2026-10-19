# contextbase Monitoring Stack

Docker-based monitoring stack using **Grafana LGTM** (Loki, Grafana, Tempo, Mimir) for complete observability.

## Quick Start

```bash
# Start the monitoring stack
./scripts/dev/start-monitoring.sh

# Or manually with docker-compose
cd scripts/dev/monitoring && docker-compose up -d
```

## Access

- **Grafana UI**: http://localhost:3000
  - No login required (anonymous admin enabled for dev)

## Features

- **Traces**: OpenTelemetry traces with GenAI semantic conventions (Tempo)
- **Metrics**: Prometheus scraping of contextbase API `/metrics` endpoint
- **Logs**: Loki log aggregation (future)
- **Dashboards**: Pre-configured dashboards from `monitoring/grafana/dashboards/`:
  - contextbase Operations
  - contextbase LLM Metrics
  - contextbase API Service

## Configure contextbase API

Set these environment variables in your `.env`:

```bash
# Enable tracing
CONTEXTBASE_API_OTEL_TRACES_ENABLED=true

# Grafana Tempo OTLP endpoint (HTTP)
CONTEXTBASE_API_OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318

# Optional: Custom service name
CONTEXTBASE_API_OTEL_SERVICE_NAME=contextbase-api

# Optional: Deployment environment
CONTEXTBASE_API_OTEL_DEPLOYMENT_ENVIRONMENT=development
```

## View Data

### Traces
1. Open http://localhost:3000
2. Go to **Explore** (compass icon)
3. Select **Tempo** as data source
4. Click "Search" to see recent traces

### Metrics & Dashboards
1. Open http://localhost:3000
2. Go to **Dashboards** (dashboard icon)
3. Browse the contextbase folder

### Raw Metrics
- Prometheus metrics: http://localhost:8888/metrics
- PromQL queries: Explore → Prometheus

## Ports

| Port | Service |
|------|---------|
| 3000 | Grafana UI |
| 4317 | OTLP gRPC endpoint |
| 4318 | OTLP HTTP endpoint |

## Stop

```bash
cd scripts/dev/monitoring && docker-compose down
```

## Architecture

- **Single Container**: Grafana LGTM (~515MB) provides all observability components
- **Auto-provisioned Dashboards**: Dashboards from `monitoring/grafana/dashboards/` are automatically loaded
- **Prometheus Scraping**: Configured to scrape contextbase API at `host.docker.internal:8888/metrics` every 5 seconds
- **Network**: Uses `contextbase-network` (shared with API for future service-to-service tracing)
