"""
cost_tracker_patch.py

Patch for cost_tracker.py to integrate with DocumentLogger (Option 2).

This allows cost_tracker and document_logger to work together:
- cost_tracker continues logging API calls globally
- document_logger receives the same logs for per-document tracking
- Both systems stay synchronized

HOW TO APPLY:
1. Add these functions to your existing cost_tracker.py
2. Update log_api_call() to call _log_to_document_logger()
3. In app.py, call set_document_logger() after creating DocumentLogger
"""

# =============================================================================
# ADD TO TOP OF cost_tracker.py (after imports)
# =============================================================================

# Global reference to current document logger (thread-local for safety)
import threading
_thread_local = threading.local()

def set_document_logger(doc_logger):
    """
    Set the active document logger for this processing session.
    
    Call this in app.py after creating DocumentLogger:
        doc_logger = DocumentLogger(...)
        set_document_logger(doc_logger)
    
    Thread-safe: Each request thread gets its own logger.
    """
    _thread_local.doc_logger = doc_logger


def get_current_document_logger():
    """Get the document logger for current thread, if any."""
    return getattr(_thread_local, 'doc_logger', None)


def clear_document_logger():
    """Clear document logger after document processing completes."""
    if hasattr(_thread_local, 'doc_logger'):
        delattr(_thread_local, 'doc_logger')


def _log_to_document_logger(service, query='', success=True, cost=0.0, **kwargs):
    """
    Log API call to document logger if one is active.
    
    This gets called from log_api_call() to sync logs.
    """
    doc_logger = get_current_document_logger()
    if not doc_logger:
        return  # No active document logger
    
    # Map service name to match document_logger expectations
    service_mapping = {
        'openai': 'openai',
        'anthropic': 'anthropic', 
        'gemini': 'gemini',
        'serpapi': 'serpapi',
        'crossref': 'crossref',
        'openalex': 'openalex',
        'pubmed': 'pubmed',
        'semantic_scholar': 'semantic_scholar',
        'thenewsapi': 'thenewsapi',
        'newsdata': 'newsdata',
        'google_books': 'google_books',
        'courtlistener': 'courtlistener',
    }
    
    source = service_mapping.get(service, service.lower().replace(' ', '_'))
    
    # Log to document logger
    doc_logger.log_citation(
        query=query or kwargs.get('url', ''),
        source=source,
        success=success,
        cost=cost,
        **kwargs  # Pass any citation components
    )


# =============================================================================
# UPDATE YOUR EXISTING log_api_call() FUNCTION
# =============================================================================

def log_api_call(service, query='', function='', cost=None, **kwargs):
    """
    Log an API call for cost tracking.
    
    UPDATED: Now also logs to document_logger if active.
    
    Args:
        service: API service name (openai, serpapi, crossref, etc.)
        query: Query text or URL
        function: Function name that made the call
        cost: Cost in dollars (if None, auto-calculated)
        **kwargs: Additional data (title, authors, success, etc.)
    """
    # ... YOUR EXISTING CODE TO LOG TO CSV ...
    
    # Calculate cost if not provided
    if cost is None:
        # Your existing cost calculation logic
        pass
    
    # ADD THIS: Also log to document logger
    success = kwargs.get('success', True)
    _log_to_document_logger(
        service=service,
        query=query,
        success=success,
        cost=cost or 0.0,
        **kwargs
    )
    
    # ... REST OF YOUR EXISTING CODE ...


# =============================================================================
# EXAMPLE INTEGRATION IN app.py
# =============================================================================

"""
In app.py, in the /api/process endpoint:

@app.route('/api/process', methods=['POST'])
def process_doc():
    # ... existing code ...
    
    # Create document logger
    doc_logger = DocumentLogger(
        session_id=doc_session_id,
        filename=file.filename,
        user_id=user_id
    )
    
    # SET IT AS ACTIVE (this is the key step!)
    from cost_tracker import set_document_logger, clear_document_logger
    set_document_logger(doc_logger)
    
    try:
        # Process document - all API calls will now log to both systems
        processed_bytes, results, components_cache = process_document(
            file_bytes,
            style=style,
            add_links=add_links
        )
        
        # Save document log
        log_path = doc_logger.save()
        
    finally:
        # Clear document logger when done
        clear_document_logger()
    
    # ... rest of code ...
"""
