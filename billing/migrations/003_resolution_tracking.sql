-- =============================================================================
-- CITATEGENIE RESOLUTION TRACKING SCHEMA
-- =============================================================================
-- Tables for tracking user acceptance of citation recommendations
-- Run this after 002_admin_analytics.sql
--
-- Tables:
--   - resolution_events: Per-citation resolution events
--
-- Columns added to document_sessions:
--   - resolution_* counters for aggregated metrics
--
-- Success Definition:
--   CitateGenie "succeeded" when user accepted the original recommendation,
--   selected an alternative, or made only minor edits (<20% change).
--   CitateGenie "failed" when user provided their own citation (>20% change).
--
-- Version: 2025-12-22
-- =============================================================================

-- =============================================================================
-- RESOLUTION EVENTS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS resolution_events (
    id                      SERIAL PRIMARY KEY,
    
    -- Links
    document_session_id     INTEGER REFERENCES document_sessions(id),
    session_id              VARCHAR(100) NOT NULL,
    citation_id             INTEGER NOT NULL,  -- note_id in document
    
    -- Resolution outcome
    -- 'accepted_original': User accepted CitateGenie's recommendation as-is (>=95% similar)
    -- 'accepted_alternative': User selected an alternative from search results
    -- 'minor_edit': User made small edits to recommendation (80-95% similar)
    -- 'user_provided': User provided their own citation (<80% similar) - this is a FAILURE
    resolution_type         VARCHAR(50) NOT NULL,
    
    -- Text comparison
    original_text           TEXT,           -- What CitateGenie recommended
    final_text              TEXT,           -- What user accepted/saved
    similarity_ratio        REAL,           -- Levenshtein ratio (0.0-1.0)
    
    -- Alternative tracking
    alternative_index       INTEGER,        -- Which alternative selected (0, 1, 2...) or NULL
    
    -- Source tracking - which engine produced the accepted citation
    source_engine           VARCHAR(100),   -- crossref, pubmed, openalex, google_books, ai_lookup, etc.
    
    -- Context
    citation_style          VARCHAR(50),    -- chicago, apa, mla, etc.
    citation_type           VARCHAR(50),    -- journal, book, legal, etc.
    
    -- Timestamp
    recorded_at             TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for analytics queries
CREATE INDEX IF NOT EXISTS idx_resolution_session_id ON resolution_events(session_id);
CREATE INDEX IF NOT EXISTS idx_resolution_doc_session ON resolution_events(document_session_id);
CREATE INDEX IF NOT EXISTS idx_resolution_type ON resolution_events(resolution_type);
CREATE INDEX IF NOT EXISTS idx_resolution_source_engine ON resolution_events(source_engine);
CREATE INDEX IF NOT EXISTS idx_resolution_recorded_at ON resolution_events(recorded_at);

-- =============================================================================
-- ADD AGGREGATE COLUMNS TO DOCUMENT_SESSIONS
-- =============================================================================

-- Add resolution tracking columns to document_sessions
ALTER TABLE document_sessions 
    ADD COLUMN IF NOT EXISTS resolution_accepted_original INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS resolution_accepted_alternative INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS resolution_minor_edit INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS resolution_user_provided INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS resolution_success_rate REAL;

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to calculate resolution success rate for a document
-- Success = accepted_original + accepted_alternative + minor_edit
-- Failure = user_provided
CREATE OR REPLACE FUNCTION calculate_resolution_success_rate(
    p_accepted_original INTEGER,
    p_accepted_alternative INTEGER,
    p_minor_edit INTEGER,
    p_user_provided INTEGER
)
RETURNS REAL AS $$
DECLARE
    total INTEGER;
    successes INTEGER;
BEGIN
    successes := COALESCE(p_accepted_original, 0) + 
                 COALESCE(p_accepted_alternative, 0) + 
                 COALESCE(p_minor_edit, 0);
    total := successes + COALESCE(p_user_provided, 0);
    
    IF total = 0 THEN
        RETURN NULL;
    END IF;
    
    RETURN (successes * 100.0 / total)::REAL;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to get resolution stats for a date range
CREATE OR REPLACE FUNCTION get_resolution_stats(start_date DATE, end_date DATE)
RETURNS TABLE(
    total_resolutions BIGINT,
    accepted_original BIGINT,
    accepted_alternative BIGINT,
    minor_edit BIGINT,
    user_provided BIGINT,
    success_rate REAL
) AS $$
    SELECT 
        COUNT(*) as total_resolutions,
        COUNT(*) FILTER (WHERE resolution_type = 'accepted_original') as accepted_original,
        COUNT(*) FILTER (WHERE resolution_type = 'accepted_alternative') as accepted_alternative,
        COUNT(*) FILTER (WHERE resolution_type = 'minor_edit') as minor_edit,
        COUNT(*) FILTER (WHERE resolution_type = 'user_provided') as user_provided,
        (COUNT(*) FILTER (WHERE resolution_type IN ('accepted_original', 'accepted_alternative', 'minor_edit')) 
         * 100.0 / NULLIF(COUNT(*), 0))::REAL as success_rate
    FROM resolution_events
    WHERE recorded_at >= start_date 
      AND recorded_at < end_date + INTERVAL '1 day';
$$ LANGUAGE SQL STABLE;

-- Function to get resolution stats by source engine
CREATE OR REPLACE FUNCTION get_resolution_by_engine(start_date DATE, end_date DATE)
RETURNS TABLE(
    source_engine VARCHAR,
    total_count BIGINT,
    success_count BIGINT,
    success_rate REAL
) AS $$
    SELECT 
        source_engine,
        COUNT(*) as total_count,
        COUNT(*) FILTER (WHERE resolution_type IN ('accepted_original', 'accepted_alternative', 'minor_edit')) as success_count,
        (COUNT(*) FILTER (WHERE resolution_type IN ('accepted_original', 'accepted_alternative', 'minor_edit')) 
         * 100.0 / NULLIF(COUNT(*), 0))::REAL as success_rate
    FROM resolution_events
    WHERE recorded_at >= start_date 
      AND recorded_at < end_date + INTERVAL '1 day'
      AND source_engine IS NOT NULL
    GROUP BY source_engine
    ORDER BY total_count DESC;
$$ LANGUAGE SQL STABLE;

-- =============================================================================
-- ADD RESOLUTION COLUMNS TO DAILY_STATS
-- =============================================================================

ALTER TABLE daily_stats
    ADD COLUMN IF NOT EXISTS resolution_total INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS resolution_accepted_original INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS resolution_accepted_alternative INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS resolution_minor_edit INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS resolution_user_provided INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS resolution_success_rate REAL;

-- =============================================================================
-- SAMPLE QUERIES
-- =============================================================================

-- Get overall resolution success rate for last 7 days:
-- SELECT * FROM get_resolution_stats(CURRENT_DATE - INTERVAL '7 days', CURRENT_DATE);

-- Get success rate by source engine:
-- SELECT * FROM get_resolution_by_engine(CURRENT_DATE - INTERVAL '30 days', CURRENT_DATE);

-- Get documents with lowest resolution success:
-- SELECT 
--     ds.filename, 
--     ds.resolution_success_rate,
--     ds.resolution_accepted_original,
--     ds.resolution_user_provided,
--     ds.started_at
-- FROM document_sessions ds
-- WHERE ds.resolution_success_rate IS NOT NULL
-- ORDER BY ds.resolution_success_rate ASC
-- LIMIT 10;

-- Get resolution type distribution:
-- SELECT 
--     resolution_type, 
--     COUNT(*) as count,
--     ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as percentage
-- FROM resolution_events
-- WHERE recorded_at >= CURRENT_DATE - INTERVAL '30 days'
-- GROUP BY resolution_type
-- ORDER BY count DESC;
