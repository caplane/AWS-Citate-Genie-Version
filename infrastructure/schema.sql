-- =============================================================================
-- CitateGenie Database Schema
-- PostgreSQL 15+ (Aurora Serverless)
-- 
-- SOC 2 Compliance:
--   - Audit columns on all tables (created_at, updated_at)
--   - Soft delete support (deleted_at)
--   - User data separation for GDPR
--
-- Version: 1.0
-- Date: 2025-12-20
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- USERS
-- =============================================================================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    email_verified BOOLEAN DEFAULT FALSE,
    password_hash VARCHAR(255),  -- NULL for OAuth users
    
    -- Profile
    name VARCHAR(255),
    organization VARCHAR(255),
    
    -- Subscription
    subscription_tier VARCHAR(50) DEFAULT 'free',  -- free, pro, enterprise
    credits_balance INTEGER DEFAULT 3,  -- Starting credits
    
    -- Data residency (GDPR)
    data_region VARCHAR(20) DEFAULT 'us-east-1',  -- or 'eu-west-1'
    gdpr_consent_date TIMESTAMPTZ,
    marketing_consent BOOLEAN DEFAULT FALSE,
    
    -- Account status
    status VARCHAR(20) DEFAULT 'active',  -- active, suspended, deleted
    last_login_at TIMESTAMPTZ,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,  -- Soft delete for GDPR
    
    -- Constraints
    CONSTRAINT valid_tier CHECK (subscription_tier IN ('free', 'pro', 'enterprise')),
    CONSTRAINT valid_status CHECK (status IN ('active', 'suspended', 'deleted')),
    CONSTRAINT valid_region CHECK (data_region IN ('us-east-1', 'eu-west-1'))
);

CREATE INDEX idx_users_email ON users(email) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_status ON users(status) WHERE deleted_at IS NULL;

-- =============================================================================
-- SESSIONS
-- =============================================================================

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Session data
    token_hash VARCHAR(64) NOT NULL,  -- SHA-256 of session token
    ip_address INET,
    user_agent TEXT,
    
    -- Expiration
    expires_at TIMESTAMPTZ NOT NULL,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_token ON sessions(token_hash);
CREATE INDEX idx_sessions_expires ON sessions(expires_at);

-- =============================================================================
-- DOCUMENTS
-- =============================================================================

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Document info
    filename VARCHAR(255) NOT NULL,
    file_size_bytes INTEGER,
    s3_key VARCHAR(512),  -- Path in S3
    
    -- Processing status
    status VARCHAR(20) DEFAULT 'uploaded',  -- uploaded, processing, completed, failed
    style VARCHAR(50),  -- Citation style used
    citations_count INTEGER DEFAULT 0,
    citations_resolved INTEGER DEFAULT 0,
    
    -- Cost tracking
    processing_cost_usd DECIMAL(10, 6) DEFAULT 0,
    credits_charged INTEGER DEFAULT 0,
    
    -- Output
    output_s3_key VARCHAR(512),
    
    -- Timing
    processing_started_at TIMESTAMPTZ,
    processing_completed_at TIMESTAMPTZ,
    processing_duration_ms INTEGER,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    
    -- Constraints
    CONSTRAINT valid_doc_status CHECK (status IN ('uploaded', 'processing', 'completed', 'failed'))
);

CREATE INDEX idx_documents_user ON documents(user_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_status ON documents(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_created ON documents(created_at DESC);

-- =============================================================================
-- CITATION LIBRARY
-- =============================================================================

CREATE TABLE citations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Citation components (the data comprising a citation)
    citation_type VARCHAR(50),  -- journal, book, legal, newspaper, website, etc.
    
    -- Authors (JSONB array for flexibility)
    authors JSONB,  -- [{"family": "Smith", "given": "John"}, ...]
    
    -- Core fields
    title TEXT,
    year VARCHAR(10),
    
    -- Journal article fields
    journal_name VARCHAR(500),
    volume VARCHAR(50),
    issue VARCHAR(50),
    pages VARCHAR(50),
    doi VARCHAR(255),
    pmid VARCHAR(50),
    
    -- Book fields
    publisher VARCHAR(255),
    publisher_place VARCHAR(255),
    isbn VARCHAR(50),
    edition VARCHAR(50),
    editors JSONB,
    
    -- Legal fields
    court VARCHAR(255),
    case_name TEXT,
    case_citation VARCHAR(255),
    docket_number VARCHAR(100),
    
    -- Web fields
    url TEXT,
    access_date DATE,
    
    -- Source tracking
    source_engine VARCHAR(50),  -- crossref, pubmed, ai_lookup, manual, etc.
    raw_input TEXT,  -- Original user input
    
    -- Formatted outputs (cached)
    formatted_chicago TEXT,
    formatted_apa TEXT,
    formatted_mla TEXT,
    formatted_bluebook TEXT,
    
    -- Organization
    collection_id UUID,  -- For user-created collections
    tags JSONB,  -- ["important", "chapter-1", ...]
    notes TEXT,
    
    -- Usage tracking
    use_count INTEGER DEFAULT 1,
    last_used_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_citations_user ON citations(user_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_citations_doi ON citations(doi) WHERE doi IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX idx_citations_title ON citations USING gin(to_tsvector('english', title)) WHERE deleted_at IS NULL;
CREATE INDEX idx_citations_authors ON citations USING gin(authors) WHERE deleted_at IS NULL;
CREATE INDEX idx_citations_type ON citations(citation_type) WHERE deleted_at IS NULL;
CREATE INDEX idx_citations_collection ON citations(collection_id) WHERE collection_id IS NOT NULL AND deleted_at IS NULL;

-- =============================================================================
-- CITATION COLLECTIONS
-- =============================================================================

CREATE TABLE citation_collections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    name VARCHAR(255) NOT NULL,
    description TEXT,
    color VARCHAR(7),  -- Hex color code
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_collections_user ON citation_collections(user_id) WHERE deleted_at IS NULL;

-- Add foreign key after collections table exists
ALTER TABLE citations 
ADD CONSTRAINT fk_citations_collection 
FOREIGN KEY (collection_id) REFERENCES citation_collections(id) ON DELETE SET NULL;

-- =============================================================================
-- DOCUMENT CITATIONS (Junction table)
-- =============================================================================

CREATE TABLE document_citations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    citation_id UUID NOT NULL REFERENCES citations(id) ON DELETE CASCADE,
    
    -- Position in document
    note_type VARCHAR(20),  -- endnote, footnote
    note_id VARCHAR(50),
    position_order INTEGER,
    
    -- What was used
    formatted_output TEXT,  -- The actual formatted text used
    style_used VARCHAR(50),
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(document_id, citation_id, note_id)
);

CREATE INDEX idx_doc_citations_document ON document_citations(document_id);
CREATE INDEX idx_doc_citations_citation ON document_citations(citation_id);

-- =============================================================================
-- CREDIT TRANSACTIONS
-- =============================================================================

CREATE TABLE credit_transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Transaction type
    type VARCHAR(20) NOT NULL,  -- purchase, spend, refund, bonus
    
    -- Credits
    credits_amount INTEGER NOT NULL,  -- Positive for add, negative for spend
    credits_balance_after INTEGER NOT NULL,
    
    -- For purchases
    amount_usd DECIMAL(10, 2),
    stripe_payment_intent_id VARCHAR(255),
    stripe_invoice_id VARCHAR(255),
    
    -- For spending
    document_id UUID REFERENCES documents(id),
    
    -- Details
    description TEXT,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT valid_tx_type CHECK (type IN ('purchase', 'spend', 'refund', 'bonus'))
);

CREATE INDEX idx_credit_tx_user ON credit_transactions(user_id);
CREATE INDEX idx_credit_tx_type ON credit_transactions(type);
CREATE INDEX idx_credit_tx_stripe ON credit_transactions(stripe_payment_intent_id) 
    WHERE stripe_payment_intent_id IS NOT NULL;

-- =============================================================================
-- AUDIT LOG (SOC 2)
-- =============================================================================

CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Event identification
    request_id VARCHAR(50),
    
    -- Actor
    user_id UUID REFERENCES users(id),
    user_id_hash VARCHAR(64),  -- For anonymized logging
    ip_address_hash VARCHAR(64),
    
    -- Action
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(100),
    
    -- Outcome
    outcome VARCHAR(20) NOT NULL,  -- success, failure, denied
    
    -- Details
    details JSONB,
    
    -- Timing
    duration_ms INTEGER,
    
    -- Classification
    severity VARCHAR(20) DEFAULT 'info',
    
    -- Timestamp
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT valid_outcome CHECK (outcome IN ('success', 'failure', 'denied', 'partial', 'timeout')),
    CONSTRAINT valid_severity CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical'))
);

-- Partition audit log by month for performance
-- Note: In production, implement partitioning

CREATE INDEX idx_audit_user ON audit_log(user_id);
CREATE INDEX idx_audit_action ON audit_log(action);
CREATE INDEX idx_audit_created ON audit_log(created_at DESC);
CREATE INDEX idx_audit_severity ON audit_log(severity) WHERE severity IN ('high', 'critical');
CREATE INDEX idx_audit_request ON audit_log(request_id) WHERE request_id IS NOT NULL;

-- =============================================================================
-- GDPR DATA REQUESTS
-- =============================================================================

CREATE TABLE gdpr_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    
    -- Request type
    request_type VARCHAR(20) NOT NULL,  -- export, delete, rectify
    
    -- Status
    status VARCHAR(20) DEFAULT 'pending',  -- pending, processing, completed, failed
    
    -- Processing
    processed_at TIMESTAMPTZ,
    processed_by VARCHAR(255),  -- System or admin user
    
    -- Result
    result_s3_key VARCHAR(512),  -- For exports
    notes TEXT,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT valid_gdpr_type CHECK (request_type IN ('export', 'delete', 'rectify')),
    CONSTRAINT valid_gdpr_status CHECK (status IN ('pending', 'processing', 'completed', 'failed'))
);

CREATE INDEX idx_gdpr_user ON gdpr_requests(user_id);
CREATE INDEX idx_gdpr_status ON gdpr_requests(status) WHERE status = 'pending';

-- =============================================================================
-- API USAGE TRACKING
-- =============================================================================

CREATE TABLE api_usage (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    document_id UUID REFERENCES documents(id),
    
    -- API provider
    provider VARCHAR(50) NOT NULL,  -- openai, anthropic, crossref, pubmed
    model VARCHAR(100),
    
    -- Usage
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd DECIMAL(10, 6) DEFAULT 0,
    
    -- Timing
    duration_ms INTEGER,
    
    -- Status
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_api_usage_user ON api_usage(user_id);
CREATE INDEX idx_api_usage_document ON api_usage(document_id);
CREATE INDEX idx_api_usage_provider ON api_usage(provider);
CREATE INDEX idx_api_usage_created ON api_usage(created_at DESC);

-- =============================================================================
-- FUNCTIONS
-- =============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply to all tables with updated_at
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_citations_updated_at BEFORE UPDATE ON citations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_collections_updated_at BEFORE UPDATE ON citation_collections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_gdpr_updated_at BEFORE UPDATE ON gdpr_requests
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- VIEWS
-- =============================================================================

-- User dashboard stats
CREATE VIEW user_stats AS
SELECT 
    u.id as user_id,
    u.email,
    u.credits_balance,
    u.subscription_tier,
    COUNT(DISTINCT d.id) as total_documents,
    COUNT(DISTINCT c.id) as total_citations,
    SUM(d.credits_charged) as total_credits_spent,
    MAX(d.created_at) as last_document_at
FROM users u
LEFT JOIN documents d ON d.user_id = u.id AND d.deleted_at IS NULL
LEFT JOIN citations c ON c.user_id = u.id AND c.deleted_at IS NULL
WHERE u.deleted_at IS NULL
GROUP BY u.id, u.email, u.credits_balance, u.subscription_tier;

-- Daily usage for billing
CREATE VIEW daily_usage AS
SELECT 
    DATE(created_at) as usage_date,
    user_id,
    COUNT(*) as documents_processed,
    SUM(credits_charged) as credits_used,
    SUM(processing_cost_usd) as cost_usd
FROM documents
WHERE deleted_at IS NULL
GROUP BY DATE(created_at), user_id;

-- =============================================================================
-- INITIAL DATA
-- =============================================================================

-- Insert system user for automated processes
INSERT INTO users (id, email, name, subscription_tier, status, data_region)
VALUES (
    '00000000-0000-0000-0000-000000000000',
    'system@citategenie.com',
    'System',
    'enterprise',
    'active',
    'us-east-1'
);

-- =============================================================================
-- GRANTS
-- =============================================================================

-- Create application role
-- Note: Run these after creating the citategenie_app user
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO citategenie_app;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO citategenie_app;
