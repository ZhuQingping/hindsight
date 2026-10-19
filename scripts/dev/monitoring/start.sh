#!/bin/bash
set -e

# Script to start the contextbase monitoring stack with Grafana LGTM
# Provides traces (Tempo), metrics (Prometheus/Mimir), logs (Loki), and dashboards (Grafana)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
API_PORT="${API_PORT:-8888}"

cd "$SCRIPT_DIR"

echo ""
echo "🚀 Starting contextbase Monitoring Stack (Grafana LGTM)"
echo ""
echo "This provides:"
echo "  • OpenTelemetry traces (Tempo)"
echo "  • Metrics (Prometheus/Mimir)"
echo "  • Logs (Loki)"
echo "  • Dashboards (Grafana)"
echo ""

# Check if API is running
if ! curl -s "http://localhost:$API_PORT/metrics" > /dev/null 2>&1; then
    echo "⚠️  WARNING: contextbase API not detected at localhost:$API_PORT"
    echo "   Start the API first: ./scripts/dev/start-api.sh"
    echo ""
fi

echo "Access Grafana UI: http://localhost:3000"
echo "  (no login required for dev - anonymous admin enabled)"
echo ""
echo "Dashboards available:"
echo "  • contextbase Operations"
echo "  • contextbase LLM Metrics"
echo "  • contextbase API Service"
echo ""
echo "Configure contextbase API for tracing:"
echo "  export CONTEXTBASE_API_OTEL_TRACES_ENABLED=true"
echo "  export CONTEXTBASE_API_OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318"
echo ""
echo "OTLP Endpoints:"
echo "  • HTTP: http://localhost:4318"
echo "  • gRPC: http://localhost:4317"
echo ""
echo "View:"
echo "  • Traces: http://localhost:3000 → Explore → Tempo"
echo "  • Metrics: http://localhost:3000 → Dashboards"
echo "  • Raw Metrics: http://localhost:$API_PORT/metrics"
echo ""
echo "Press Ctrl+C to stop"
echo ""

docker-compose up
