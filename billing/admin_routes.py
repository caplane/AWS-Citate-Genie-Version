"""
billing/admin_routes.py

Admin dashboard and reporting routes for CitateGenie.

Endpoints (all require ?key=ADMIN_SECRET):
    GET  /admin/dashboard          - Main dashboard HTML
    GET  /admin/api/stats          - Summary statistics JSON
    GET  /admin/api/costs          - Cost breakdown JSON
    GET  /admin/api/documents      - Recent documents JSON
    GET  /admin/api/calls          - Recent API calls JSON
    GET  /admin/api/success-rates  - Success rates by source type
    GET  /admin/api/citation-types - Citation type distribution
    GET  /admin/api/trends         - Cost trends over time
    GET  /admin/api/export/csv     - Export all data as CSV
    POST /admin/api/refresh-stats  - Recalculate daily stats

Authentication:
    All routes require ?key=ADMIN_SECRET query parameter.
    This is simple token-based auth for admin-only access.

Version History:
    2025-12-20: Initial implementation
"""

import os
import csv
from io import StringIO
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, request, jsonify, render_template_string, Response
from sqlalchemy import func, desc, case

from billing.db import get_db


# =============================================================================
# CONFIGURATION
# =============================================================================

ADMIN_SECRET = os.environ.get('ADMIN_SECRET', '')

admin_bp = Blueprint('admin_bp', __name__, url_prefix='/admin')


# =============================================================================
# AUTHENTICATION DECORATOR
# =============================================================================

def requires_admin_key(f):
    """
    Decorator that requires ADMIN_SECRET in query string.
    
    Usage: /admin/dashboard?key=YOUR_SECRET
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        provided_key = request.args.get('key', '')
        
        if not ADMIN_SECRET:
            return jsonify({
                'error': 'ADMIN_SECRET not configured on server'
            }), 500
        
        if not provided_key or provided_key != ADMIN_SECRET:
            return jsonify({
                'error': 'Invalid or missing admin key'
            }), 401
        
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_date_range(period: str = '30d') -> tuple:
    """
    Parse period string and return (start_date, end_date).
    
    Supported formats:
        - 'all' - all time (from 2020 to now)
        - '7d', '30d', '90d' - last N days
        - '2025-01' - specific month
        - '2025-01-15:2025-01-20' - date range
    """
    now = datetime.utcnow()
    
    # All time - from 2020 to now
    if period == 'all':
        return (datetime(2020, 1, 1), now)
    
    if period.endswith('d'):
        days = int(period[:-1])
        return (now - timedelta(days=days), now)
    
    if ':' in period:
        start, end = period.split(':')
        return (
            datetime.fromisoformat(start),
            datetime.fromisoformat(end) + timedelta(days=1)
        )
    
    # Assume month format: 2025-01
    try:
        year, month = period.split('-')
        start = datetime(int(year), int(month), 1)
        if int(month) == 12:
            end = datetime(int(year) + 1, 1, 1)
        else:
            end = datetime(int(year), int(month) + 1, 1)
        return (start, end)
    except:
        pass
    
    # Default to 30 days
    return (now - timedelta(days=30), now)


# =============================================================================
# DASHBOARD HTML
# =============================================================================

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CitateGenie Admin Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            padding: 20px;
            min-height: 100vh;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid #334155;
        }
        .header h1 {
            font-size: 24px;
            font-weight: 600;
            color: #f8fafc;
        }
        .header-actions {
            display: flex;
            gap: 10px;
        }
        .btn {
            padding: 8px 16px;
            border-radius: 6px;
            border: none;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.2s;
        }
        .btn-primary {
            background: #6366f1;
            color: white;
        }
        .btn-primary:hover { background: #4f46e5; }
        .btn-secondary {
            background: #334155;
            color: #e2e8f0;
        }
        .btn-secondary:hover { background: #475569; }
        .btn-danger {
            background: #dc2626;
            color: white;
        }
        .btn-danger:hover { background: #b91c1c; }
        .btn-success {
            background: #16a34a;
            color: white;
        }
        .btn-success:hover { background: #15803d; }
        
        .period-selector {
            display: flex;
            gap: 8px;
            margin-bottom: 20px;
        }
        .period-btn {
            padding: 6px 12px;
            border-radius: 4px;
            border: 1px solid #334155;
            background: transparent;
            color: #94a3b8;
            cursor: pointer;
            font-size: 13px;
        }
        .period-btn.active {
            background: #6366f1;
            border-color: #6366f1;
            color: white;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: #1e293b;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #334155;
        }
        .stat-label {
            font-size: 13px;
            color: #94a3b8;
            margin-bottom: 8px;
        }
        .stat-value {
            font-size: 28px;
            font-weight: 700;
            color: #f8fafc;
        }
        .stat-value.cost { color: #f59e0b; }
        .stat-value.success { color: #22c55e; }
        .stat-value.fail { color: #ef4444; }
        .stat-sub {
            font-size: 12px;
            color: #64748b;
            margin-top: 4px;
        }
        
        .charts-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .chart-card {
            background: #1e293b;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #334155;
        }
        .chart-title {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 16px;
            color: #f8fafc;
        }
        .chart-container {
            height: 250px;
        }
        
        .table-card {
            background: #1e293b;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #334155;
            margin-bottom: 20px;
        }
        .table-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            text-align: left;
            padding: 12px;
            border-bottom: 1px solid #334155;
        }
        th {
            font-size: 12px;
            text-transform: uppercase;
            color: #94a3b8;
            font-weight: 600;
        }
        td {
            font-size: 14px;
            color: #e2e8f0;
        }
        tr:hover { background: #334155; }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
        }
        .badge-success { background: #166534; color: #86efac; }
        .badge-fail { background: #991b1b; color: #fca5a5; }
        .badge-provider {
            background: #3730a3;
            color: #c7d2fe;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #64748b;
        }
        
        @media (max-width: 768px) {
            .charts-grid { grid-template-columns: 1fr; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔬 CitateGenie Admin Dashboard</h1>
        <div class="header-actions">
            <button class="btn btn-danger" onclick="clearLogs()">🗑️ Clear Logs</button>
            <button class="btn btn-success" onclick="exportCitations()">📋 Export Citations</button>
            <button class="btn btn-secondary" onclick="exportCSV()">📊 Export API Calls</button>
            <button class="btn btn-primary" onclick="refreshData()">🔄 Refresh</button>
        </div>
    </div>
    
    <div class="period-selector">
        <button class="period-btn active" data-period="7d">7 Days</button>
        <button class="period-btn" data-period="30d">30 Days</button>
        <button class="period-btn" data-period="90d">90 Days</button>
    </div>
    
    <div class="stats-grid" id="stats-grid">
        <div class="loading">Loading statistics...</div>
    </div>
    
    <div class="charts-grid">
        <div class="chart-card">
            <div class="chart-title">Cost by Provider</div>
            <div class="chart-container">
                <canvas id="providerChart"></canvas>
            </div>
        </div>
        <div class="chart-card">
            <div class="chart-title">Citation Type Distribution</div>
            <div class="chart-container">
                <canvas id="citationChart"></canvas>
            </div>
        </div>
        <div class="chart-card">
            <div class="chart-title">Success Rate by Source Type</div>
            <div class="chart-container">
                <canvas id="successChart"></canvas>
            </div>
        </div>
        <div class="chart-card">
            <div class="chart-title">Daily Costs (Last 14 Days)</div>
            <div class="chart-container">
                <canvas id="trendChart"></canvas>
            </div>
        </div>
    </div>
    
    <div class="table-card">
        <div class="table-header">
            <div class="chart-title">Recent Documents</div>
        </div>
        <table id="documents-table">
            <thead>
                <tr>
                    <th>Filename</th>
                    <th>Style</th>
                    <th>Citations</th>
                    <th>Cost</th>
                    <th>API Calls</th>
                    <th>Time</th>
                </tr>
            </thead>
            <tbody>
                <tr><td colspan="6" class="loading">Loading...</td></tr>
            </tbody>
        </table>
    </div>
    
    <div class="table-card">
        <div class="table-header">
            <div class="chart-title">Recent API Calls</div>
        </div>
        <table id="calls-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Provider</th>
                    <th>Tokens</th>
                    <th>Cost</th>
                    <th>Source</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                <tr><td colspan="6" class="loading">Loading...</td></tr>
            </tbody>
        </table>
    </div>

    <script>
        const adminKey = new URLSearchParams(window.location.search).get('key');
        let currentPeriod = '7d';
        let charts = {};
        
        // Period selector
        document.querySelectorAll('.period-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentPeriod = btn.dataset.period;
                refreshData();
            });
        });
        
        async function fetchAPI(endpoint) {
            const response = await fetch(`/admin/api/${endpoint}?key=${adminKey}&period=${currentPeriod}`);
            return response.json();
        }
        
        async function loadStats() {
            const data = await fetchAPI('stats');
            const grid = document.getElementById('stats-grid');
            
            const successRate = data.call_count > 0 
                ? ((data.successful_calls / data.call_count) * 100).toFixed(1)
                : 0;
            
            grid.innerHTML = `
                <div class="stat-card">
                    <div class="stat-label">Total Cost</div>
                    <div class="stat-value cost">$${data.total_cost.toFixed(4)}</div>
                    <div class="stat-sub">${currentPeriod} period</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">API Calls</div>
                    <div class="stat-value">${data.call_count.toLocaleString()}</div>
                    <div class="stat-sub">$${data.call_count > 0 ? (data.total_cost / data.call_count).toFixed(6) : 0} avg</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Documents</div>
                    <div class="stat-value">${data.document_count.toLocaleString()}</div>
                    <div class="stat-sub">${data.paid_documents} paid</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Citations Resolved</div>
                    <div class="stat-value success">${data.citations_resolved.toLocaleString()}</div>
                    <div class="stat-sub">${data.citations_failed} failed</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Success Rate</div>
                    <div class="stat-value ${parseFloat(successRate) >= 80 ? 'success' : 'fail'}">${successRate}%</div>
                    <div class="stat-sub">of API calls</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Median Cost/Doc</div>
                    <div class="stat-value cost">$${(data.median_cost_per_doc || 0).toFixed(4)}</div>
                    <div class="stat-sub">mode: $${(data.mode_cost_per_doc || 0).toFixed(4)}</div>
                </div>
            `;
        }
        
        async function loadProviderChart() {
            const data = await fetchAPI('costs');
            const ctx = document.getElementById('providerChart').getContext('2d');
            
            if (charts.provider) charts.provider.destroy();
            
            const providers = Object.keys(data.by_provider);
            const costs = providers.map(p => data.by_provider[p].cost);
            
            charts.provider = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: providers.map(p => p.charAt(0).toUpperCase() + p.slice(1)),
                    datasets: [{
                        data: costs,
                        backgroundColor: ['#6366f1', '#f59e0b', '#22c55e', '#ef4444', '#8b5cf6', '#06b6d4']
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'right', labels: { color: '#94a3b8' } }
                    }
                }
            });
        }
        
        async function loadCitationChart() {
            const data = await fetchAPI('citation-types');
            const ctx = document.getElementById('citationChart').getContext('2d');
            
            if (charts.citation) charts.citation.destroy();
            
            charts.citation = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: Object.keys(data).map(t => t.charAt(0).toUpperCase() + t.slice(1)),
                    datasets: [{
                        data: Object.values(data),
                        backgroundColor: '#6366f1'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                        x: { ticks: { color: '#94a3b8' }, grid: { display: false } }
                    }
                }
            });
        }
        
        async function loadSuccessChart() {
            const data = await fetchAPI('success-rates');
            const ctx = document.getElementById('successChart').getContext('2d');
            
            if (charts.success) charts.success.destroy();
            
            charts.success = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: Object.keys(data).map(t => t.toUpperCase()),
                    datasets: [{
                        data: Object.values(data),
                        backgroundColor: Object.values(data).map(v => v >= 80 ? '#22c55e' : v >= 50 ? '#f59e0b' : '#ef4444')
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { max: 100, ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                        x: { ticks: { color: '#94a3b8' }, grid: { display: false } }
                    }
                }
            });
        }
        
        async function loadTrendChart() {
            const data = await fetchAPI('trends');
            const ctx = document.getElementById('trendChart').getContext('2d');
            
            if (charts.trend) charts.trend.destroy();
            
            charts.trend = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: data.dates,
                    datasets: [{
                        label: 'Daily Cost ($)',
                        data: data.costs,
                        borderColor: '#6366f1',
                        backgroundColor: 'rgba(99, 102, 241, 0.1)',
                        fill: true,
                        tension: 0.3
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                        x: { ticks: { color: '#94a3b8' }, grid: { display: false } }
                    }
                }
            });
        }
        
        async function loadDocuments() {
            const data = await fetchAPI('documents');
            const tbody = document.querySelector('#documents-table tbody');
            
            if (data.documents.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#64748b;">No documents found</td></tr>';
                return;
            }
            
            tbody.innerHTML = data.documents.map(d => `
                <tr>
                    <td>${d.filename || d.session_id.substring(0, 8) + '...'}</td>
                    <td>${d.style || '-'}</td>
                    <td>${d.resolved}/${d.found} <span style="color:#64748b">(${d.failed} failed)</span></td>
                    <td style="color:#f59e0b">$${d.cost.toFixed(4)}</td>
                    <td>${d.api_calls}</td>
                    <td style="color:#64748b">${new Date(d.started_at).toLocaleString()}</td>
                </tr>
            `).join('');
        }
        
        async function loadCalls() {
            const data = await fetchAPI('calls');
            const tbody = document.querySelector('#calls-table tbody');
            
            if (data.calls.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#64748b;">No API calls found</td></tr>';
                return;
            }
            
            tbody.innerHTML = data.calls.map(c => `
                <tr>
                    <td style="color:#64748b">${new Date(c.timestamp).toLocaleString()}</td>
                    <td><span class="badge badge-provider">${c.provider}</span></td>
                    <td>${c.input_tokens} → ${c.output_tokens}</td>
                    <td style="color:#f59e0b">$${c.cost.toFixed(6)}</td>
                    <td>${c.source_type || '-'} / ${c.citation_type || '-'}</td>
                    <td><span class="badge ${c.success ? 'badge-success' : 'badge-fail'}">${c.success ? 'OK' : 'FAIL'}</span></td>
                </tr>
            `).join('');
        }
        
        async function refreshData() {
            await Promise.all([
                loadStats(),
                loadProviderChart(),
                loadCitationChart(),
                loadSuccessChart(),
                loadTrendChart(),
                loadDocuments(),
                loadCalls()
            ]);
        }
        
        function exportCSV() {
            window.location.href = `/admin/api/export/csv?key=${adminKey}&period=${currentPeriod}`;
        }
        
        function exportCitations() {
            window.location.href = `/admin/api/export/citations-csv?key=${adminKey}&period=${currentPeriod}`;
        }
        
        async function clearLogs() {
            // Step 1: Offer to save logs first
            const wantToSave = confirm('🗑️ Clear All Logs\\n\\nWould you like to EXPORT logs before clearing?\\n\\nClick OK to download CSV first, or Cancel to skip export.');
            
            if (wantToSave) {
                // Trigger CSV download
                window.location.href = `/admin/api/export/csv?key=${adminKey}&period=all`;
                
                // Wait a moment for download to start, then ask to proceed
                await new Promise(resolve => setTimeout(resolve, 1500));
            }
            
            // Step 2: Confirm clearing (now that they've had chance to save)
            const confirmMessage = wantToSave 
                ? '✅ Logs exported.\\n\\nNow that you have saved your logs, do you want to CLEAR all logs from the database?\\n\\nThis action CANNOT be undone.'
                : '⚠️ You chose not to export logs.\\n\\nAre you sure you want to CLEAR all logs from the database?\\n\\nThis action CANNOT be undone.';
            
            if (!confirm(confirmMessage)) {
                return;
            }
            
            // Step 3: Final confirmation
            if (!confirm('🚨 FINAL CONFIRMATION\\n\\nClick OK to permanently delete:\\n• All API call logs\\n• All document sessions\\n• All daily stats\\n\\nProceed?')) {
                return;
            }
            
            try {
                const response = await fetch(`/admin/api/clear-logs?key=${adminKey}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ confirm: true })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    alert(`✅ Logs cleared successfully!\\n\\nDeleted:\\n• ${data.deleted.api_calls || 0} API calls\\n• ${data.deleted.document_sessions || 0} document sessions\\n• ${data.deleted.daily_stats || 0} daily stats`);
                    refreshData();  // Reload dashboard
                } else {
                    alert('❌ Failed to clear logs: ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                alert('❌ Error: ' + err.message);
            }
        }
        
        // Initial load
        refreshData();
        
        // Auto-refresh every 60 seconds
        setInterval(refreshData, 60000);
    </script>
</body>
</html>
"""


# =============================================================================
# ROUTES
# =============================================================================

@admin_bp.route('/dashboard')
@requires_admin_key
def dashboard():
    """Render the admin dashboard HTML."""
    return render_template_string(DASHBOARD_HTML)


@admin_bp.route('/api/stats')
@requires_admin_key
def api_stats():
    """
    Get summary statistics.
    
    Query params:
        - period: '7d', '30d', '90d', or date range
    """
    from billing.admin_models import APICall, DocumentSession
    
    period = request.args.get('period', '30d')
    start_date, end_date = get_date_range(period)
    
    db = get_db()
    
    # Total cost and calls
    cost_stats = db.query(
        func.sum(APICall.cost_usd),
        func.count(APICall.id),
        func.count(case((APICall.success == True, 1)))
    ).filter(
        APICall.timestamp >= start_date,
        APICall.timestamp < end_date
    ).first()
    
    total_cost = cost_stats[0] or 0.0
    call_count = cost_stats[1] or 0
    successful_calls = cost_stats[2] or 0
    
    # Document stats
    doc_stats = db.query(
        func.count(DocumentSession.id),
        func.count(case((DocumentSession.is_preview == False, 1))),
        func.sum(DocumentSession.citations_resolved),
        func.sum(DocumentSession.citations_failed)
    ).filter(
        DocumentSession.started_at >= start_date,
        DocumentSession.started_at < end_date
    ).first()
    
    document_count = doc_stats[0] or 0
    paid_documents = doc_stats[1] or 0
    citations_resolved = doc_stats[2] or 0
    citations_failed = doc_stats[3] or 0
    
    # Median and mode cost per document
    doc_costs = db.query(DocumentSession.total_cost_usd).filter(
        DocumentSession.started_at >= start_date,
        DocumentSession.started_at < end_date,
        DocumentSession.total_cost_usd > 0
    ).all()
    
    median_cost = 0.0
    mode_cost = 0.0
    if doc_costs:
        costs = sorted([c[0] for c in doc_costs])
        median_cost = costs[len(costs) // 2]
        
        # Mode (most frequent, rounded to 4 decimals)
        from collections import Counter
        rounded_costs = [round(c, 4) for c in costs]
        mode_cost = Counter(rounded_costs).most_common(1)[0][0] if rounded_costs else 0
    
    return jsonify({
        'total_cost': total_cost,
        'call_count': call_count,
        'successful_calls': successful_calls,
        'document_count': document_count,
        'paid_documents': paid_documents,
        'citations_resolved': citations_resolved or 0,
        'citations_failed': citations_failed or 0,
        'median_cost_per_doc': median_cost,
        'mode_cost_per_doc': mode_cost,
        'period': period
    })


@admin_bp.route('/api/costs')
@requires_admin_key
def api_costs():
    """Get cost breakdown by provider."""
    from billing.admin_models import APICall
    
    period = request.args.get('period', '30d')
    start_date, end_date = get_date_range(period)
    
    db = get_db()
    
    provider_stats = db.query(
        APICall.provider,
        func.sum(APICall.cost_usd),
        func.count(APICall.id)
    ).filter(
        APICall.timestamp >= start_date,
        APICall.timestamp < end_date
    ).group_by(APICall.provider).all()
    
    by_provider = {}
    for provider, cost, count in provider_stats:
        by_provider[provider] = {
            'cost': cost or 0.0,
            'calls': count or 0
        }
    
    return jsonify({
        'by_provider': by_provider,
        'period': period
    })


@admin_bp.route('/api/url-stats')
@requires_admin_key
def api_url_stats():
    """
    Get URL fetch statistics.
    
    Returns detailed breakdown of URL resolution success/failure rates
    by domain and resolution method.
    """
    from billing.admin_models import APICall
    import json
    
    period = request.args.get('period', '30d')
    start_date, end_date = get_date_range(period)
    
    db = get_db()
    
    # Get all URL fetch records
    url_calls = db.query(APICall).filter(
        APICall.timestamp >= start_date,
        APICall.timestamp < end_date,
        APICall.provider == 'url_fetch'
    ).all()
    
    if not url_calls:
        return jsonify({
            'total_urls': 0,
            'success_rate': 0,
            'by_method': {},
            'by_domain': {},
            'failures': {},
            'ai_fallback_rate': 0,
            'period': period
        })
    
    total = len(url_calls)
    successful = sum(1 for c in url_calls if c.success)
    ai_fallbacks = 0
    by_method = {}
    by_domain = {}
    failures = {}
    
    for call in url_calls:
        # Count by method (stored in endpoint field)
        method = call.endpoint or 'unknown'
        if method not in by_method:
            by_method[method] = {'total': 0, 'success': 0}
        by_method[method]['total'] += 1
        if call.success:
            by_method[method]['success'] += 1
        
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
            by_domain[domain] = {'total': 0, 'success': 0, 'failures': {}}
        by_domain[domain]['total'] += 1
        if call.success:
            by_domain[domain]['success'] += 1
        else:
            reason = meta.get('failure_reason') or call.error_message or 'unknown'
            by_domain[domain]['failures'][reason] = by_domain[domain]['failures'].get(reason, 0) + 1
        
        # Count AI fallbacks
        if meta.get('used_ai_fallback'):
            ai_fallbacks += 1
        
        # Count overall failure reasons
        if not call.success:
            reason = meta.get('failure_reason') or call.error_message or 'unknown'
            failures[reason] = failures.get(reason, 0) + 1
    
    # Calculate success rates for methods
    for method in by_method:
        m = by_method[method]
        m['success_rate'] = round(m['success'] / m['total'] * 100, 1) if m['total'] > 0 else 0
    
    # Calculate success rates for domains and sort by total
    for domain in by_domain:
        d = by_domain[domain]
        d['success_rate'] = round(d['success'] / d['total'] * 100, 1) if d['total'] > 0 else 0
    
    # Sort domains by total (descending)
    sorted_domains = dict(sorted(by_domain.items(), key=lambda x: -x[1]['total']))
    
    return jsonify({
        'total_urls': total,
        'successful': successful,
        'failed': total - successful,
        'success_rate': round(successful / total * 100, 1) if total > 0 else 0,
        'ai_fallback_count': ai_fallbacks,
        'ai_fallback_rate': round(ai_fallbacks / total * 100, 1) if total > 0 else 0,
        'by_method': by_method,
        'by_domain': sorted_domains,
        'failures': failures,
        'period': period
    })


@admin_bp.route('/api/documents')
@requires_admin_key
def api_documents():
    """Get recent document sessions."""
    from billing.admin_models import DocumentSession
    
    period = request.args.get('period', '30d')
    limit = min(int(request.args.get('limit', 50)), 200)
    start_date, end_date = get_date_range(period)
    
    db = get_db()
    
    docs = db.query(DocumentSession).filter(
        DocumentSession.started_at >= start_date,
        DocumentSession.started_at < end_date
    ).order_by(desc(DocumentSession.started_at)).limit(limit).all()
    
    return jsonify({
        'documents': [
            {
                'session_id': d.session_id,
                'filename': d.filename,
                'style': d.citation_style,
                'found': d.total_citations_found or 0,
                'resolved': d.citations_resolved or 0,
                'failed': d.citations_failed or 0,
                'cost': d.total_cost_usd or 0,
                'api_calls': d.total_api_calls or 0,
                'started_at': d.started_at.isoformat() if d.started_at else None,
                'is_preview': d.is_preview
            }
            for d in docs
        ],
        'period': period
    })


@admin_bp.route('/api/calls')
@requires_admin_key
def api_calls():
    """Get recent API calls."""
    from billing.admin_models import APICall
    
    period = request.args.get('period', '30d')
    limit = min(int(request.args.get('limit', 100)), 500)
    start_date, end_date = get_date_range(period)
    
    db = get_db()
    
    calls = db.query(APICall).filter(
        APICall.timestamp >= start_date,
        APICall.timestamp < end_date
    ).order_by(desc(APICall.timestamp)).limit(limit).all()
    
    return jsonify({
        'calls': [
            {
                'timestamp': c.timestamp.isoformat() if c.timestamp else None,
                'provider': c.provider,
                'endpoint': c.endpoint,
                'input_tokens': c.input_tokens,
                'output_tokens': c.output_tokens,
                'cost': c.cost_usd,
                'source_type': c.source_type,
                'citation_type': c.citation_type,
                'success': c.success,
                'confidence': c.confidence,
                'query': c.raw_query[:100] if c.raw_query else None
            }
            for c in calls
        ],
        'period': period
    })


@admin_bp.route('/api/success-rates')
@requires_admin_key
def api_success_rates():
    """Get success rates by source type."""
    from billing.admin_models import APICall
    
    period = request.args.get('period', '30d')
    start_date, end_date = get_date_range(period)
    
    db = get_db()
    
    rates = db.query(
        APICall.source_type,
        (func.count(case((APICall.success == True, 1))) * 100.0 / 
         func.nullif(func.count(APICall.id), 0)).label('success_rate')
    ).filter(
        APICall.timestamp >= start_date,
        APICall.timestamp < end_date,
        APICall.source_type.isnot(None)
    ).group_by(APICall.source_type).all()
    
    return jsonify({row[0]: round(row[1] or 0, 1) for row in rates})


@admin_bp.route('/api/citation-types')
@requires_admin_key
def api_citation_types():
    """Get citation type distribution."""
    from billing.admin_models import APICall
    
    period = request.args.get('period', '30d')
    start_date, end_date = get_date_range(period)
    
    db = get_db()
    
    dist = db.query(
        APICall.citation_type,
        func.count(APICall.id)
    ).filter(
        APICall.timestamp >= start_date,
        APICall.timestamp < end_date,
        APICall.citation_type.isnot(None)
    ).group_by(APICall.citation_type).all()
    
    return jsonify({row[0]: row[1] for row in dist})


@admin_bp.route('/api/trends')
@requires_admin_key
def api_trends():
    """Get daily cost trends."""
    from billing.admin_models import APICall
    
    days = int(request.args.get('days', 14))
    
    db = get_db()
    
    # Get daily costs for last N days
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    daily = db.query(
        func.date(APICall.timestamp).label('date'),
        func.sum(APICall.cost_usd).label('cost')
    ).filter(
        APICall.timestamp >= start_date,
        APICall.timestamp < end_date
    ).group_by(func.date(APICall.timestamp)).order_by('date').all()
    
    # Fill in missing days
    date_costs = {row[0]: row[1] for row in daily}
    dates = []
    costs = []
    
    current = start_date.date()
    while current < end_date.date():
        dates.append(current.strftime('%m/%d'))
        costs.append(date_costs.get(current, 0) or 0)
        current += timedelta(days=1)
    
    return jsonify({
        'dates': dates,
        'costs': costs
    })


@admin_bp.route('/api/export/csv')
@requires_admin_key
def api_export_csv():
    """Export API calls as CSV."""
    from billing.admin_models import APICall
    from zoneinfo import ZoneInfo
    
    period = request.args.get('period', '30d')
    start_date, end_date = get_date_range(period)
    
    # EST timezone for readable timestamps
    est = ZoneInfo('America/New_York')
    
    db = get_db()
    
    calls = db.query(APICall).filter(
        APICall.timestamp >= start_date,
        APICall.timestamp < end_date
    ).order_by(desc(APICall.timestamp)).all()
    
    # Build CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        'timestamp_est', 'provider', 'endpoint', 'input_tokens', 'output_tokens',
        'cost_usd', 'source_type', 'citation_type', 'success', 'confidence',
        'latency_ms', 'query'
    ])
    
    # Data
    for c in calls:
        # Convert UTC timestamp to EST
        if c.timestamp:
            ts_est = c.timestamp.astimezone(est)
            ts_str = ts_est.strftime('%Y-%m-%d %H:%M:%S EST')
        else:
            ts_str = ''
        
        writer.writerow([
            ts_str,
            c.provider,
            c.endpoint,
            c.input_tokens,
            c.output_tokens,
            c.cost_usd,
            c.source_type,
            c.citation_type,
            c.success,
            c.confidence,
            c.latency_ms,
            c.raw_query[:200] if c.raw_query else ''
        ])
    
    # Return as downloadable CSV
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=citategenie_api_calls_{period}.csv'
        }
    )


# =============================================================================
# CLEAR LOGS ENDPOINT
# =============================================================================

@admin_bp.route('/api/clear-logs', methods=['POST'])
@requires_admin_key
def api_clear_logs():
    """
    Clear all logs from the database for a fresh start.
    
    POST /admin/api/clear-logs?key=ADMIN_SECRET
    
    Optional JSON body:
    {
        "confirm": true,           # Required confirmation
        "tables": ["api_calls", "document_sessions", "daily_stats"]  # Optional: specific tables
    }
    
    Returns counts of deleted records.
    """
    from billing.admin_models import APICall, DocumentSession, DailyStats
    
    data = request.get_json() or {}
    
    # Require explicit confirmation
    if not data.get('confirm'):
        return jsonify({
            'success': False,
            'error': 'Must include {"confirm": true} in request body'
        }), 400
    
    # Which tables to clear (default: all)
    tables_to_clear = data.get('tables', ['api_calls', 'document_sessions', 'daily_stats'])
    
    db = get_db()
    deleted_counts = {}
    
    try:
        # Clear in correct order (children before parents due to foreign keys)
        
        if 'api_calls' in tables_to_clear:
            count = db.query(APICall).delete()
            deleted_counts['api_calls'] = count
        
        if 'document_sessions' in tables_to_clear:
            count = db.query(DocumentSession).delete()
            deleted_counts['document_sessions'] = count
        
        if 'daily_stats' in tables_to_clear:
            count = db.query(DailyStats).delete()
            deleted_counts['daily_stats'] = count
        
        db.commit()
        
        total_deleted = sum(deleted_counts.values())
        
        return jsonify({
            'success': True,
            'message': f'Cleared {total_deleted} records',
            'deleted': deleted_counts,
            'cleared_at': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        db.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =============================================================================
# EXPORT ACCEPTED CITATIONS CSV
# =============================================================================

@admin_bp.route('/api/export/citations-csv')
@requires_admin_key
def api_export_citations_csv():
    """
    Export all accepted citations as CSV with full SourceComponents.
    
    GET /admin/api/export/citations-csv?key=ADMIN_SECRET&period=30d
    
    Query params:
        period: Time period (7d, 30d, 90d, all)
    
    Returns CSV file with columns for all SourceComponents fields.
    """
    from billing.admin_models import AcceptedCitation
    from zoneinfo import ZoneInfo
    
    period = request.args.get('period', '30d')
    start_date, end_date = get_date_range(period)
    
    est = ZoneInfo('America/New_York')
    
    db = get_db()
    
    citations = db.query(AcceptedCitation).filter(
        AcceptedCitation.accepted_at >= start_date,
        AcceptedCitation.accepted_at < end_date
    ).order_by(AcceptedCitation.accepted_at.desc()).all()
    
    # Build CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Header - comprehensive SourceComponents columns
    writer.writerow([
        'accepted_at_est', 'session_id', 'note_id', 'original_text', 'formatted_citation',
        'citation_style', 'citation_type', 'source_engine', 'confidence',
        'title', 'year', 'doi', 'url',
        'author1_last', 'author1_first', 'author2_last', 'author2_first', 
        'author3_last', 'author3_first', 'author4_last', 'author4_first',
        'journal', 'volume', 'issue', 'pages', 'pmid',
        'publisher', 'place', 'edition', 'isbn',
        'case_name', 'legal_citation', 'court', 'jurisdiction',
        'newspaper', 'access_date'
    ])
    
    # Data
    for c in citations:
        # Convert timestamp
        if c.accepted_at:
            ts_est = c.accepted_at.astimezone(est)
            ts_str = ts_est.strftime('%Y-%m-%d %H:%M:%S EST')
        else:
            ts_str = ''
        
        # Parse authors (stored as JSON array)
        authors = c.authors or []
        author_cols = [''] * 8  # 4 authors x 2 (last, first)
        for i, author in enumerate(authors[:4]):
            if isinstance(author, dict):
                author_cols[i*2] = author.get('family', author.get('last', ''))
                author_cols[i*2 + 1] = author.get('given', author.get('first', ''))
            elif isinstance(author, str):
                # Try to parse "Last, First" or "First Last"
                if ',' in author:
                    parts = author.split(',', 1)
                    author_cols[i*2] = parts[0].strip()
                    author_cols[i*2 + 1] = parts[1].strip() if len(parts) > 1 else ''
                else:
                    parts = author.rsplit(' ', 1)
                    if len(parts) == 2:
                        author_cols[i*2] = parts[1]  # Last
                        author_cols[i*2 + 1] = parts[0]  # First
                    else:
                        author_cols[i*2] = author
        
        writer.writerow([
            ts_str,
            c.session_id[:12] if c.session_id else '',
            c.note_id,
            (c.original_text or '')[:200],
            (c.formatted_citation or '')[:500],
            c.citation_style,
            c.citation_type,
            c.source_engine,
            c.confidence,
            c.title,
            c.year,
            c.doi,
            c.url,
            *author_cols,
            c.journal,
            c.volume,
            c.issue,
            c.pages,
            c.pmid,
            c.publisher,
            c.place,
            c.edition,
            c.isbn,
            c.case_name,
            c.legal_citation,
            c.court,
            c.jurisdiction,
            c.newspaper,
            c.access_date
        ])
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=citategenie_citations_{period}.csv'
        }
    )

