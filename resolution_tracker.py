"""
resolution_tracker.py

Tracks user acceptance of citation recommendations to measure CitateGenie's
effectiveness at generating correct citations.

Success Definition:
    CitateGenie "succeeds" when user accepts the recommendation or makes minor edits.
    CitateGenie "fails" when user provides their own citation.

Resolution Types:
    - accepted_original: User accepted recommendation as-is (>=95% similar)
    - accepted_alternative: User selected an alternative from search results
    - minor_edit: User made small edits (80-95% similar)
    - user_provided: User provided their own citation (<80% similar) - FAILURE

Usage:
    from resolution_tracker import log_resolution, calculate_similarity
    
    # Log when user accepts a citation
    resolution_type = log_resolution(
        session_id='abc123',
        citation_id=1,
        original_text='Smith, J. (2020). Title...',
        final_text='Smith, J. (2020). Title...',  # or edited version
        alternative_index=None,  # or 0, 1, 2 if they picked an alternative
        source_engine='crossref',
        citation_style='apa',
        citation_type='journal'
    )

Version History:
    2025-12-22: Initial implementation
"""

import os
from datetime import datetime
from typing import Optional, Dict, Any
from difflib import SequenceMatcher

# =============================================================================
# SIMILARITY CALCULATION
# =============================================================================

def calculate_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity ratio between two strings using SequenceMatcher.
    
    Uses Python's difflib which implements a variation of Levenshtein distance
    that's more focused on matching blocks of text.
    
    Args:
        text1: First string
        text2: Second string
        
    Returns:
        Float between 0.0 (completely different) and 1.0 (identical)
    """
    if not text1 and not text2:
        return 1.0
    if not text1 or not text2:
        return 0.0
    
    # Normalize: lowercase, strip whitespace
    t1 = ' '.join(text1.lower().split())
    t2 = ' '.join(text2.lower().split())
    
    return SequenceMatcher(None, t1, t2).ratio()


def determine_resolution_type(
    original_text: str,
    final_text: str,
    alternative_index: Optional[int] = None,
    similarity_threshold_original: float = 0.95,
    similarity_threshold_minor: float = 0.80
) -> tuple[str, float]:
    """
    Determine the resolution type based on text similarity and user action.
    
    Args:
        original_text: What CitateGenie recommended
        final_text: What user accepted/saved
        alternative_index: Index of selected alternative (None if not applicable)
        similarity_threshold_original: Threshold for "accepted_original" (default 95%)
        similarity_threshold_minor: Threshold for "minor_edit" (default 80%)
        
    Returns:
        Tuple of (resolution_type, similarity_ratio)
    """
    # If user selected an alternative, that's always "accepted_alternative"
    if alternative_index is not None:
        similarity = calculate_similarity(original_text, final_text)
        return ('accepted_alternative', similarity)
    
    # Calculate similarity
    similarity = calculate_similarity(original_text, final_text)
    
    # Determine type based on similarity
    if similarity >= similarity_threshold_original:
        return ('accepted_original', similarity)
    elif similarity >= similarity_threshold_minor:
        return ('minor_edit', similarity)
    else:
        return ('user_provided', similarity)


# =============================================================================
# DATABASE LOGGING
# =============================================================================

def log_resolution(
    session_id: str,
    citation_id: int,
    original_text: str,
    final_text: str,
    alternative_index: Optional[int] = None,
    source_engine: Optional[str] = None,
    citation_style: Optional[str] = None,
    citation_type: Optional[str] = None,
    document_session_id: Optional[int] = None
) -> str:
    """
    Log a citation resolution event to the database.
    
    Args:
        session_id: Application session ID
        citation_id: Note/citation ID within the document
        original_text: What CitateGenie recommended
        final_text: What user accepted/saved
        alternative_index: Index of selected alternative (None if original/edited)
        source_engine: Which engine produced the citation (crossref, pubmed, etc.)
        citation_style: Citation style used (apa, chicago, etc.)
        citation_type: Type of citation (journal, book, etc.)
        document_session_id: Database ID of the document session
        
    Returns:
        resolution_type: One of 'accepted_original', 'accepted_alternative', 
                        'minor_edit', 'user_provided'
    """
    # Determine resolution type
    resolution_type, similarity = determine_resolution_type(
        original_text, final_text, alternative_index
    )
    
    # Log to database
    try:
        from billing.db import get_db
        from billing.admin_models import ResolutionEvent
        
        db = get_db()
        
        event = ResolutionEvent(
            document_session_id=document_session_id,
            session_id=session_id,
            citation_id=citation_id,
            resolution_type=resolution_type,
            original_text=original_text[:2000] if original_text else None,  # Truncate for storage
            final_text=final_text[:2000] if final_text else None,
            similarity_ratio=similarity,
            alternative_index=alternative_index,
            source_engine=source_engine,
            citation_style=citation_style,
            citation_type=citation_type
        )
        db.add(event)
        db.commit()
        
        # Log to console
        status = "✓" if resolution_type != 'user_provided' else "✗"
        print(f"[Resolution] {status} {resolution_type} (sim={similarity:.2f}) "
              f"session={session_id[:8]}... cite={citation_id} engine={source_engine or 'unknown'}")
        
        return resolution_type
        
    except ImportError:
        # Models not available yet - log to console only
        print(f"[Resolution] {resolution_type} (sim={similarity:.2f}) "
              f"session={session_id[:8]}... cite={citation_id} [DB not available]")
        return resolution_type
        
    except Exception as e:
        print(f"[Resolution] Error logging: {e}")
        # Still return the type even if DB logging fails
        return resolution_type


def update_document_resolution_stats(session_id: str) -> Dict[str, Any]:
    """
    Update document_session with aggregated resolution stats.
    
    Call this when document processing is complete.
    
    Args:
        session_id: Application session ID
        
    Returns:
        Dict with resolution counts and success rate
    """
    try:
        from billing.db import get_db
        from billing.admin_models import DocumentSession, ResolutionEvent
        from sqlalchemy import func
        
        db = get_db()
        
        # Get counts by resolution type
        counts = db.query(
            ResolutionEvent.resolution_type,
            func.count(ResolutionEvent.id)
        ).filter(
            ResolutionEvent.session_id == session_id
        ).group_by(
            ResolutionEvent.resolution_type
        ).all()
        
        # Build stats dict
        stats = {
            'accepted_original': 0,
            'accepted_alternative': 0,
            'minor_edit': 0,
            'user_provided': 0
        }
        for resolution_type, count in counts:
            if resolution_type in stats:
                stats[resolution_type] = count
        
        # Calculate success rate
        successes = stats['accepted_original'] + stats['accepted_alternative'] + stats['minor_edit']
        total = successes + stats['user_provided']
        success_rate = (successes * 100.0 / total) if total > 0 else None
        
        # Update document session
        doc_session = db.query(DocumentSession).filter(
            DocumentSession.session_id == session_id
        ).first()
        
        if doc_session:
            doc_session.resolution_accepted_original = stats['accepted_original']
            doc_session.resolution_accepted_alternative = stats['accepted_alternative']
            doc_session.resolution_minor_edit = stats['minor_edit']
            doc_session.resolution_user_provided = stats['user_provided']
            doc_session.resolution_success_rate = success_rate
            db.commit()
            
            print(f"[Resolution] Updated doc stats: {successes}/{total} = {success_rate:.1f}% success")
        
        stats['success_rate'] = success_rate
        stats['total'] = total
        return stats
        
    except Exception as e:
        print(f"[Resolution] Error updating doc stats: {e}")
        return {}


# =============================================================================
# ANALYTICS FUNCTIONS
# =============================================================================

def get_resolution_stats(days: int = 30) -> Dict[str, Any]:
    """
    Get resolution statistics for the admin dashboard.
    
    Args:
        days: Number of days to look back
        
    Returns:
        Dict with:
        - total: Total resolution events
        - by_type: Counts by resolution type
        - success_rate: Overall success rate
        - by_engine: Success rate by source engine
    """
    try:
        from billing.db import get_db
        from billing.admin_models import ResolutionEvent
        from sqlalchemy import func
        from datetime import timedelta
        
        db = get_db()
        since = datetime.utcnow() - timedelta(days=days)
        
        # Get counts by type
        type_counts = db.query(
            ResolutionEvent.resolution_type,
            func.count(ResolutionEvent.id)
        ).filter(
            ResolutionEvent.recorded_at >= since
        ).group_by(
            ResolutionEvent.resolution_type
        ).all()
        
        by_type = {
            'accepted_original': 0,
            'accepted_alternative': 0,
            'minor_edit': 0,
            'user_provided': 0
        }
        for res_type, count in type_counts:
            if res_type in by_type:
                by_type[res_type] = count
        
        total = sum(by_type.values())
        successes = by_type['accepted_original'] + by_type['accepted_alternative'] + by_type['minor_edit']
        success_rate = round(successes * 100.0 / total, 1) if total > 0 else 0
        
        # Get stats by source engine
        engine_stats = db.query(
            ResolutionEvent.source_engine,
            func.count(ResolutionEvent.id).label('total'),
            func.count(ResolutionEvent.id).filter(
                ResolutionEvent.resolution_type.in_(['accepted_original', 'accepted_alternative', 'minor_edit'])
            ).label('successes')
        ).filter(
            ResolutionEvent.recorded_at >= since,
            ResolutionEvent.source_engine.isnot(None)
        ).group_by(
            ResolutionEvent.source_engine
        ).all()
        
        by_engine = {}
        for engine, total_count, success_count in engine_stats:
            by_engine[engine] = {
                'total': total_count,
                'successes': success_count,
                'success_rate': round(success_count * 100.0 / total_count, 1) if total_count > 0 else 0
            }
        
        return {
            'total': total,
            'by_type': by_type,
            'success_rate': success_rate,
            'successes': successes,
            'failures': by_type['user_provided'],
            'by_engine': by_engine
        }
        
    except Exception as e:
        print(f"[Resolution] Error getting stats: {e}")
        return {
            'total': 0,
            'by_type': {},
            'success_rate': 0,
            'by_engine': {},
            'error': str(e)
        }


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    print("Testing resolution tracker...")
    
    # Test similarity calculation
    test_cases = [
        ("Hello World", "Hello World", 1.0),
        ("Hello World", "hello world", 1.0),  # Case insensitive
        ("Hello World", "Hello World!", 0.95),  # Minor difference
        ("Smith, J. (2020). Title.", "Smith, J. (2020). Title", 0.98),
        ("Completely different text", "Nothing alike here", 0.2),
    ]
    
    print("\nSimilarity tests:")
    for t1, t2, expected in test_cases:
        actual = calculate_similarity(t1, t2)
        status = "✓" if abs(actual - expected) < 0.1 else "✗"
        print(f"  {status} '{t1[:20]}...' vs '{t2[:20]}...' = {actual:.2f} (expected ~{expected})")
    
    # Test resolution type determination
    print("\nResolution type tests:")
    
    original = "Smith, J. (2020). The impact of AI. Journal of Tech, 15(2), 100-120."
    
    # Identical
    res_type, sim = determine_resolution_type(original, original)
    print(f"  Identical: {res_type} ({sim:.2f})")
    
    # Minor edit (typo fix)
    edited = "Smith, J. (2020). The impact of AI. Journal of Technology, 15(2), 100-120."
    res_type, sim = determine_resolution_type(original, edited)
    print(f"  Minor edit: {res_type} ({sim:.2f})")
    
    # User provided (completely different)
    user = "Jones, A. (2019). Different paper entirely. Other Journal, 1, 1-10."
    res_type, sim = determine_resolution_type(original, user)
    print(f"  User provided: {res_type} ({sim:.2f})")
    
    # Alternative selected
    res_type, sim = determine_resolution_type(original, edited, alternative_index=1)
    print(f"  Alternative: {res_type} ({sim:.2f})")
    
    print("\nTests complete!")
