"""
citeflex/cost_tracker.py

Database-backed API cost tracking for CitateGenie.

Logs every paid API call to PostgreSQL for analytics and cost analysis.
Replaces the previous CSV-based tracking with persistent database storage.

Usage:
    from cost_tracker import log_api_call, start_document_tracking, finish_document_tracking
    
    # Start tracking a document
    start_document_tracking(session_id='abc123', filename='paper.docx')
    
    # Log API calls during processing
    log_api_call('openai', input_tokens=847, output_tokens=312, 
                 query='Simonton, 1992', function='classify',
                 source_type='parenthetical', citation_type='journal')
    
    # Finish tracking
    summary = finish_document_tracking(citations_resolved=5, citations_failed=1)

Version History:
    2025-12-20 V2.0: Database-backed tracking (replaces CSV)
    2025-12-14 V1.1: Added EMAIL_AFTER_EVERY_CALL for test mode auto-emails
    2025-12-13 V1.0: Initial implementation - CSV logging with cost calculation
"""

import os
from datetime import datetime
from typing import Optional, Dict, Any
from contextlib import contextmanager
import threading

# Thread-local storage for per-document tracking
_thread_local = threading.local()


# =============================================================================
# PRICING (per 1M tokens, updated Dec 2024)
# =============================================================================

PRICING = {
    'gemini': {
        'input': 0.075,    # $0.075 per 1M input tokens (Gemini 2.0 Flash)
        'output': 0.30,    # $0.30 per 1M output tokens
    },
    'openai': {
        'input': 2.50,     # $2.50 per 1M input tokens (GPT-4o)
        'output': 10.00,   # $10.00 per 1M output tokens
    },
    'claude': {
        'input': 3.00,     # $3.00 per 1M input tokens (Claude 3.5 Sonnet)
        'output': 15.00,   # $15.00 per 1M output tokens
    },
    'serpapi': {
        'per_search': 0.01,  # ~$0.01 per search (varies by plan)
    },
}


# =============================================================================
# COST CALCULATION
# =============================================================================

def calculate_cost(provider: str, input_tokens: int = 0, output_tokens: int = 0) -> float:
    """
    Calculate cost in USD for an API call.
    
    Args:
        provider: 'gemini', 'openai', 'claude', or 'serpapi'
        input_tokens: Number of input/prompt tokens
        output_tokens: Number of output/completion tokens
        
    Returns:
        Cost in USD (float)
    """
    provider = provider.lower()
    
    if provider == 'serpapi':
        return PRICING['serpapi']['per_search']
    
    if provider not in PRICING:
        return 0.0
    
    pricing = PRICING[provider]
    
    # Cost = (tokens / 1,000,000) * price_per_million
    input_cost = (input_tokens / 1_000_000) * pricing['input']
    output_cost = (output_tokens / 1_000_000) * pricing['output']
    
    return round(input_cost + output_cost, 8)  # Keep precision for small costs


# =============================================================================
# PER-DOCUMENT TRACKING
# =============================================================================

def _get_current_tracking() -> Dict[str, Any]:
    """Get current document tracking state (thread-safe)."""
    if not hasattr(_thread_local, 'tracking'):
        _thread_local.tracking = {
            'active': False,
            'session_id': None,
            'db_session_id': None,
            'filename': None,
            'user_id': None,
            'style': None,
            'mode': None,
            'is_preview': False,
            'cost': 0.0,
            'calls': 0,
            'started_at': None,
        }
    return _thread_local.tracking


def start_document_tracking(
    session_id: str,
    filename: str = "",
    user_id: Optional[int] = None,
    style: Optional[str] = None,
    mode: Optional[str] = None,
    is_preview: bool = False
) -> Optional[int]:
    """
    Start tracking costs for a new document.
    
    Creates a DocumentSession record in the database.
    
    Args:
        session_id: Your application's session ID
        filename: Document filename
        user_id: User ID (None for anonymous)
        style: Citation style (chicago, apa, etc.)
        mode: Processing mode (footnote, author-date, unified)
        is_preview: Whether this is a preview (free) processing
    
    Returns:
        Database session ID (for linking API calls)
    """
    tracking = _get_current_tracking()
    
    # Reset tracking state
    tracking['active'] = True
    tracking['session_id'] = session_id
    tracking['filename'] = filename
    tracking['user_id'] = user_id
    tracking['style'] = style
    tracking['mode'] = mode
    tracking['is_preview'] = is_preview
    tracking['cost'] = 0.0
    tracking['calls'] = 0
    tracking['started_at'] = datetime.utcnow()
    tracking['db_session_id'] = None
    
    # Create database record
    try:
        from billing.db import get_db
        from billing.admin_models import DocumentSession
        
        db = get_db()
        
        doc_session = DocumentSession(
            session_id=session_id,
            user_id=user_id,
            filename=filename,
            citation_style=style,
            processing_mode=mode,
            is_preview=is_preview,
            status='processing'
        )
        db.add(doc_session)
        db.commit()
        
        tracking['db_session_id'] = doc_session.id
        print(f"[CostTracker] Started tracking: {filename or session_id[:8]} (db_id={doc_session.id})")
        return doc_session.id
        
    except Exception as e:
        print(f"[CostTracker] Warning: Could not create DB session: {e}")
        print(f"[CostTracker] Continuing with in-memory tracking only")
        return None


def get_document_cost() -> Dict[str, Any]:
    """Get current document's cost summary."""
    tracking = _get_current_tracking()
    return {
        'cost': tracking['cost'],
        'calls': tracking['calls'],
        'document': tracking['filename'],
        'session_id': tracking['session_id'],
    }


def finish_document_tracking(
    citations_found: int = 0,
    citations_resolved: int = 0,
    citations_failed: int = 0,
    status: str = 'completed',
    error_message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Finish tracking and update database record.
    
    Args:
        citations_found: Total citations found in document
        citations_resolved: Successfully resolved citations
        citations_failed: Failed to resolve
        status: Final status ('completed', 'failed')
        error_message: Error details if failed
    
    Returns:
        Summary dict with cost, calls, document info
    """
    tracking = _get_current_tracking()
    
    if not tracking['active']:
        return {'cost': 0, 'calls': 0, 'document': ''}
    
    # Calculate processing time
    processing_time_ms = None
    if tracking['started_at']:
        delta = datetime.utcnow() - tracking['started_at']
        processing_time_ms = int(delta.total_seconds() * 1000)
    
    summary = {
        'cost': tracking['cost'],
        'calls': tracking['calls'],
        'document': tracking['filename'],
        'session_id': tracking['session_id'],
        'processing_time_ms': processing_time_ms,
        'citations_found': citations_found,
        'citations_resolved': citations_resolved,
        'citations_failed': citations_failed,
    }
    
    # Update database record
    if tracking['db_session_id']:
        try:
            from billing.db import get_db
            from billing.admin_models import DocumentSession
            
            db = get_db()
            doc_session = db.query(DocumentSession).get(tracking['db_session_id'])
            
            if doc_session:
                doc_session.total_citations_found = citations_found
                doc_session.citations_resolved = citations_resolved
                doc_session.citations_failed = citations_failed
                doc_session.total_cost_usd = tracking['cost']
                doc_session.total_api_calls = tracking['calls']
                doc_session.completed_at = datetime.utcnow()
                doc_session.processing_time_ms = processing_time_ms
                doc_session.status = status
                doc_session.error_message = error_message
                db.commit()
                
        except Exception as e:
            print(f"[CostTracker] Warning: Could not update DB session: {e}")
    
    print(f"[CostTracker] Document '{tracking['filename']}' complete: "
          f"{tracking['calls']} API calls, ${tracking['cost']:.4f}")
    
    # Reset tracking state
    tracking['active'] = False
    tracking['session_id'] = None
    tracking['db_session_id'] = None
    tracking['filename'] = None
    tracking['cost'] = 0.0
    tracking['calls'] = 0
    tracking['started_at'] = None
    
    return summary


# =============================================================================
# API CALL LOGGING
# =============================================================================

def log_api_call(
    provider: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    query: str = '',
    function: str = '',
    source_type: Optional[str] = None,
    citation_type: Optional[str] = None,
    success: bool = True,
    confidence: Optional[float] = None,
    latency_ms: Optional[int] = None,
    error_message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> float:
    """
    Log an API call to the database and return the calculated cost.
    
    Args:
        provider: 'gemini', 'openai', 'claude', 'serpapi', 'crossref', etc.
        input_tokens: Number of input tokens (0 for non-AI APIs)
        output_tokens: Number of output tokens (0 for non-AI APIs)
        query: The citation/search query being processed (truncated to 500 chars)
        function: Which function made the call (e.g., 'classify', 'lookup')
        source_type: Type of source being resolved (url, doi, parenthetical, etc.)
        citation_type: Type of citation (journal, book, legal, etc.)
        success: Whether the call was successful
        confidence: Confidence score (0.0-1.0) for the result
        latency_ms: Response time in milliseconds
        error_message: Error details if failed
        metadata: Additional metadata to store as JSON
        
    Returns:
        Cost in USD for this call
    """
    cost = calculate_cost(provider, input_tokens, output_tokens)
    
    # Clean query for storage
    clean_query = query.replace('\n', ' ').replace('\r', '')[:500] if query else ''
    
    # Print for visibility
    if provider.lower() in ['openai', 'claude', 'gemini']:
        print(f"[CostTracker] {provider}: {input_tokens} in + {output_tokens} out = ${cost:.6f}")
    elif provider.lower() == 'serpapi':
        print(f"[CostTracker] {provider}: 1 search = ${cost:.4f}")
    elif cost > 0:
        print(f"[CostTracker] {provider}: ${cost:.6f}")
    
    # Update in-memory tracking
    tracking = _get_current_tracking()
    if tracking['active']:
        tracking['cost'] += cost
        tracking['calls'] += 1
    
    # Write to database
    try:
        from billing.db import get_db
        from billing.admin_models import APICall
        
        db = get_db()
        
        api_call = APICall(
            document_session_id=tracking.get('db_session_id'),
            provider=provider.lower(),
            endpoint=function,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            source_type=source_type,
            citation_type=citation_type,
            raw_query=clean_query,
            success=success,
            confidence=confidence,
            latency_ms=latency_ms,
            error_message=error_message,
            metadata_json=metadata or {}
        )
        db.add(api_call)
        db.commit()
        
    except Exception as e:
        print(f"[CostTracker] Warning: Could not write to DB: {e}")
    
    return cost


# =============================================================================
# ANALYTICS QUERIES
# =============================================================================

def get_total_cost(days: int = 30) -> Dict[str, Any]:
    """
    Get total cost summary for the specified number of days.
    
    Args:
        days: Number of days to include (default 30)
    
    Returns:
        Dict with total_cost, by_provider breakdown, and call_count
    """
    try:
        from billing.db import get_db
        from billing.admin_models import APICall
        from sqlalchemy import func
        from datetime import timedelta
        
        db = get_db()
        since = datetime.utcnow() - timedelta(days=days)
        
        # Total cost and calls
        totals = db.query(
            func.sum(APICall.cost_usd),
            func.count(APICall.id)
        ).filter(APICall.timestamp >= since).first()
        
        total_cost = totals[0] or 0.0
        call_count = totals[1] or 0
        
        # By provider
        by_provider = {}
        provider_stats = db.query(
            APICall.provider,
            func.sum(APICall.cost_usd),
            func.count(APICall.id)
        ).filter(
            APICall.timestamp >= since
        ).group_by(APICall.provider).all()
        
        for provider, cost, count in provider_stats:
            by_provider[provider] = {
                'cost': cost or 0.0,
                'calls': count or 0
            }
        
        return {
            'total_cost': total_cost,
            'call_count': call_count,
            'by_provider': by_provider,
            'days': days
        }
        
    except Exception as e:
        print(f"[CostTracker] Error getting total cost: {e}")
        return {
            'total_cost': 0,
            'call_count': 0,
            'by_provider': {},
            'days': days
        }


def get_success_rates(days: int = 30) -> Dict[str, float]:
    """
    Get success rates by source type.
    
    Args:
        days: Number of days to include
    
    Returns:
        Dict mapping source_type to success rate (0-100)
    """
    try:
        from billing.db import get_db
        from billing.admin_models import APICall
        from sqlalchemy import func, case
        from datetime import timedelta
        
        db = get_db()
        since = datetime.utcnow() - timedelta(days=days)
        
        rates = db.query(
            APICall.source_type,
            (func.count(case((APICall.success == True, 1))) * 100.0 / 
             func.nullif(func.count(APICall.id), 0)).label('success_rate')
        ).filter(
            APICall.timestamp >= since,
            APICall.source_type.isnot(None)
        ).group_by(APICall.source_type).all()
        
        return {row[0]: round(row[1] or 0, 1) for row in rates}
        
    except Exception as e:
        print(f"[CostTracker] Error getting success rates: {e}")
        return {}


def get_citation_type_distribution(days: int = 30) -> Dict[str, int]:
    """
    Get citation type distribution.
    
    Args:
        days: Number of days to include
    
    Returns:
        Dict mapping citation_type to count
    """
    try:
        from billing.db import get_db
        from billing.admin_models import APICall
        from sqlalchemy import func
        from datetime import timedelta
        
        db = get_db()
        since = datetime.utcnow() - timedelta(days=days)
        
        dist = db.query(
            APICall.citation_type,
            func.count(APICall.id)
        ).filter(
            APICall.timestamp >= since,
            APICall.citation_type.isnot(None)
        ).group_by(APICall.citation_type).all()
        
        return {row[0]: row[1] for row in dist}
        
    except Exception as e:
        print(f"[CostTracker] Error getting citation distribution: {e}")
        return {}


# =============================================================================
# URL FETCH TRACKING (V4.3)
# =============================================================================

def log_url_fetch(
    url: str,
    success: bool,
    resolution_method: str,
    failure_reason: Optional[str] = None,
    domain: Optional[str] = None,
    has_title: bool = False,
    has_authors: bool = False,
    has_doi: bool = False,
    latency_ms: Optional[int] = None,
    used_ai_fallback: bool = False
):
    """
    Log a URL fetch attempt for analytics.
    
    Args:
        url: The URL being fetched
        success: Whether we got minimum citation data (title + author)
        resolution_method: How it was resolved (doi, pii_pubmed, html_scrape, ai_fallback, failed)
        failure_reason: Why it failed (403, timeout, no_metadata, ai_failed, etc.)
        domain: Extracted domain (e.g., 'thelancet.com')
        has_title: Whether title was extracted
        has_authors: Whether authors were extracted
        has_doi: Whether DOI was found
        latency_ms: How long the fetch took
        used_ai_fallback: Whether AI was needed as fallback
    """
    # Extract domain if not provided
    if not domain:
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace('www.', '')
        except:
            domain = 'unknown'
    
    # Log to database via existing log_api_call
    log_api_call(
        provider='url_fetch',
        query=url[:500],
        function=resolution_method,
        source_type='url',
        success=success,
        latency_ms=latency_ms,
        error_message=failure_reason,
        metadata={
            'domain': domain,
            'has_title': has_title,
            'has_authors': has_authors,
            'has_doi': has_doi,
            'used_ai_fallback': used_ai_fallback,
            'failure_reason': failure_reason
        }
    )
    
    # Print summary
    status = "✓" if success else "✗"
    print(f"[URLTracker] {status} {domain} via {resolution_method}" + 
          (f" (failed: {failure_reason})" if failure_reason else ""))


def get_url_fetch_stats(days: int = 30) -> Dict[str, Any]:
    """
    Get URL fetch statistics for dashboard.
    
    Returns:
        Dict with:
        - total_urls: Total URL fetch attempts
        - success_rate: Percentage of successful fetches (with title+author)
        - by_method: Breakdown by resolution method
        - by_domain: Breakdown by domain
        - failures: Breakdown of failure reasons
        - ai_fallback_rate: How often AI fallback was needed
    """
    try:
        from billing.db import get_db
        from billing.admin_models import APICall
        from sqlalchemy import func
        from datetime import timedelta
        import json
        
        db = get_db()
        since = datetime.utcnow() - timedelta(days=days)
        
        # Get all URL fetch records
        url_calls = db.query(APICall).filter(
            APICall.timestamp >= since,
            APICall.provider == 'url_fetch'
        ).all()
        
        if not url_calls:
            return {
                'total_urls': 0,
                'success_rate': 0,
                'by_method': {},
                'by_domain': {},
                'failures': {},
                'ai_fallback_rate': 0
            }
        
        total = len(url_calls)
        successful = sum(1 for c in url_calls if c.success)
        ai_fallbacks = 0
        by_method = {}
        by_domain = {}
        failures = {}
        
        for call in url_calls:
            # Count by method
            method = call.endpoint or 'unknown'
            by_method[method] = by_method.get(method, 0) + 1
            
            # Parse metadata
            meta = call.metadata_json or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except:
                    meta = {}
            
            # Count by domain
            domain = meta.get('domain', 'unknown')
            if domain not in by_domain:
                by_domain[domain] = {'total': 0, 'success': 0}
            by_domain[domain]['total'] += 1
            if call.success:
                by_domain[domain]['success'] += 1
            
            # Count AI fallbacks
            if meta.get('used_ai_fallback'):
                ai_fallbacks += 1
            
            # Count failure reasons
            if not call.success:
                reason = meta.get('failure_reason') or call.error_message or 'unknown'
                failures[reason] = failures.get(reason, 0) + 1
        
        # Calculate domain success rates
        for domain in by_domain:
            d = by_domain[domain]
            d['success_rate'] = round(d['success'] / d['total'] * 100, 1) if d['total'] > 0 else 0
        
        return {
            'total_urls': total,
            'success_rate': round(successful / total * 100, 1) if total > 0 else 0,
            'successful': successful,
            'failed': total - successful,
            'by_method': by_method,
            'by_domain': by_domain,
            'failures': failures,
            'ai_fallback_count': ai_fallbacks,
            'ai_fallback_rate': round(ai_fallbacks / total * 100, 1) if total > 0 else 0
        }
        
    except Exception as e:
        print(f"[CostTracker] Error getting URL stats: {e}")
        return {
            'total_urls': 0,
            'success_rate': 0,
            'by_method': {},
            'by_domain': {},
            'failures': {},
            'ai_fallback_rate': 0,
            'error': str(e)
        }


def print_summary(days: int = 30):
    """Print a cost summary to console."""
    stats = get_total_cost(days)
    
    print("\n" + "="*50)
    print(f"CITATEGENIE API COST SUMMARY (Last {days} days)")
    print("="*50)
    print(f"Total API calls: {stats['call_count']}")
    print(f"Total cost: ${stats['total_cost']:.4f}")
    print("\nBy provider:")
    for provider, data in stats['by_provider'].items():
        print(f"  {provider:12} ${data['cost']:.4f} ({data['calls']} calls)")
    print("="*50 + "\n")


def print_url_summary(days: int = 30):
    """Print URL fetch summary to console."""
    stats = get_url_fetch_stats(days)
    
    print("\n" + "="*50)
    print(f"URL FETCH SUMMARY (Last {days} days)")
    print("="*50)
    print(f"Total URLs: {stats['total_urls']}")
    print(f"Success Rate: {stats['success_rate']}%")
    print(f"AI Fallback Rate: {stats['ai_fallback_rate']}%")
    
    if stats.get('by_method'):
        print("\nBy Resolution Method:")
        for method, count in sorted(stats['by_method'].items(), key=lambda x: -x[1]):
            print(f"  {method:20} {count}")
    
    if stats.get('failures'):
        print("\nFailure Reasons:")
        for reason, count in sorted(stats['failures'].items(), key=lambda x: -x[1]):
            print(f"  {reason:20} {count}")
    
    if stats.get('by_domain'):
        print("\nTop Domains:")
        sorted_domains = sorted(stats['by_domain'].items(), 
                               key=lambda x: -x[1]['total'])[:10]
        for domain, data in sorted_domains:
            print(f"  {domain:30} {data['success_rate']:5.1f}% ({data['success']}/{data['total']})")
    
    print("="*50 + "\n")


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    print("Testing cost tracker...")
    
    # Test cost calculation
    print(f"OpenAI 1000 in + 500 out = ${calculate_cost('openai', 1000, 500):.6f}")
    print(f"Gemini 1000 in + 500 out = ${calculate_cost('gemini', 1000, 500):.6f}")
    print(f"Claude 1000 in + 500 out = ${calculate_cost('claude', 1000, 500):.6f}")
    print(f"SerpAPI search = ${calculate_cost('serpapi'):.6f}")
