# CitateGenie Lambda Deployment Guide

## Overview

This guide covers deploying CitateGenie's Lambda infrastructure to AWS with SOC 2 and GDPR compliance.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         CloudFront                               │
│                      (CDN + WAF + DDoS)                          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway                               │
│               (REST API + Throttling + Logging)                  │
└─────────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │ Process  │ │  GDPR    │ │  GDPR    │
              │ Document │ │  Export  │ │  Delete  │
              │  Lambda  │ │  Lambda  │ │  Lambda  │
              └──────────┘ └──────────┘ └──────────┘
                    │           │           │
                    └───────────┼───────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│     S3       │      │    Aurora    │      │   Secrets    │
│  Documents   │      │  Serverless  │      │   Manager    │
│              │      │  PostgreSQL  │      │              │
└──────────────┘      └──────────────┘      └──────────────┘
```

## Prerequisites

### 1. AWS Account Setup

- AWS account with admin access
- AWS CLI installed and configured
- SAM CLI installed (`pip install aws-sam-cli`)

### 2. API Keys

Obtain API keys from:
- **OpenAI**: https://platform.openai.com/api-keys
- **Anthropic**: https://console.anthropic.com/
- **Stripe** (for payments): https://dashboard.stripe.com/apikeys

### 3. Sign Data Processing Agreements

**Required for SOC 2:**

| Provider | DPA Location |
|----------|--------------|
| OpenAI | https://openai.com/policies/data-processing-addendum/ |
| Anthropic | Auto-included in Commercial Terms |
| Stripe | Auto-included in Stripe Agreement |
| AWS | Included in Enterprise Agreement |

## Deployment Steps

### Step 1: Clone and Configure

```bash
cd citategenie
cp .env.example .env
```

Edit `.env`:
```bash
ENVIRONMENT=production
AWS_REGION=us-east-1
ALERT_EMAIL=your-email@company.com
```

### Step 2: Create Secrets

Store API keys in AWS Secrets Manager:

```bash
# OpenAI
aws secretsmanager create-secret \
    --name citategenie/production/openai-api-key \
    --secret-string '{"api_key":"sk-...your-key..."}'

# Anthropic
aws secretsmanager create-secret \
    --name citategenie/production/anthropic-api-key \
    --secret-string '{"api_key":"sk-ant-...your-key..."}'

# Stripe
aws secretsmanager create-secret \
    --name citategenie/production/stripe-api-key \
    --secret-string '{"api_key":"sk_live_...your-key..."}'
```

### Step 3: Deploy Infrastructure

```bash
# Build
sam build

# Deploy to US region
sam deploy \
    --stack-name citategenie-us-production \
    --parameter-overrides \
        Environment=production \
        Region=us-east-1 \
        AlertEmail=alerts@citategenie.com \
    --capabilities CAPABILITY_IAM \
    --confirm-changeset

# Deploy to EU region (for GDPR)
sam deploy \
    --stack-name citategenie-eu-production \
    --region eu-west-1 \
    --parameter-overrides \
        Environment=production \
        Region=eu-west-1 \
        AlertEmail=alerts@citategenie.com \
    --capabilities CAPABILITY_IAM \
    --confirm-changeset
```

### Step 4: Initialize Database

```bash
# Connect to Aurora
psql -h <aurora-endpoint> -U citategenie_admin -d citategenie

# Run schema
\i infrastructure/schema.sql
```

### Step 5: Verify Deployment

```bash
# Get API endpoint
aws cloudformation describe-stacks \
    --stack-name citategenie-us-production \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
    --output text

# Test health check
curl https://<api-endpoint>/health
```

## Multi-Region Setup

### US Region (us-east-1)
- Default for US users
- Primary region

### EU Region (eu-west-1)
- For EU users (GDPR compliance)
- Data never leaves EU

### Routing Users to Correct Region

Users are routed based on:
1. Account setting (user chooses)
2. Billing address country
3. Default: US region

## Monitoring

### CloudWatch Dashboards

Create dashboard for:
- Lambda invocations and errors
- API Gateway latency
- Aurora connections
- S3 storage usage
- Cost tracking

### Alerts

Pre-configured alerts:
- Processing errors > 5 in 5 minutes
- Daily cost > $100
- Security events (high/critical)
- Failed authentications

### Log Retention (SOC 2)

| Log Type | Retention |
|----------|-----------|
| Audit logs | 7 years |
| Security logs | 7 years |
| API access logs | 1 year |
| Application logs | 90 days |

## Security

### Encryption

| Data State | Encryption |
|------------|------------|
| At rest (S3) | AES-256 (SSE-S3) |
| At rest (Aurora) | AES-256 |
| In transit | TLS 1.2+ |
| Secrets | AWS KMS |

### Network

- Lambda runs in VPC
- Aurora in private subnets
- No public IP on resources
- NAT Gateway for outbound

### Access Control

- IAM roles with least privilege
- Secrets Manager for credentials
- No hardcoded keys

## Cost Estimation

### Monthly Costs (Estimated)

| Resource | Low Usage | Medium | High |
|----------|-----------|--------|------|
| Lambda | $5 | $50 | $200 |
| API Gateway | $5 | $20 | $100 |
| Aurora Serverless | $15 | $50 | $200 |
| S3 | $5 | $20 | $100 |
| NAT Gateway | $35 | $35 | $35 |
| CloudWatch | $5 | $20 | $50 |
| **Total** | **~$70** | **~$195** | **~$685** |

### AI API Costs (Pass-through)

| Provider | Model | Cost |
|----------|-------|------|
| Anthropic | Opus 4.5 | ~$0.006/doc (gist) |
| OpenAI | GPT-5.2 | ~$0.002/citation |

## Rollback

### Quick Rollback

```bash
# Rollback to previous version
sam rollback --stack-name citategenie-us-production
```

### Full Rollback

```bash
# Delete stack (preserves S3 and Aurora with DeletionPolicy: Retain)
sam delete --stack-name citategenie-us-production
```

## Troubleshooting

### Lambda Timeout

If processing times out:
1. Check CloudWatch logs
2. Verify AI API connectivity
3. Increase memory (more CPU)

### Database Connection

If Aurora connection fails:
1. Verify security group rules
2. Check Lambda VPC config
3. Verify credentials in Secrets Manager

### API Gateway 5xx

If API returns 500:
1. Check Lambda logs
2. Verify IAM permissions
3. Check VPC/NAT connectivity

## SOC 2 Audit Preparation

### Evidence Collection

1. **Access Control**: IAM policies, role assignments
2. **Logging**: CloudWatch logs, CloudTrail
3. **Encryption**: KMS key policies, S3 bucket policies
4. **Change Management**: CloudFormation history, Git history
5. **Incident Response**: SNS alerts, runbooks

### Vanta Integration

1. Connect AWS account to Vanta
2. Enable automatic evidence collection
3. Map controls to SOC 2 criteria

## Support

- **Technical Issues**: Create GitHub issue
- **Security Concerns**: security@citategenie.com
- **Billing**: billing@citategenie.com
