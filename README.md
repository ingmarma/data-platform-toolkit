# 🏗️ data-platform-toolkit

> Production-grade serverless modules for Data Platform Engineers. Schema validation, data quality monitoring, pipeline observability, and self-service queries — all on AWS, $0/month base cost.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![AWS SAM](https://img.shields.io/badge/AWS-SAM-FF9900?logo=amazon-aws)](https://aws.amazon.com/serverless/sam/)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Serverless](https://img.shields.io/badge/Architecture-Serverless-blueviolet)](https://aws.amazon.com/serverless/)

---

## The Problem

Building a data pipeline is one thing. **Operating a data platform** is another.

You ship a Glue job, it works, and everyone's happy — until a schema changes at 3 AM and breaks downstream silently. Or data stops arriving and nobody notices until a stakeholder asks why the dashboard is empty. Or a query scans 2 TB of data and the bill arrives next month.

A senior Data Platform Engineer doesn't just move data. They build **the systems that keep data reliable, observable, and accessible** — without becoming the bottleneck.

This toolkit gives you production-ready modules for the four pillars of a mature data platform:

```
┌──────────────────────────────────────────────────────────────┐
│                     DATA SOURCES                              │
│       APIs  ·  Databases  ·  S3 Uploads  ·  Streams          │
└──────────────────────┬───────────────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │    SCHEMA VALIDATOR     │  ← Catch breaking changes
          │  Glue Registry + S3    │     before they propagate
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │    QUALITY ENGINE       │  ← Freshness SLAs, volume
          │  Athena + DynamoDB     │     anomalies, null rates
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  PIPELINE OBSERVABILITY │  ← Duration, cost, records
          │  EventBridge + CW      │     per pipeline per run
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  SELF-SERVICE QUERIES   │  ← Parameterized SQL API
          │  API GW + Athena       │     with usage analytics
          └─────────────────────────┘
```

## Modules

### 📋 Schema Validator

Pre-ingestion validation gate triggered by S3 events.

- **JSON Schema & Avro** validation against Glue Schema Registry
- **Breaking change detection**: removed fields, type changes, new required fields
- Severity classification (critical / warning)
- Invalid files → quarantine bucket + SNS alert

```python
# Automatic: upload a file to s3://data-lake/raw/ → Lambda validates it
# If invalid → moved to s3://data-lake-quarantine/ + alert fires
```

### 📊 Quality Engine

Scheduled data quality monitoring with composite scoring.

- **Freshness**: is data arriving within SLA? (score degrades linearly)
- **Volume anomaly**: 50% drop or 3x spike vs 7-day rolling average
- **Null rate**: per-column null percentage tracking with thresholds
- **Quality Score** = Freshness (30%) + Volume (30%) + Null rates (40%)
- Results → DynamoDB + SNS alerts on threshold breach

```python
# Runs hourly via EventBridge Schedule
# Score < 0.8 → SNS alert with breakdown per check
```

### 🔍 Pipeline Observability

Real-time pipeline metrics via EventBridge event consumers.

- **Glue jobs**: duration, DPU consumption, success/failure tracking
- **Step Functions**: execution tracking across states
- **Custom events**: records in/out/rejected per stage
- **Cost estimation**: Glue DPU-hours ($0.44/hr), Athena TB scanned ($5/TB), Lambda GB-seconds
- Metrics → DynamoDB (history) + CloudWatch (dashboards & alarms)

```python
# Automatic: Glue job completes → EventBridge → Lambda stores metrics
# CloudWatch Metric: DataPlatform/Pipelines/EstimatedCost per pipeline
```

### 🔎 Self-Service Queries

REST API for teams to run pre-approved Athena queries without SQL or AWS access.

- **Parameterized SQL templates** stored in DynamoDB
- **SQL injection prevention**: strict type validation + character filtering
- 10 GB scan limit per query via Athena WorkGroup
- **Usage analytics**: who queries what, how often, adoption metrics
- Pre-signed S3 URLs for result downloads

```bash
# Execute a template
curl -X POST /query -d '{"template": "daily_summary", "parameters": {"date": "2024-11-18"}}'

# Check results
curl /query/{execution-id}

# List available templates
curl /queries
```

## Architecture

Everything runs on AWS Serverless — **$0/month base cost** (you pay only for actual usage):

| Service | Purpose | Pricing |
|---------|---------|---------|
| **Lambda** (ARM64) | All compute | ~$0.20 per 1M requests |
| **DynamoDB** (On-Demand) | Metrics, templates, usage | Pay per read/write |
| **S3** | Data lake, quarantine, results | $0.023/GB/month |
| **EventBridge** | Pipeline event routing | $1 per 1M events |
| **CloudWatch** | Dashboards & alarms | Per metric/alarm |
| **Athena** | Self-service queries | $5 per TB scanned |
| **API Gateway** | REST API | $3.50 per 1M calls |
| **SNS** | Alerts & notifications | $0.50 per 1M messages |
| **Glue Schema Registry** | Schema management | Free |

> 💡 **For a typical dev/staging environment with moderate traffic, expect $0-5/month.**

## Quick Start

### Prerequisites

- AWS CLI v2 configured
- Python 3.12+
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)

### Deploy

```bash
git clone https://github.com/ingmarma/data-platform-toolkit.git
cd data-platform-toolkit

# Install dependencies
pip install -r requirements.txt

# Deploy to dev (default: us-east-1)
./scripts/deploy.sh

# Deploy to staging
./scripts/deploy.sh staging

# Deploy to production in a specific region
./scripts/deploy.sh prod us-east-1
```

### Run Tests

```bash
pytest              # All modules
pytest tests/test_validator.py    # Schema Validator only
pytest tests/test_quality.py      # Quality Engine only
pytest tests/test_observability.py # Pipeline Observability only
pytest tests/test_queries.py      # Self-Service Queries only
```

## Project Structure

```
data-platform-toolkit/
├── schema-validator/
│   └── src/
│       ├── handler.py              # S3 event → validate → pass/quarantine
│       ├── validator.py            # JSON Schema + Avro validation engine
│       └── breaking_changes.py     # Schema version diff detection
├── quality-engine/
│   └── src/
│       ├── handler.py              # Scheduled quality check orchestrator
│       ├── freshness.py            # SLA freshness monitoring
│       ├── volume.py               # Volume anomaly detection (statistical)
│       └── null_monitor.py         # Per-column null rate tracking
├── pipeline-observability/
│   └── src/
│       ├── handler.py              # EventBridge event consumer
│       ├── metrics.py              # DynamoDB + CloudWatch publisher
│       └── cost_estimator.py       # Per-service cost calculator
├── self-service-queries/
│   ├── src/
│   │   ├── handler.py              # API Gateway REST handler
│   │   ├── executor.py             # Parameterized Athena executor
│   │   └── analytics.py            # Query usage tracking
│   └── sql/
│       ├── daily_summary.sql       # Example: daily dataset health
│       └── top_customers.sql       # Example: customer activity report
├── tests/
│   ├── test_validator.py           # Schema validation + breaking changes
│   ├── test_quality.py             # Freshness, volume, null rates
│   ├── test_observability.py       # Cost estimation + metrics
│   └── test_queries.py             # SQL injection prevention + API
├── infra/
│   └── template.yaml              # SAM/CloudFormation (all resources)
├── scripts/
│   └── deploy.sh                  # One-command deploy to any environment
├── docs/
│   └── architecture.md            # Detailed architecture documentation
├── requirements.txt
├── pytest.ini
└── LICENSE
```

## Key Design Decisions

| Decision | Why |
|----------|-----|
| **ARM64 Lambda** | 20% cheaper, faster cold starts |
| **DynamoDB On-Demand** | Zero cost at rest, scales automatically |
| **EventBridge over SQS** | Native AWS service integration, no polling |
| **Athena WorkGroup isolation** | Cost limits + result separation per consumer |
| **Parameterized templates** | SQL injection prevention without sacrificing flexibility |
| **Composite quality score** | Single number for executive dashboards, breakdown for debugging |

## Related Projects

- [serverless-data-pipeline](https://github.com/ingmarma/serverless-data-pipeline) — The foundation: S3 → Glue → Athena pipeline with CloudFormation

## Contributing

Contributions are welcome! Please open an issue first to discuss what you'd like to change.

## License

MIT — see [LICENSE](LICENSE).

---

**Built by [Matias Martinez](https://github.com/ingmarma)** — Data Platform Engineer

[![GitHub](https://img.shields.io/badge/GitHub-@ingmarma-181717?logo=github)](https://github.com/ingmarma)
[![Instagram](https://img.shields.io/badge/Instagram-@marmatech.dev-E4405F?logo=instagram&logoColor=white)](https://instagram.com/marmatech.dev)
[![X](https://img.shields.io/badge/X-@marmatechdev-000000?logo=x&logoColor=white)](https://x.com/marmatechdev)
