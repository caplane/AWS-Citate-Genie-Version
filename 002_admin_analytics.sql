-- =============================================================================
-- CITATEGENIE ADMIN ANALYTICS SCHEMA
-- =============================================================================
-- Tables for cost tracking, API call logging, and analytics
-- Run this after the billing schema (001_initial_billing.sql)
--
-- Tables:
--   - document_sessions: Document processing records
--   - api_calls: Individual API call logs with costs
--   - daily_stats: Pre-aggregated daily statistics
--
-- Version: 2025-12-20
-- =============================================================================

-- =============================================================================
-- DOCUMENT SESSIONS
-- =============================================================================

CREATE TABLE IF NOT EXISTS document_sessions (
    id                      SERIAL PRIMARY KEY,
    
    -- Session identifier
    session_id              VARCHAR(100) UNIQUE NOT NULL,
    
    -- User (nullable for anonymous/preview)
    user_id                 INTEGER REFERENCES users(id),
    
    -- Document info
    filename                VARCHAR(500),
    file_size_bytes         INTEGER,
    
    -- Processing mode
    citation_style          VARCHAR(50),
    processing_mode         VARCHAR(50),
    is_preview              BOOLEAN DEFAULT FALSE,
    
    -- Citation counts
    total_citations_found   INTEGER DEFAULT 0,
    citations_resolved      INTEGER DEFAULT 0,
    citations_failed        INTEGER DEFAULT 0,
    
    -- Cost tracking
    total_cost_usd          REAL DEFAULT 0.0,
    total_api_calls         INTEGER DEFAULT 0,
    
    -- Timing
    started_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at            TIMESTAMP WITH TIME ZONE,
    processing_time_ms      INTEGER,
    
    -- Status
    status                  VARCHAR(50) DEFAULT 'processing',
    error_message           TEXT
);

CREATE INDEX IF NOT EXISTS idx_doc_sessions_session_id ON document_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_doc_sessions_user ON document_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_doc_sessions_started ON document_sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_doc_sessions_status ON document_sessions(status);

-- =============================================================================
-- API CALLS
-- =============================================================================

CREATE TABLE IF NOT EXISTS api_calls (
    id                      SERIAL PRIMARY KEY,
    
    -- Link to document session (nullable for standalone calls)
    document_session_id     INTEGER REFERENCES document_sessions(id),
    
    -- Timestamp
    timestamp               TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Provider info
    provider                VARCHAR(50) NOT NULL,
    endpoint                VARCHAR(200),
    
    -- Token counts (for AI providers)
    input_tokens            INTEGER DEFAULT 0,
    output_tokens           INTEGER DEFAULT 0,
    
    -- Cost
    cost_usd                REAL DEFAULT 0.0,
    
    -- What was being resolved
    source_type             VARCHAR(50),
    citation_type           VARCHAR(50),
    raw_query               TEXT,
    
    -- Result
    success                 BOOLEAN DEFAULT TRUE,
    confidence              REAL,
    error_message           TEXT,
    
    -- Performance
    latency_ms              INTEGER,
    
    -- Additional metadata
    metadata_json           JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_api_calls_session ON api_calls(document_session_id);
CREATE INDEX IF NOT EXISTS idx_api_calls_timestamp ON api_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_api_calls_provider ON api_calls(provider);
CREATE INDEX IF NOT EXISTS idx_api_calls_source_type ON api_calls(source_type);
CREATE INDEX IF NOT EXISTS idx_api_calls_citation_type ON api_calls(citation_type);
CREATE INDEX IF NOT EXISTS idx_api_calls_success ON api_calls(success);

-- =============================================================================
-- DAILY STATS (Pre-aggregated)
-- =============================================================================

CREATE TABLE IF NOT EXISTS daily_stats (
    id                          SERIAL PRIMARY KEY,
    
    -- Date (one row per day)
    date                        DATE UNIQUE NOT NULL,
    
    -- Document counts
    documents_processed         INTEGER DEFAULT 0,
    documents_preview           INTEGER DEFAULT 0,
    documents_paid              INTEGER DEFAULT 0,
    
    -- Citation counts
    citations_found             INTEGER DEFAULT 0,
    citations_resolved          INTEGER DEFAULT 0,
    citations_failed            INTEGER DEFAULT 0,
    
    -- Cost breakdown by provider
    cost_total_usd              REAL DEFAULT 0.0,
    cost_openai_usd             REAL DEFAULT 0.0,
    cost_claude_usd             REAL DEFAULT 0.0,
    cost_gemini_usd             REAL DEFAULT 0.0,
    cost_serpapi_usd            REAL DEFAULT 0.0,
    cost_other_usd              REAL DEFAULT 0.0,
    
    -- API call counts by provider
    calls_total                 INTEGER DEFAULT 0,
    calls_openai                INTEGER DEFAULT 0,
    calls_claude                INTEGER DEFAULT 0,
    calls_gemini                INTEGER DEFAULT 0,
    calls_crossref              INTEGER DEFAULT 0,
    calls_pubmed                INTEGER DEFAULT 0,
    calls_serpapi               INTEGER DEFAULT 0,
    
    -- Success rates (percentages 0-100)
    success_rate_overall        REAL,
    success_rate_url            REAL,
    success_rate_doi            REAL,
    success_rate_parenthetical  REAL,
    
    -- Citation type distribution
    type_journal                INTEGER DEFAULT 0,
    type_book                   INTEGER DEFAULT 0,
    type_legal                  INTEGER DEFAULT 0,
    type_newspaper              INTEGER DEFAULT 0,
    type_other                  INTEGER DEFAULT 0,
    
    -- Timestamps
    created_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON daily_stats(date);

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to get total cost for a date range
CREATE OR REPLACE FUNCTION get_total_cost(start_date DATE, end_date DATE)
RETURNS REAL AS $$
    SELECT COALESCE(SUM(cost_usd), 0.0)::REAL
    FROM api_calls
    WHERE timestamp >= start_date 
      AND timestamp < end_date + INTERVAL '1 day';
$$ LANGUAGE SQL STABLE;

-- Function to get cost breakdown by provider for a date range
CREATE OR REPLACE FUNCTION get_cost_by_provider(start_date DATE, end_date DATE)
RETURNS TABLE(provider VARCHAR, total_cost REAL, call_count BIGINT) AS $$
    SELECT 
        provider,
        COALESCE(SUM(cost_usd), 0.0)::REAL as total_cost,
        COUNT(*) as call_count
    FROM api_calls
    WHERE timestamp >= start_date 
      AND timestamp < end_date + INTERVAL '1 day'
    GROUP BY provider
    ORDER BY total_cost DESC;
$$ LANGUAGE SQL STABLE;

-- Function to calculate success rate by source type
CREATE OR REPLACE FUNCTION get_success_rates(start_date DATE, end_date DATE)
RETURNS TABLE(source_type VARCHAR, success_rate REAL, total_count BIGINT) AS $$
    SELECT 
        source_type,
        (COUNT(*) FILTER (WHERE success = TRUE) * 100.0 / NULLIF(COUNT(*), 0))::REAL as success_rate,
        COUNT(*) as total_count
    FROM api_calls
    WHERE timestamp >= start_date 
      AND timestamp < end_date + INTERVAL '1 day'
      AND source_type IS NOT NULL
    GROUP BY source_type
    ORDER BY total_count DESC;
$$ LANGUAGE SQL STABLE;

-- =============================================================================
-- TRIGGER: Update daily_stats updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION update_daily_stats_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_daily_stats_updated ON daily_stats;
CREATE TRIGGER trigger_daily_stats_updated
    BEFORE UPDATE ON daily_stats
    FOR EACH ROW
    EXECUTE FUNCTION update_daily_stats_updated_at();

-- =============================================================================
-- SAMPLE QUERIES
-- =============================================================================

-- Get today's cost:
-- SELECT get_total_cost(CURRENT_DATE, CURRENT_DATE);

-- Get this month's cost breakdown:
-- SELECT * FROM get_cost_by_provider(DATE_TRUNC('month', CURRENT_DATE)::DATE, CURRENT_DATE);

-- Get success rates for last 7 days:
-- SELECT * FROM get_success_rates(CURRENT_DATE - INTERVAL '7 days', CURRENT_DATE);

-- Get recent expensive API calls:
-- SELECT provider, cost_usd, raw_query, timestamp 
-- FROM api_calls 
-- ORDER BY cost_usd DESC 
-- LIMIT 10;

-- Get documents with highest cost:
-- SELECT ds.filename, ds.total_cost_usd, ds.total_api_calls, ds.started_at
-- FROM document_sessions ds
-- ORDER BY ds.total_cost_usd DESC
-- LIMIT 10;
