"""
citeflex/lambda_config.py

Lambda configuration with multi-region support (US + EU).

This module provides centralized configuration for:
- Multi-region deployment (us-east-1, eu-west-1)
- API provider settings
- Cost tracking configuration
- SOC 2 compliance settings
- GDPR compliance settings

Environment Variables:
    AWS_REGION: Current AWS region (us-east-1 or eu-west-1)
    ENVIRONMENT: development, staging, or production
    
    # API Keys (stored in AWS Secrets Manager in production)
    OPENAI_API_KEY: OpenAI API key for GPT-5.2
    ANTHROPIC_API_KEY: Anthropic API key for Opus 4.5
    
    # Feature Flags
    ENABLE_COST_TRACKING: Enable detailed cost tracking (default: true)
    ENABLE_AUDIT_LOGGING: Enable SOC 2 audit logging (default: true)

Version History:
    2025-12-20 V1.0: Initial multi-region configuration
"""

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any
from enum import Enum


# =============================================================================
# ENVIRONMENT DETECTION
# =============================================================================

class Environment(Enum):
    """Deployment environments."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Region(Enum):
    """Supported AWS regions."""
    US_EAST_1 = "us-east-1"      # US users
    EU_WEST_1 = "eu-west-1"      # EU users (Ireland)


def get_environment() -> Environment:
    """Get current environment from env var."""
    env = os.environ.get('ENVIRONMENT', 'development').lower()
    return Environment(env) if env in [e.value for e in Environment] else Environment.DEVELOPMENT


def get_region() -> Region:
    """Get current AWS region from env var."""
    region = os.environ.get('AWS_REGION', 'us-east-1')
    return Region(region) if region in [r.value for r in Region] else Region.US_EAST_1


ENVIRONMENT = get_environment()
AWS_REGION = get_region()


# =============================================================================
# REGION-SPECIFIC CONFIGURATION
# =============================================================================

@dataclass
class RegionConfig:
    """Configuration specific to an AWS region."""
    region: Region
    s3_bucket: str
    dynamodb_table_prefix: str
    cloudwatch_log_group: str
    secrets_manager_prefix: str
    
    # Data residency
    data_residency: str  # "US" or "EU"
    gdpr_applies: bool


# Region configurations
REGION_CONFIGS: Dict[Region, RegionConfig] = {
    Region.US_EAST_1: RegionConfig(
        region=Region.US_EAST_1,
        s3_bucket="citategenie-documents-us",
        dynamodb_table_prefix="citategenie-us",
        cloudwatch_log_group="/citategenie/us-east-1",
        secrets_manager_prefix="citategenie/us",
        data_residency="US",
        gdpr_applies=False
    ),
    Region.EU_WEST_1: RegionConfig(
        region=Region.EU_WEST_1,
        s3_bucket="citategenie-documents-eu",
        dynamodb_table_prefix="citategenie-eu",
        cloudwatch_log_group="/citategenie/eu-west-1",
        secrets_manager_prefix="citategenie/eu",
        data_residency="EU",
        gdpr_applies=True
    ),
}


def get_region_config() -> RegionConfig:
    """Get configuration for current region."""
    return REGION_CONFIGS.get(AWS_REGION, REGION_CONFIGS[Region.US_EAST_1])


# =============================================================================
# API PROVIDER CONFIGURATION
# =============================================================================

@dataclass
class AIProviderConfig:
    """Configuration for an AI provider."""
    name: str
    model: str
    api_key_env: str
    input_price_per_1m: float   # $ per 1M input tokens
    output_price_per_1m: float  # $ per 1M output tokens
    timeout_seconds: int
    max_retries: int


# AI Provider configurations (December 2025 pricing)
AI_PROVIDERS = {
    "opus_4.5": AIProviderConfig(
        name="Anthropic Opus 4.5",
        model="claude-opus-4-5-20251101",
        api_key_env="ANTHROPIC_API_KEY",
        input_price_per_1m=15.00,
        output_price_per_1m=75.00,
        timeout_seconds=30,
        max_retries=2
    ),
    "gpt_5.2": AIProviderConfig(
        name="OpenAI GPT-5.2",
        model="gpt-5.2",
        api_key_env="OPENAI_API_KEY",
        input_price_per_1m=1.75,
        output_price_per_1m=14.00,
        timeout_seconds=30,
        max_retries=2
    ),
    # Fallback options if needed
    "gpt_5_mini": AIProviderConfig(
        name="OpenAI GPT-5 mini",
        model="gpt-5-mini",
        api_key_env="OPENAI_API_KEY",
        input_price_per_1m=0.25,
        output_price_per_1m=2.00,
        timeout_seconds=30,
        max_retries=2
    ),
}

# Current AI provider selection
GIST_PROVIDER = "opus_4.5"      # Best accuracy for document context
LOOKUP_PROVIDER = "gpt_5.2"     # Best accuracy-to-cost for citation lookup


def get_ai_provider(provider_key: str) -> AIProviderConfig:
    """Get AI provider configuration."""
    return AI_PROVIDERS.get(provider_key, AI_PROVIDERS["gpt_5.2"])


def get_api_key(provider_key: str) -> Optional[str]:
    """Get API key for a provider from environment."""
    config = get_ai_provider(provider_key)
    return os.environ.get(config.api_key_env)


# =============================================================================
# COST TRACKING CONFIGURATION
# =============================================================================

@dataclass
class CostConfig:
    """Configuration for cost tracking and billing."""
    credit_interval_usd: float = 0.05  # $0.05 per credit
    min_credits_per_document: int = 1
    
    # No hard ceiling - user pays via credits
    # credits_charged = ceil(total_cost / credit_interval_usd)


COST_CONFIG = CostConfig()


def calculate_credits(cost_usd: float) -> int:
    """
    Calculate credits to charge based on API cost.
    
    Formula: ceil(cost / $0.05)
    Minimum: 1 credit
    
    Examples:
        $0.01 -> 1 credit
        $0.05 -> 1 credit
        $0.06 -> 2 credits
        $0.10 -> 2 credits
        $0.41 -> 9 credits
    """
    import math
    if cost_usd <= 0:
        return COST_CONFIG.min_credits_per_document
    
    credits = math.ceil(cost_usd / COST_CONFIG.credit_interval_usd)
    return max(COST_CONFIG.min_credits_per_document, credits)


# =============================================================================
# CITATION STYLE CONFIGURATION
# =============================================================================

class CitationOutputFormat(Enum):
    """Output format types."""
    FOOTNOTE = "footnote"       # Footnotes/endnotes with bibliography
    AUTHOR_DATE = "author_date"  # Parenthetical + References section


# Style to output format mapping
STYLE_OUTPUT_FORMAT: Dict[str, CitationOutputFormat] = {
    # Footnote styles
    "chicago manual of style": CitationOutputFormat.FOOTNOTE,
    "chicago": CitationOutputFormat.FOOTNOTE,
    "bluebook": CitationOutputFormat.FOOTNOTE,
    "oscola": CitationOutputFormat.FOOTNOTE,
    
    # Author-date styles
    "apa 7": CitationOutputFormat.AUTHOR_DATE,
    "apa": CitationOutputFormat.AUTHOR_DATE,
    "mla 9": CitationOutputFormat.AUTHOR_DATE,
    "mla": CitationOutputFormat.AUTHOR_DATE,
    "asa": CitationOutputFormat.AUTHOR_DATE,
    "chicago author-date": CitationOutputFormat.AUTHOR_DATE,
    "harvard": CitationOutputFormat.AUTHOR_DATE,
    "vancouver": CitationOutputFormat.AUTHOR_DATE,
}


def get_output_format(style: str) -> CitationOutputFormat:
    """Get output format for a citation style."""
    return STYLE_OUTPUT_FORMAT.get(
        style.lower().strip(), 
        CitationOutputFormat.FOOTNOTE
    )


def is_author_date_style(style: str) -> bool:
    """Check if style produces author-date output."""
    return get_output_format(style) == CitationOutputFormat.AUTHOR_DATE


def is_footnote_style(style: str) -> bool:
    """Check if style produces footnote output."""
    return get_output_format(style) == CitationOutputFormat.FOOTNOTE


# =============================================================================
# PROCESSING CONFIGURATION
# =============================================================================

@dataclass
class ProcessingConfig:
    """Configuration for document processing."""
    # Parallel processing
    max_parallel_lookups: int = 20  # Max concurrent citation lookups
    lookup_timeout_seconds: int = 30  # Timeout per citation lookup
    
    # Document limits
    max_document_size_mb: int = 16
    max_citations_per_document: int = 500
    
    # Retry configuration
    max_retries_per_citation: int = 2
    retry_delay_seconds: float = 1.0
    
    # Cache TTL
    citation_cache_ttl_hours: int = 24


PROCESSING_CONFIG = ProcessingConfig()


# =============================================================================
# SOC 2 / GDPR CONFIGURATION
# =============================================================================

@dataclass
class ComplianceConfig:
    """Configuration for SOC 2 and GDPR compliance."""
    # Audit logging
    enable_audit_logging: bool = True
    audit_log_retention_days: int = 365  # 1 year for SOC 2
    security_log_retention_days: int = 2555  # 7 years for legal
    
    # Data retention
    document_retention_days: int = 30
    user_data_retention_days: int = 365  # After account deletion
    
    # GDPR
    gdpr_data_export_format: str = "json"
    gdpr_deletion_confirmation_required: bool = True
    
    # Security
    require_mfa_for_admin: bool = True
    session_timeout_minutes: int = 60
    max_failed_login_attempts: int = 5
    lockout_duration_minutes: int = 30


def get_compliance_config() -> ComplianceConfig:
    """Get compliance configuration, adjusted for environment."""
    config = ComplianceConfig()
    
    # Relaxed settings for development
    if ENVIRONMENT == Environment.DEVELOPMENT:
        config.enable_audit_logging = os.environ.get('ENABLE_AUDIT_LOGGING', 'true').lower() == 'true'
        config.require_mfa_for_admin = False
        config.session_timeout_minutes = 480  # 8 hours for dev
    
    return config


COMPLIANCE_CONFIG = get_compliance_config()


# =============================================================================
# FEATURE FLAGS
# =============================================================================

@dataclass
class FeatureFlags:
    """Feature flags for gradual rollout."""
    enable_parallel_lookup: bool = True
    enable_author_date_transform: bool = True
    enable_cost_tracking: bool = True
    enable_gdpr_endpoints: bool = True
    enable_credit_billing: bool = True
    
    # Experimental features
    enable_user_edited_lookup: bool = True  # Look up user-edited text


def get_feature_flags() -> FeatureFlags:
    """Get feature flags from environment."""
    return FeatureFlags(
        enable_parallel_lookup=os.environ.get('ENABLE_PARALLEL_LOOKUP', 'true').lower() == 'true',
        enable_author_date_transform=os.environ.get('ENABLE_AUTHOR_DATE_TRANSFORM', 'true').lower() == 'true',
        enable_cost_tracking=os.environ.get('ENABLE_COST_TRACKING', 'true').lower() == 'true',
        enable_gdpr_endpoints=os.environ.get('ENABLE_GDPR_ENDPOINTS', 'true').lower() == 'true',
        enable_credit_billing=os.environ.get('ENABLE_CREDIT_BILLING', 'true').lower() == 'true',
        enable_user_edited_lookup=os.environ.get('ENABLE_USER_EDITED_LOOKUP', 'true').lower() == 'true',
    )


FEATURE_FLAGS = get_feature_flags()


# =============================================================================
# SUBPROCESSOR DOCUMENTATION
# =============================================================================

# This is documentation for SOC 2 auditors and privacy policy
SUBPROCESSORS = [
    {
        "name": "Amazon Web Services (AWS)",
        "purpose": "Infrastructure hosting (compute, storage, database)",
        "data_processed": "All user data",
        "location": "US (us-east-1) and EU (eu-west-1)",
        "dpa_status": "Included in AWS Enterprise Agreement",
        "soc2_certified": True,
    },
    {
        "name": "OpenAI",
        "purpose": "AI-powered citation lookup (GPT-5.2)",
        "data_processed": "Citation text, document excerpts",
        "location": "US",
        "dpa_status": "Requires signing via OpenAI DPA form",
        "soc2_certified": True,
        "no_training_on_data": True,
        "retention_days": 30,
    },
    {
        "name": "Anthropic",
        "purpose": "AI-powered document gist extraction (Opus 4.5)",
        "data_processed": "Document excerpts (first 1000 chars)",
        "location": "US",
        "dpa_status": "Auto-included in Commercial Terms",
        "soc2_certified": True,
        "no_training_on_data": True,
    },
    {
        "name": "Stripe",
        "purpose": "Payment processing",
        "data_processed": "Payment information, billing details",
        "location": "US",
        "dpa_status": "Included in Stripe Agreement",
        "soc2_certified": True,
        "pci_compliant": True,
    },
]


def get_subprocessor_list() -> list:
    """Get list of subprocessors for compliance documentation."""
    return SUBPROCESSORS


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Environment
    'ENVIRONMENT',
    'AWS_REGION',
    'get_environment',
    'get_region',
    
    # Region config
    'RegionConfig',
    'get_region_config',
    
    # AI providers
    'AIProviderConfig',
    'AI_PROVIDERS',
    'GIST_PROVIDER',
    'LOOKUP_PROVIDER',
    'get_ai_provider',
    'get_api_key',
    
    # Cost
    'COST_CONFIG',
    'calculate_credits',
    
    # Styles
    'CitationOutputFormat',
    'get_output_format',
    'is_author_date_style',
    'is_footnote_style',
    
    # Processing
    'PROCESSING_CONFIG',
    
    # Compliance
    'COMPLIANCE_CONFIG',
    'get_compliance_config',
    
    # Features
    'FEATURE_FLAGS',
    'get_feature_flags',
    
    # Subprocessors
    'SUBPROCESSORS',
    'get_subprocessor_list',
]
