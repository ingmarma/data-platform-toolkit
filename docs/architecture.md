# Architecture

## Overview

Data Platform Toolkit is a modular, serverless framework for building
production-grade data platforms on AWS. Each module operates independently
but integrates through shared AWS services.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                                 │
│    APIs  ·  Databases  ·  S3 Uploads  ·  Streaming                 │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    SCHEMA VALIDATOR                                  │
│  S3 Event → Lambda → Validate against Glue Schema Registry          │
│           → Valid files pass through                                │
│           → Invalid files → Quarantine bucket + SNS alert           │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    QUALITY ENGINE                                    │
│  EventBridge Schedule → Lambda (hourly)                             │
│    ├── Freshness Check   → Is data within SLA?                      │
│    ├── Volume Anomaly    → 50% drop or 3x spike?                    │
│    └── Null Rate Monitor → Columns within thresholds?               │
│                                                                     │
│  Score = Freshness(30%) + Volume(30%) + Nulls(40%)                  │
│  Results → DynamoDB + SNS alerts on failures                        │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 PIPELINE OBSERVABILITY                               │
│  EventBridge → Lambda                                               │
│    ├── Glue Job events      → Duration, cost, status                │
│    ├── Step Function events → Execution tracking                    │
│    └── Custom events        → Records, stages, Athena bytes         │
│                                                                     │
│  Metrics → DynamoDB (history) + CloudWatch (dashboards/alarms)      │
│  Cost estimates: Glue DPU-hours, Athena TB scanned, Lambda GB-sec   │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 SELF-SERVICE QUERIES                                 │
│  API Gateway → Lambda                                               │
│    POST /query       → Execute named template with parameters       │
│    GET  /query/{id}  → Check status / download results              │
│    GET  /queries     → List available templates                     │
│    GET  /usage       → Query analytics                              │
│                                                                     │
│  SQL injection prevention via parameterized templates               │
│  10 GB scan limit per query · Athena workgroup isolation            │
│  Usage tracking in DynamoDB for adoption metrics                    │
└─────────────────────────────────────────────────────────────────────┘
```

## AWS Services Used

| Service             | Purpose                        | Estimated Cost |
|---------------------|--------------------------------|----------------|
| Lambda (ARM64)      | All compute                    | ~$0/month*     |
| DynamoDB (On-Demand)| Metrics, templates, usage      | ~$0/month*     |
| S3                  | Data lake, quarantine, results | ~$0/month*     |
| EventBridge         | Pipeline event routing         | $0/month       |
| CloudWatch          | Dashboards, alarms             | ~$0/month*     |
| Athena              | Self-service queries           | $5/TB scanned  |
| SNS                 | Alerts                         | ~$0/month*     |
| API Gateway         | REST API                       | ~$0/month*     |
| Glue Schema Registry| Schema management              | $0/month       |

*Within AWS Free Tier for typical development usage.

## Security Model

- **Least privilege IAM**: Each Lambda has only the permissions it needs
- **Athena workgroup isolation**: Query cost limits and result isolation
- **SQL injection prevention**: Parameterized templates with strict validation
- **S3 quarantine**: Invalid data never enters the clean data lake
- **API Gateway authorizer**: Cognito/IAM authentication for query API

## Deployment

Uses AWS SAM (Serverless Application Model):

```bash
# Deploy to dev
./scripts/deploy.sh dev

# Deploy to production
./scripts/deploy.sh prod us-east-1
```

Each environment gets isolated resources (tables, buckets, functions)
with environment-specific naming: `dpt-*-{env}`.
