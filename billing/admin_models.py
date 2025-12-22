"""
billing/admin_models.py

SQLAlchemy models for admin analytics and cost tracking.

Tables:
    - api_calls: Individual API call records with cost and metadata
    - document_sessions: Document processing session records

These tables enable:
    - Per-document and per-citation cost tracking
    - Success rate analysis by source type and engine
    - Citation type distribution
    - Provider usage breakdown
    - Trend analysis over time

Version History:
    2025-12-20: Initial implementation
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text, Float,
    ForeignKey, Index, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from billing.models import Base
import enum


# =============================================================================
# ENUMS
# =============================================================================

class APIProvider(str, enum.Enum):
    """API providers for cost tracking."""
    CROSSREF = 'crossref'
    PUBMED = 'pubmed'
    OPENALEX = 'openalex'
    GOOGLE_BOOKS = 'google_books'
    OPEN_LIBRARY = 'open_library'
    COURTLISTENER = 'courtlistener'
    SERPAPI = 'serpapi'
    OPENAI = 'openai'
    CLAUDE = 'claude'
    GEMINI = 'gemini'
    GENERIC_URL = 'generic_url'
    CACHE = 'cache'
    UNKNOWN = 'unknown'


class SourceType(str, enum.Enum):
    """Source type being resolved."""
    URL = 'url'
    DOI = 'doi'
    PMID = 'pmid'
    ISBN = 'isbn'
    ARXIV = 'arxiv'
    PARENTHETICAL = 'parenthetical'
    FOOTNOTE = 'footnote'
    UNKNOWN = 'unknown'


class CitationType(str, enum.Enum):
    """Citation type classification."""
    JOURNAL = 'journal'
    BOOK = 'book'
    LEGAL = 'legal'
    NEWSPAPER = 'newspaper'
    GOVERNMENT = 'government'
    INTERVIEW = 'interview'
    LETTER = 'letter'
    MEDICAL = 'medical'
    URL = 'url'
    UNKNOWN = 'unknown'


# =============================================================================
# DOCUMENT SESSION MODEL
# =============================================================================

class DocumentSession(Base):
    """
    Document processing session record.
    
    Tracks each document processed through CitateGenie:
    - Who processed it (user or anonymous)
    - What style was selected
    - How many citations were found/resolved
    - Total cost of all API calls
    - Processing time
    """
    __tablename__ = 'document_sessions'
    
    id = Column(Integer, primary_key=True)
    
    # Session identifier (matches your existing session_id)
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    
    # User (nullable for anonymous/preview)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    
    # Document info
    filename = Column(String(500))
    file_size_bytes = Column(Integer)
    
    # Processing mode
    citation_style = Column(String(50))  # chicago, apa, mla, etc.
    processing_mode = Column(String(50))  # footnote, author-date, unified
    is_preview = Column(Boolean, default=False)
    
    # Citation counts
    total_citations_found = Column(Integer, default=0)
    citations_resolved = Column(Integer, default=0)
    citations_failed = Column(Integer, default=0)
    
    # Cost tracking
    total_cost_usd = Column(Float, default=0.0)
    total_api_calls = Column(Integer, default=0)
    
    # Timing
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    processing_time_ms = Column(Integer)
    
    # Status
    status = Column(String(50), default='processing')  # processing, completed, failed
    error_message = Column(Text)
    
    # Resolution tracking (user acceptance metrics)
    # Success = accepted_original + accepted_alternative + minor_edit
    # Failure = user_provided
    resolution_accepted_original = Column(Integer, default=0)
    resolution_accepted_alternative = Column(Integer, default=0)
    resolution_minor_edit = Column(Integer, default=0)
    resolution_user_provided = Column(Integer, default=0)
    resolution_success_rate = Column(Float)  # Percentage (0-100)
    
    # Relationships
    api_calls = relationship('APICall', back_populates='document_session', lazy='dynamic')
    
    def __repr__(self):
        return f'<DocumentSession {self.session_id[:8]}... {self.status}>'


# Indexes for common queries
Index('idx_doc_sessions_user', DocumentSession.user_id)
Index('idx_doc_sessions_started', DocumentSession.started_at)
Index('idx_doc_sessions_status', DocumentSession.status)


# =============================================================================
# API CALL MODEL
# =============================================================================

class APICall(Base):
    """
    Individual API call record.
    
    Tracks every external API call made during citation resolution:
    - Which provider was called
    - Token counts and cost (for AI providers)
    - What was being resolved
    - Success/failure status
    - Response time
    
    This enables detailed cost analysis and optimization.
    """
    __tablename__ = 'api_calls'
    
    id = Column(Integer, primary_key=True)
    
    # Link to document session
    document_session_id = Column(Integer, ForeignKey('document_sessions.id'), nullable=True, index=True)
    
    # Timestamp
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Provider info
    provider = Column(String(50), nullable=False, index=True)  # openai, claude, crossref, etc.
    endpoint = Column(String(200))  # Specific API endpoint or function
    
    # Token counts (for AI providers)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    
    # Cost
    cost_usd = Column(Float, default=0.0)
    
    # What was being resolved
    source_type = Column(String(50))  # url, doi, parenthetical, etc.
    citation_type = Column(String(50))  # journal, book, legal, etc.
    raw_query = Column(Text)  # Original query/URL/citation text (truncated)
    
    # Result
    success = Column(Boolean, default=True)
    confidence = Column(Float)  # 0.0-1.0 confidence score
    error_message = Column(Text)
    
    # Performance
    latency_ms = Column(Integer)
    
    # Additional metadata
    metadata_json = Column(JSONB, default={})
    
    # Relationships
    document_session = relationship('DocumentSession', back_populates='api_calls')
    
    def __repr__(self):
        return f'<APICall {self.provider} ${self.cost_usd:.6f}>'


# Indexes for analytics queries
Index('idx_api_calls_provider', APICall.provider)
Index('idx_api_calls_timestamp', APICall.timestamp)
Index('idx_api_calls_source_type', APICall.source_type)
Index('idx_api_calls_citation_type', APICall.citation_type)
Index('idx_api_calls_success', APICall.success)


# =============================================================================
# DAILY STATS MODEL (Pre-aggregated for fast dashboard)
# =============================================================================

class DailyStats(Base):
    """
    Pre-aggregated daily statistics for fast dashboard loading.
    
    Updated by a background job or on-demand.
    Stores rolled-up metrics for each day.
    """
    __tablename__ = 'daily_stats'
    
    id = Column(Integer, primary_key=True)
    
    # Date (one row per day)
    date = Column(DateTime(timezone=True), unique=True, nullable=False, index=True)
    
    # Document counts
    documents_processed = Column(Integer, default=0)
    documents_preview = Column(Integer, default=0)
    documents_paid = Column(Integer, default=0)
    
    # Citation counts
    citations_found = Column(Integer, default=0)
    citations_resolved = Column(Integer, default=0)
    citations_failed = Column(Integer, default=0)
    
    # Cost breakdown by provider
    cost_total_usd = Column(Float, default=0.0)
    cost_openai_usd = Column(Float, default=0.0)
    cost_claude_usd = Column(Float, default=0.0)
    cost_gemini_usd = Column(Float, default=0.0)
    cost_serpapi_usd = Column(Float, default=0.0)
    cost_other_usd = Column(Float, default=0.0)
    
    # API call counts by provider
    calls_total = Column(Integer, default=0)
    calls_openai = Column(Integer, default=0)
    calls_claude = Column(Integer, default=0)
    calls_gemini = Column(Integer, default=0)
    calls_crossref = Column(Integer, default=0)
    calls_pubmed = Column(Integer, default=0)
    calls_serpapi = Column(Integer, default=0)
    
    # Success rates (stored as percentages)
    success_rate_overall = Column(Float)
    success_rate_url = Column(Float)
    success_rate_doi = Column(Float)
    success_rate_parenthetical = Column(Float)
    
    # Citation type distribution (counts)
    type_journal = Column(Integer, default=0)
    type_book = Column(Integer, default=0)
    type_legal = Column(Integer, default=0)
    type_newspaper = Column(Integer, default=0)
    type_other = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f'<DailyStats {self.date.strftime("%Y-%m-%d")}>'


# =============================================================================
# ACCEPTED CITATION MODEL
# =============================================================================

class AcceptedCitation(Base):
    """
    Stores SourceComponents for each accepted citation.
    
    This enables:
    - CSV export of all processed citations with full metadata
    - Building user citation libraries
    - Analytics on citation types and sources
    
    Populated when user clicks Accept & Save in the workbench.
    """
    __tablename__ = 'accepted_citations'
    
    id = Column(Integer, primary_key=True)
    
    # Session info
    session_id = Column(String(100), index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    
    # Citation identification
    note_id = Column(Integer)  # Footnote/endnote number in document
    original_text = Column(Text)  # What user typed/pasted
    
    # Formatted output
    formatted_citation = Column(Text)  # Final formatted citation
    citation_style = Column(String(50))  # chicago, apa, mla, etc.
    
    # SourceComponents fields
    citation_type = Column(String(50))  # journal, book, legal, etc.
    title = Column(Text)
    authors = Column(JSONB)  # List of author names
    year = Column(String(20))
    
    # Academic
    journal = Column(String(500))
    volume = Column(String(50))
    issue = Column(String(50))
    pages = Column(String(100))
    doi = Column(String(200))
    pmid = Column(String(50))
    
    # Book
    publisher = Column(String(500))
    place = Column(String(200))
    edition = Column(String(100))
    isbn = Column(String(50))
    
    # Legal
    case_name = Column(Text)
    legal_citation = Column(String(500))
    court = Column(String(200))
    jurisdiction = Column(String(100))
    
    # Newspaper
    newspaper = Column(String(500))
    
    # URL/Web
    url = Column(Text)
    access_date = Column(String(50))
    
    # Source tracking
    source_engine = Column(String(100))  # crossref, pubmed, google_books, etc.
    confidence = Column(String(20))  # high, medium, low
    
    # Timestamps
    accepted_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f'<AcceptedCitation {self.id} {self.citation_type}>'


# Indexes for accepted citations
Index('idx_accepted_session', AcceptedCitation.session_id)
Index('idx_accepted_user', AcceptedCitation.user_id)
Index('idx_accepted_type', AcceptedCitation.citation_type)
Index('idx_accepted_at', AcceptedCitation.accepted_at)


# =============================================================================
# RESOLUTION EVENT MODEL
# =============================================================================

class ResolutionEvent(Base):
    """
    Tracks user acceptance of citation recommendations.
    
    Success Definition:
        CitateGenie "succeeds" when user accepts the recommendation or makes minor edits.
        CitateGenie "fails" when user provides their own citation.
    
    Resolution Types:
        - accepted_original: User accepted recommendation as-is (>=95% similar)
        - accepted_alternative: User selected an alternative from search results
        - minor_edit: User made small edits (80-95% similar)
        - user_provided: User provided their own citation (<80% similar) - FAILURE
    
    Populated when user clicks Accept & Save in the workbench.
    """
    __tablename__ = 'resolution_events'
    
    id = Column(Integer, primary_key=True)
    
    # Links
    document_session_id = Column(Integer, ForeignKey('document_sessions.id'), nullable=True, index=True)
    session_id = Column(String(100), nullable=False, index=True)
    citation_id = Column(Integer, nullable=False)  # note_id in document
    
    # Resolution outcome
    resolution_type = Column(String(50), nullable=False, index=True)
    
    # Text comparison
    original_text = Column(Text)           # What CitateGenie recommended
    final_text = Column(Text)              # What user accepted/saved
    similarity_ratio = Column(Float)       # 0.0-1.0
    
    # Alternative tracking
    alternative_index = Column(Integer)    # Which alternative selected (0, 1, 2...) or NULL
    
    # Source tracking - which engine produced the accepted citation
    source_engine = Column(String(100), index=True)  # crossref, pubmed, ai_lookup, etc.
    
    # Context
    citation_style = Column(String(50))    # chicago, apa, mla, etc.
    citation_type = Column(String(50))     # journal, book, legal, etc.
    
    # Timestamp
    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationship
    document_session = relationship('DocumentSession', backref='resolution_events')
    
    def __repr__(self):
        return f'<ResolutionEvent {self.id} {self.resolution_type}>'


# Indexes for resolution events
Index('idx_resolution_session_id', ResolutionEvent.session_id)
Index('idx_resolution_doc_session', ResolutionEvent.document_session_id)
Index('idx_resolution_type', ResolutionEvent.resolution_type)
Index('idx_resolution_source_engine', ResolutionEvent.source_engine)
Index('idx_resolution_recorded_at', ResolutionEvent.recorded_at)
