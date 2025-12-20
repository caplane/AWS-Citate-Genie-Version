# CitateGenie AWS Stack

**Version:** 3.0 (Lambda-Ready)  
**Date:** December 20, 2025

## Overview

This package contains CitateGenie ready for AWS Lambda deployment with:
- SOC 2 Type II compliance infrastructure
- Multi-region support (US + EU for GDPR)
- Parallel citation lookup
- Author-date transformation (APA, MLA, Chicago Author-Date)
- Cost tracking and credit-based billing

## New Files for AWS Migration

| File | Purpose |
|------|---------|
| `lambda_processor.py` | Main Lambda entry point with parallel lookup |
| `lambda_config.py` | Multi-region config, AI pricing, feature flags |
| `soc2_logging.py` | SOC 2 compliant audit logging (Vanta-compatible) |
| `author_date_transformer.py` | Superscript→parenthetical transformation |
| `infrastructure/template.yaml` | AWS SAM CloudFormation template |
| `infrastructure/schema.sql` | PostgreSQL database schema |
| `infrastructure/DEPLOYMENT.md` | Step-by-step deployment guide |

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│   API Gateway   │────▶│     Lambda      │
│   (REST API)    │     │  (Processing)   │
└─────────────────┘     └────────┬────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│       S3        │     │     Aurora      │     │    Secrets      │
│   (Documents)   │     │   (PostgreSQL)  │     │    Manager      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Quick Start

### 1. Prerequisites

```bash
# Install AWS SAM CLI
pip install aws-sam-cli

# Configure AWS credentials
aws configure
```

### 2. Store API Keys

```bash
aws secretsmanager create-secret \
    --name citategenie/production/openai-api-key \
    --secret-string '{"api_key":"sk-..."}'

aws secretsmanager create-secret \
    --name citategenie/production/anthropic-api-key \
    --secret-string '{"api_key":"sk-ant-..."}'
```

### 3. Deploy

```bash
cd infrastructure
sam build
sam deploy --guided
```

### 4. Initialize Database

```bash
psql -h <aurora-endpoint> -U citategenie_admin -d citategenie -f schema.sql
```

## Cost Model

| Component | Cost Per |
|-----------|----------|
| Document gist (Opus 4.5) | ~$0.006/document |
| Citation lookup (GPT-5.2) | ~$0.002/citation |
| **Credit** | $0.05 (covers ~8 citations) |

Credits charged: `ceil(total_cost / $0.05)`

## SOC 2 Compliance

- All operations logged to CloudWatch
- PII hashed in logs
- 7-year audit log retention
- Request tracing via request_id
- Vanta-compatible event format

## Multi-Region

| Region | AWS Region | GDPR |
|--------|------------|------|
| US | us-east-1 | No |
| EU | eu-west-1 | Yes |

Data never crosses regions.

## File Structure

```
citategenie-aws-stack/
├── app.py                      # Flask app (Railway bridge)
├── lambda_processor.py         # NEW: Lambda entry point
├── lambda_config.py            # NEW: Multi-region config
├── soc2_logging.py             # NEW: Audit logging
├── author_date_transformer.py  # NEW: APA/MLA transformation
├── unified_router.py           # Citation routing logic
├── document_processor.py       # Word document manipulation
├── models.py                   # Data models
├── config.py                   # Configuration
│
├── engines/                    # Citation lookup engines
│   ├── academic.py             # Crossref, PubMed, OpenAlex
│   ├── books.py                # Google Books, Open Library
│   ├── superlegal.py           # CourtListener
│   ├── ai_lookup.py            # AI fallback
│   └── ...
│
├── formatters/                 # Citation formatters
│   ├── chicago.py
│   ├── apa.py
│   ├── mla.py
│   ├── legal.py
│   └── ...
│
├── processors/                 # Document processors
│   ├── word_document.py
│   └── ...
│
├── infrastructure/             # AWS deployment
│   ├── template.yaml           # SAM template
│   ├── schema.sql              # Database schema
│   └── DEPLOYMENT.md           # Deployment guide
│
└── requirements.txt
```

## Migration Path

### Phase 1: Dual-Run (Current)
- Railway serves production traffic
- Lambda deployed for testing
- Same codebase, different entry points

### Phase 2: Traffic Split
- Route 10% traffic to Lambda
- Monitor errors and latency
- Compare costs

### Phase 3: Full Migration
- Route 100% to Lambda
- Decommission Railway
- Enable auto-scaling

## Required Actions

| Priority | Action |
|----------|--------|
| **High** | Sign OpenAI DPA |
| **High** | Confirm Anthropic Commercial Terms |
| **High** | Review infrastructure/DEPLOYMENT.md |
| **Medium** | Set up Vanta for SOC 2 |
| **Medium** | Configure CloudWatch dashboards |

## Support

- GitHub Issues: [your-repo]
- Email: support@citategenie.com
