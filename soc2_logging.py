"""
citeflex/soc2_logging.py

SOC 2 compliant audit logging framework.

This module provides comprehensive audit logging for SOC 2 Type II compliance,
designed to integrate with Vanta and similar compliance automation platforms.

SOC 2 Trust Service Criteria Addressed:
    - CC6.1: Logical access controls are implemented
    - CC6.2: Prior to access, users are identified and authenticated
    - CC6.3: Registered and authorized users' access is removed timely
    - CC7.1: Security events are logged and monitored
    - CC7.2: Anomalies are identified and addressed

GDPR Requirements Addressed:
    - Article 30: Records of processing activities
    - Article 33: Breach notification (incident logging)

Log Structure:
    All logs follow a consistent JSON structure for automated parsing:
    {
        "timestamp": "ISO 8601 UTC",
        "service": "citategenie",
        "environment": "production|staging",
        "region": "us-east-1|eu-west-1",
        "request_id": "unique trace ID",
        "user_id_hash": "SHA-256 hash for privacy",
        "action": "action category",
        "resource": "resource identifier",
        "outcome": "success|failure|denied",
        "details": { ... action-specific data ... }
    }

Usage:
    from soc2_logging import AuditLogger, SecurityEvent
    
    logger = AuditLogger()
    
    # Log document processing
    logger.log_document_process(
        user_id="user_123",
        document_id="doc_456",
        citations_count=47,
        outcome="success",
        cost_usd=0.094
    )
    
    # Log authentication
    logger.log_auth_event(
        user_id="user_123",
        event_type="login",
        outcome="success",
        ip_address="192.168.1.1"
    )

Version History:
    2025-12-20 V1.0: Initial SOC 2 compliant implementation
"""

import os
import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
import uuid


# =============================================================================
# CONFIGURATION
# =============================================================================

# Environment detection
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'development')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'citategenie')

# Log levels by environment
LOG_LEVEL = logging.DEBUG if ENVIRONMENT == 'development' else logging.INFO


# =============================================================================
# ENUMS
# =============================================================================

class ActionCategory(Enum):
    """Categories of auditable actions."""
    # Authentication & Authorization
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_FAILED = "auth.failed"
    AUTH_MFA = "auth.mfa"
    AUTH_TOKEN_REFRESH = "auth.token_refresh"
    AUTH_PASSWORD_CHANGE = "auth.password_change"
    AUTH_PASSWORD_RESET = "auth.password_reset"
    
    # Document Operations
    DOC_UPLOAD = "document.upload"
    DOC_PROCESS = "document.process"
    DOC_DOWNLOAD = "document.download"
    DOC_DELETE = "document.delete"
    DOC_SHARE = "document.share"
    
    # Citation Operations
    CITATION_LOOKUP = "citation.lookup"
    CITATION_ACCEPT = "citation.accept"
    CITATION_REJECT = "citation.reject"
    CITATION_MANUAL = "citation.manual_edit"
    
    # API Operations
    API_CALL_OPENAI = "api.openai"
    API_CALL_ANTHROPIC = "api.anthropic"
    API_CALL_CROSSREF = "api.crossref"
    API_CALL_PUBMED = "api.pubmed"
    
    # Billing Operations
    BILLING_CREDIT_PURCHASE = "billing.credit_purchase"
    BILLING_CREDIT_SPEND = "billing.credit_spend"
    BILLING_SUBSCRIPTION = "billing.subscription"
    
    # Admin Operations
    ADMIN_USER_CREATE = "admin.user_create"
    ADMIN_USER_DELETE = "admin.user_delete"
    ADMIN_USER_SUSPEND = "admin.user_suspend"
    ADMIN_SETTINGS_CHANGE = "admin.settings_change"
    
    # GDPR Data Subject Rights
    GDPR_DATA_EXPORT = "gdpr.data_export"
    GDPR_DATA_DELETE = "gdpr.data_delete"
    GDPR_CONSENT_UPDATE = "gdpr.consent_update"
    
    # Security Events
    SECURITY_ANOMALY = "security.anomaly"
    SECURITY_BREACH_ATTEMPT = "security.breach_attempt"
    SECURITY_RATE_LIMIT = "security.rate_limit"


class Outcome(Enum):
    """Possible outcomes for audited actions."""
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    PARTIAL = "partial"
    TIMEOUT = "timeout"


class Severity(Enum):
    """Severity levels for security events."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class AuditEvent:
    """
    Structured audit event for SOC 2 compliance.
    
    All fields are designed to be:
    - Immutable once created
    - JSON serializable
    - Privacy-preserving (PII is hashed)
    - Queryable for compliance reporting
    """
    # Required fields
    timestamp: str
    service: str
    environment: str
    region: str
    request_id: str
    action: str
    outcome: str
    
    # Optional identification
    user_id_hash: Optional[str] = None
    session_id_hash: Optional[str] = None
    
    # Resource identification
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    
    # Request context
    ip_address_hash: Optional[str] = None
    user_agent_hash: Optional[str] = None
    
    # Performance metrics
    duration_ms: Optional[int] = None
    
    # Action-specific details
    details: Dict[str, Any] = field(default_factory=dict)
    
    # Security classification
    severity: str = "info"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = asdict(self)
        return {k: v for k, v in result.items() if v is not None}
    
    def to_json(self) -> str:
        """Convert to JSON string for logging."""
        return json.dumps(self.to_dict(), default=str)


@dataclass
class SecurityEvent(AuditEvent):
    """
    Extended audit event for security-specific logging.
    
    Used for:
    - Failed authentication attempts
    - Rate limiting triggers
    - Anomaly detection
    - Potential breach attempts
    """
    threat_type: Optional[str] = None
    source_ip: Optional[str] = None  # May be stored unhashed for security investigation
    blocked: bool = False
    alert_triggered: bool = False


# =============================================================================
# AUDIT LOGGER
# =============================================================================

class AuditLogger:
    """
    SOC 2 compliant audit logger.
    
    Features:
    - Structured JSON logging for automated parsing
    - PII hashing for privacy
    - Request tracing via request_id
    - Multi-region support
    - Vanta-compatible format
    
    Usage:
        logger = AuditLogger()
        logger.log_document_process(user_id="123", document_id="456", ...)
    """
    
    def __init__(
        self,
        service_name: str = SERVICE_NAME,
        environment: str = ENVIRONMENT,
        region: str = AWS_REGION
    ):
        self.service_name = service_name
        self.environment = environment
        self.region = region
        
        # Configure Python logger
        self._logger = logging.getLogger(f"{service_name}.audit")
        self._logger.setLevel(LOG_LEVEL)
        
        # Ensure we have a handler
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(message)s'))
            self._logger.addHandler(handler)
    
    # =========================================================================
    # CORE LOGGING METHODS
    # =========================================================================
    
    def log_event(
        self,
        action: ActionCategory,
        outcome: Outcome,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        duration_ms: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        severity: Severity = Severity.INFO,
        request_id: Optional[str] = None
    ) -> AuditEvent:
        """
        Log a generic audit event.
        
        This is the base method - use specific methods like log_document_process()
        for better type safety and consistency.
        """
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            service=self.service_name,
            environment=self.environment,
            region=self.region,
            request_id=request_id or self._generate_request_id(),
            action=action.value if isinstance(action, ActionCategory) else action,
            outcome=outcome.value if isinstance(outcome, Outcome) else outcome,
            user_id_hash=self._hash_pii(user_id) if user_id else None,
            session_id_hash=self._hash_pii(session_id) if session_id else None,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address_hash=self._hash_pii(ip_address) if ip_address else None,
            user_agent_hash=self._hash_pii(user_agent) if user_agent else None,
            duration_ms=duration_ms,
            details=details or {},
            severity=severity.value if isinstance(severity, Severity) else severity
        )
        
        # Output to logger (CloudWatch in production)
        self._logger.info(event.to_json())
        
        return event
    
    # =========================================================================
    # AUTHENTICATION EVENTS
    # =========================================================================
    
    def log_auth_event(
        self,
        event_type: str,  # "login", "logout", "failed", "mfa"
        outcome: Outcome,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        failure_reason: Optional[str] = None,
        request_id: Optional[str] = None
    ) -> AuditEvent:
        """Log authentication-related events."""
        action_map = {
            "login": ActionCategory.AUTH_LOGIN,
            "logout": ActionCategory.AUTH_LOGOUT,
            "failed": ActionCategory.AUTH_FAILED,
            "mfa": ActionCategory.AUTH_MFA,
            "token_refresh": ActionCategory.AUTH_TOKEN_REFRESH,
            "password_change": ActionCategory.AUTH_PASSWORD_CHANGE,
            "password_reset": ActionCategory.AUTH_PASSWORD_RESET,
        }
        
        action = action_map.get(event_type, ActionCategory.AUTH_LOGIN)
        severity = Severity.HIGH if outcome == Outcome.FAILURE else Severity.INFO
        
        details = {}
        if failure_reason:
            details["failure_reason"] = failure_reason
        
        return self.log_event(
            action=action,
            outcome=outcome,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
            severity=severity,
            request_id=request_id
        )
    
    # =========================================================================
    # DOCUMENT EVENTS
    # =========================================================================
    
    def log_document_upload(
        self,
        user_id: str,
        document_id: str,
        file_size_bytes: int,
        file_type: str,
        outcome: Outcome,
        request_id: Optional[str] = None
    ) -> AuditEvent:
        """Log document upload events."""
        return self.log_event(
            action=ActionCategory.DOC_UPLOAD,
            outcome=outcome,
            user_id=user_id,
            resource_type="document",
            resource_id=document_id,
            details={
                "file_size_bytes": file_size_bytes,
                "file_type": file_type
            },
            request_id=request_id
        )
    
    def log_document_process(
        self,
        user_id: str,
        document_id: str,
        citations_count: int,
        style: str,
        outcome: Outcome,
        duration_ms: int,
        cost_usd: float,
        credits_charged: int,
        ai_calls_count: int = 0,
        request_id: Optional[str] = None
    ) -> AuditEvent:
        """Log document processing events."""
        return self.log_event(
            action=ActionCategory.DOC_PROCESS,
            outcome=outcome,
            user_id=user_id,
            resource_type="document",
            resource_id=document_id,
            duration_ms=duration_ms,
            details={
                "citations_count": citations_count,
                "style": style,
                "cost_usd": round(cost_usd, 6),
                "credits_charged": credits_charged,
                "ai_calls_count": ai_calls_count
            },
            request_id=request_id
        )
    
    def log_document_download(
        self,
        user_id: str,
        document_id: str,
        outcome: Outcome,
        request_id: Optional[str] = None
    ) -> AuditEvent:
        """Log document download events."""
        return self.log_event(
            action=ActionCategory.DOC_DOWNLOAD,
            outcome=outcome,
            user_id=user_id,
            resource_type="document",
            resource_id=document_id,
            request_id=request_id
        )
    
    def log_document_delete(
        self,
        user_id: str,
        document_id: str,
        outcome: Outcome,
        deletion_type: str = "user_requested",  # or "auto_expiry", "gdpr_request"
        request_id: Optional[str] = None
    ) -> AuditEvent:
        """Log document deletion events."""
        return self.log_event(
            action=ActionCategory.DOC_DELETE,
            outcome=outcome,
            user_id=user_id,
            resource_type="document",
            resource_id=document_id,
            details={"deletion_type": deletion_type},
            request_id=request_id
        )
    
    # =========================================================================
    # API CALL EVENTS
    # =========================================================================
    
    def log_api_call(
        self,
        provider: str,  # "openai", "anthropic", "crossref", "pubmed"
        user_id: str,
        document_id: Optional[str],
        outcome: Outcome,
        duration_ms: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        model: Optional[str] = None,
        request_id: Optional[str] = None
    ) -> AuditEvent:
        """Log external API call events for cost tracking and compliance."""
        action_map = {
            "openai": ActionCategory.API_CALL_OPENAI,
            "anthropic": ActionCategory.API_CALL_ANTHROPIC,
            "crossref": ActionCategory.API_CALL_CROSSREF,
            "pubmed": ActionCategory.API_CALL_PUBMED,
        }
        
        action = action_map.get(provider, ActionCategory.API_CALL_OPENAI)
        
        return self.log_event(
            action=action,
            outcome=outcome,
            user_id=user_id,
            resource_type="document",
            resource_id=document_id,
            duration_ms=duration_ms,
            details={
                "provider": provider,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost_usd, 6)
            },
            request_id=request_id
        )
    
    # =========================================================================
    # BILLING EVENTS
    # =========================================================================
    
    def log_credit_purchase(
        self,
        user_id: str,
        credits_purchased: int,
        amount_usd: float,
        payment_method: str,
        outcome: Outcome,
        transaction_id: Optional[str] = None,
        request_id: Optional[str] = None
    ) -> AuditEvent:
        """Log credit purchase events."""
        return self.log_event(
            action=ActionCategory.BILLING_CREDIT_PURCHASE,
            outcome=outcome,
            user_id=user_id,
            resource_type="transaction",
            resource_id=transaction_id,
            details={
                "credits_purchased": credits_purchased,
                "amount_usd": round(amount_usd, 2),
                "payment_method": payment_method
            },
            request_id=request_id
        )
    
    def log_credit_spend(
        self,
        user_id: str,
        credits_spent: int,
        document_id: str,
        remaining_balance: int,
        request_id: Optional[str] = None
    ) -> AuditEvent:
        """Log credit spending events."""
        return self.log_event(
            action=ActionCategory.BILLING_CREDIT_SPEND,
            outcome=Outcome.SUCCESS,
            user_id=user_id,
            resource_type="document",
            resource_id=document_id,
            details={
                "credits_spent": credits_spent,
                "remaining_balance": remaining_balance
            },
            request_id=request_id
        )
    
    # =========================================================================
    # GDPR EVENTS
    # =========================================================================
    
    def log_gdpr_data_export(
        self,
        user_id: str,
        outcome: Outcome,
        data_categories: List[str],
        request_id: Optional[str] = None
    ) -> AuditEvent:
        """Log GDPR data export requests (Article 15 - Right of Access)."""
        return self.log_event(
            action=ActionCategory.GDPR_DATA_EXPORT,
            outcome=outcome,
            user_id=user_id,
            details={"data_categories": data_categories},
            severity=Severity.MEDIUM,
            request_id=request_id
        )
    
    def log_gdpr_data_delete(
        self,
        user_id: str,
        outcome: Outcome,
        data_categories: List[str],
        request_id: Optional[str] = None
    ) -> AuditEvent:
        """Log GDPR data deletion requests (Article 17 - Right to Erasure)."""
        return self.log_event(
            action=ActionCategory.GDPR_DATA_DELETE,
            outcome=outcome,
            user_id=user_id,
            details={"data_categories": data_categories},
            severity=Severity.HIGH,
            request_id=request_id
        )
    
    # =========================================================================
    # SECURITY EVENTS
    # =========================================================================
    
    def log_security_event(
        self,
        event_type: str,  # "anomaly", "breach_attempt", "rate_limit"
        severity: Severity,
        ip_address: Optional[str] = None,
        user_id: Optional[str] = None,
        description: str = "",
        blocked: bool = False,
        request_id: Optional[str] = None
    ) -> AuditEvent:
        """Log security-related events for incident response."""
        action_map = {
            "anomaly": ActionCategory.SECURITY_ANOMALY,
            "breach_attempt": ActionCategory.SECURITY_BREACH_ATTEMPT,
            "rate_limit": ActionCategory.SECURITY_RATE_LIMIT,
        }
        
        action = action_map.get(event_type, ActionCategory.SECURITY_ANOMALY)
        
        # For security events, we may store IP unhashed for investigation
        details = {
            "description": description,
            "blocked": blocked,
            "source_ip": ip_address  # Stored for security investigation
        }
        
        return self.log_event(
            action=action,
            outcome=Outcome.DENIED if blocked else Outcome.SUCCESS,
            user_id=user_id,
            ip_address=ip_address,
            details=details,
            severity=severity,
            request_id=request_id
        )
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def _hash_pii(self, value: str) -> str:
        """
        Hash PII for privacy while maintaining traceability.
        
        Uses SHA-256 with a consistent salt so the same input
        always produces the same hash (for correlation).
        """
        if not value:
            return ""
        
        # Use service name as salt for consistency within service
        salted = f"{self.service_name}:{value}"
        return hashlib.sha256(salted.encode()).hexdigest()[:16]
    
    def _generate_request_id(self) -> str:
        """Generate unique request ID for distributed tracing."""
        return f"req_{uuid.uuid4().hex[:12]}"


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

# Singleton logger for easy import
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def log_document_process(**kwargs) -> AuditEvent:
    """Convenience function for logging document processing."""
    return get_audit_logger().log_document_process(**kwargs)


def log_api_call(**kwargs) -> AuditEvent:
    """Convenience function for logging API calls."""
    return get_audit_logger().log_api_call(**kwargs)


def log_auth_event(**kwargs) -> AuditEvent:
    """Convenience function for logging auth events."""
    return get_audit_logger().log_auth_event(**kwargs)


def log_security_event(**kwargs) -> AuditEvent:
    """Convenience function for logging security events."""
    return get_audit_logger().log_security_event(**kwargs)
