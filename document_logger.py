"""
document_logger.py

Per-document citation processing logs with cost tracking and source attribution.

Creates detailed CSV logs for each processed document showing:
- Each citation/URL processed
- Source API used (Crossref, PubMed, TheNewsAPI, SerpAPI, etc.)
- Cost per API call
- Citation components extracted (title, authors, date, journal, etc.)
- Success/failure status
- Total document cost

Log files saved to: logs/documents/YYYYMMDD_HHMMSS_sessionid.csv
"""

import os
import csv
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

# API Cost structure (per call)
API_COSTS = {
    # Free APIs
    'crossref': 0.0,
    'openalex': 0.0,
    'pubmed': 0.0,
    'semantic_scholar': 0.0,
    'thenewsapi': 0.0,
    'newsdata': 0.0,
    'doi_lookup': 0.0,
    'html_scrape': 0.0,
    'generic_url': 0.0,
    'google_books': 0.0,
    'open_library': 0.0,
    'loc': 0.0,  # Library of Congress
    'courtlistener': 0.0,
    'famous_papers_cache': 0.0,
    'legal_cache': 0.0,
    
    # Paid APIs
    'serpapi': 0.005,
    'serpapi_news': 0.01,
    'google_scholar': 0.01,
    'openai': 0.002,  # GPT-4o-mini
    'anthropic': 0.003,  # Claude Haiku
    'gemini': 0.00015,  # Gemini Flash
}


class DocumentLogger:
    """
    Tracks citation processing for a single document.
    
    Usage:
        logger = DocumentLogger(session_id="abc123", filename="My Paper.docx")
        
        # Log each citation as processed
        logger.log_citation(
            query="Smith 2020",
            source="crossref",
            success=True,
            title="Machine Learning in Medicine",
            authors=["John Smith", "Jane Doe"],
            year="2020",
            journal="Nature Medicine"
        )
        
        # Save log when done
        logger.save()
    """
    
    def __init__(self, session_id: str, filename: str, user_id: int = None):
        self.session_id = session_id
        self.filename = filename
        self.user_id = user_id
        self.timestamp = datetime.now()
        
        # Track all citations processed
        self.citations: List[Dict[str, Any]] = []
        
        # Running totals
        self.total_cost = 0.0
        self.total_citations = 0
        self.successful_citations = 0
        self.failed_citations = 0
        
        # API usage counts
        self.api_usage = {}
        
        # Create logs directory if needed
        self.log_dir = Path('logs/documents')
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def log_citation(
        self,
        query: str,
        source: str,
        success: bool,
        **components
    ):
        """
        Log a single citation processing attempt.
        
        Args:
            query: Original citation text/URL from document
            source: API/engine used (e.g., 'crossref', 'serpapi', 'thenewsapi')
            success: Whether citation was successfully resolved
            **components: Citation components (title, authors, year, etc.)
        
        Example:
            logger.log_citation(
                query="https://www.nytimes.com/...",
                source="thenewsapi",
                success=True,
                title="Breaking News Story",
                authors=["Jane Reporter"],
                newspaper="The New York Times",
                date="December 21, 2024"
            )
        """
        # Get cost for this API call
        cost = API_COSTS.get(source, 0.0)
        
        # Track totals
        self.total_cost += cost
        self.total_citations += 1
        if success:
            self.successful_citations += 1
        else:
            self.failed_citations += 1
        
        # Track API usage
        if source not in self.api_usage:
            self.api_usage[source] = {'count': 0, 'cost': 0.0}
        self.api_usage[source]['count'] += 1
        self.api_usage[source]['cost'] += cost
        
        # Store citation record
        citation_record = {
            'citation_number': self.total_citations,
            'query': query,
            'source': source,
            'success': success,
            'cost': cost,
            'timestamp': datetime.now().isoformat(),
            
            # Citation components (all optional)
            'title': components.get('title', ''),
            'authors': self._format_authors(components.get('authors', [])),
            'year': components.get('year', ''),
            'date': components.get('date', ''),
            'journal': components.get('journal', ''),
            'newspaper': components.get('newspaper', ''),
            'publisher': components.get('publisher', ''),
            'place': components.get('place', ''),
            'volume': components.get('volume', ''),
            'issue': components.get('issue', ''),
            'pages': components.get('pages', ''),
            'doi': components.get('doi', ''),
            'url': components.get('url', ''),
            'case_name': components.get('case_name', ''),
            'court': components.get('court', ''),
            'citation': components.get('citation', ''),
        }
        
        self.citations.append(citation_record)
    
    def _format_authors(self, authors):
        """Format author list for CSV."""
        if not authors:
            return ''
        if isinstance(authors, list):
            return '; '.join(authors)
        return str(authors)
    
    def save(self) -> str:
        """
        Save document log to CSV file.
        
        Returns:
            Path to saved log file
        """
        # Generate filename: YYYYMMDD_HHMMSS_sessionid.csv
        timestamp_str = self.timestamp.strftime('%Y%m%d_%H%M%S')
        log_filename = f"{timestamp_str}_{self.session_id}.csv"
        log_path = self.log_dir / log_filename
        
        # CSV columns
        fieldnames = [
            'citation_number',
            'query',
            'source',
            'success',
            'cost',
            'timestamp',
            'title',
            'authors',
            'year',
            'date',
            'journal',
            'newspaper',
            'publisher',
            'place',
            'volume',
            'issue',
            'pages',
            'doi',
            'url',
            'case_name',
            'court',
            'citation',
        ]
        
        # Write CSV
        with open(log_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.citations)
        
        # Also save summary
        self._save_summary(log_path)
        
        print(f"[DocumentLogger] Saved log: {log_path}")
        print(f"[DocumentLogger] Total cost: ${self.total_cost:.4f}")
        print(f"[DocumentLogger] Success rate: {self.successful_citations}/{self.total_citations}")
        
        return str(log_path)
    
    def _save_summary(self, csv_path: Path):
        """Save summary metadata file alongside CSV."""
        summary_path = csv_path.with_suffix('.summary.txt')
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(f"CitateGenie Document Processing Summary\n")
            f.write(f"{'=' * 60}\n\n")
            
            f.write(f"Document: {self.filename}\n")
            f.write(f"Session ID: {self.session_id}\n")
            if self.user_id:
                f.write(f"User ID: {self.user_id}\n")
            f.write(f"Processed: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write(f"TOTALS\n")
            f.write(f"{'-' * 60}\n")
            f.write(f"Total Citations: {self.total_citations}\n")
            f.write(f"Successful: {self.successful_citations}\n")
            f.write(f"Failed: {self.failed_citations}\n")
            f.write(f"Success Rate: {(self.successful_citations/self.total_citations*100):.1f}%\n\n")
            
            f.write(f"COSTS\n")
            f.write(f"{'-' * 60}\n")
            f.write(f"Total Cost: ${self.total_cost:.4f}\n")
            f.write(f"Average per Citation: ${(self.total_cost/self.total_citations):.4f}\n\n")
            
            f.write(f"API USAGE\n")
            f.write(f"{'-' * 60}\n")
            for api, stats in sorted(self.api_usage.items(), key=lambda x: x[1]['cost'], reverse=True):
                f.write(f"{api:20s} {stats['count']:4d} calls  ${stats['cost']:.4f}\n")
            
            f.write(f"\n")
            f.write(f"Detailed log: {csv_path.name}\n")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics as dictionary."""
        return {
            'session_id': self.session_id,
            'filename': self.filename,
            'timestamp': self.timestamp.isoformat(),
            'total_citations': self.total_citations,
            'successful': self.successful_citations,
            'failed': self.failed_citations,
            'success_rate': (self.successful_citations / self.total_citations * 100) if self.total_citations > 0 else 0,
            'total_cost': self.total_cost,
            'avg_cost_per_citation': (self.total_cost / self.total_citations) if self.total_citations > 0 else 0,
            'api_usage': self.api_usage,
        }


# ============================================================================
# INTEGRATION HELPERS
# ============================================================================

def log_from_source_components(
    logger: DocumentLogger,
    query: str,
    components,
    source: str = None
):
    """
    Log citation from SourceComponents object.
    
    Args:
        logger: DocumentLogger instance
        query: Original citation text
        components: SourceComponents object
        source: Override source (if None, uses components.source_engine)
    """
    if components is None:
        logger.log_citation(
            query=query,
            source=source or 'unknown',
            success=False
        )
        return
    
    # Determine source
    api_source = source or components.source_engine or 'unknown'
    
    # Map source_engine to API name
    source_mapping = {
        'Crossref': 'crossref',
        'OpenAlex': 'openalex',
        'PubMed': 'pubmed',
        'Semantic Scholar': 'semantic_scholar',
        'Google Books': 'google_books',
        'Open Library': 'open_library',
        'Library of Congress': 'loc',
        'Legal Cache/CourtListener': 'courtlistener',
        'Famous Papers Cache': 'famous_papers_cache',
        'Generic URL': 'generic_url',
        'ChatGPT': 'openai',
        'Claude': 'anthropic',
        'Gemini': 'gemini',
    }
    
    api_source = source_mapping.get(api_source, api_source.lower().replace(' ', '_'))
    
    # Extract components
    logger.log_citation(
        query=query,
        source=api_source,
        success=components.has_minimum_data(),
        title=components.title or '',
        authors=components.authors or [],
        year=components.year or '',
        date=components.date or '',
        journal=components.journal or '',
        newspaper=components.newspaper or '',
        publisher=components.publisher or '',
        place=components.place or '',
        volume=components.volume or '',
        issue=components.issue or '',
        pages=components.pages or '',
        doi=components.doi or '',
        url=components.url or '',
        case_name=components.case_name or '',
        court=components.court or '',
        citation=components.citation or '',
    )


def log_url_resolution(
    logger: DocumentLogger,
    url: str,
    metadata,
    method: str
):
    """
    Log URL resolution (from unified_router _route_url).
    
    Args:
        logger: DocumentLogger instance
        url: URL being resolved
        metadata: Metadata object or SourceComponents
        method: Resolution method (serpapi, thenewsapi, newsdata, html_scrape, etc.)
    """
    if hasattr(metadata, 'method_used'):
        # Smart router metadata
        method = metadata.method_used
    
    if hasattr(metadata, 'is_complete') and callable(metadata.is_complete):
        # Smart router metadata
        success = metadata.is_complete()
        title = getattr(metadata, 'title', '')
        authors = getattr(metadata, 'authors', [])
        date = getattr(metadata, 'date', '')
        publication = getattr(metadata, 'publication', '')
    else:
        # SourceComponents
        success = metadata.has_minimum_data() if metadata else False
        title = metadata.title if metadata else ''
        authors = metadata.authors if metadata else []
        date = metadata.date if metadata else ''
        publication = metadata.newspaper if metadata else ''
    
    logger.log_citation(
        query=url,
        source=method,
        success=success,
        title=title,
        authors=authors,
        date=date,
        newspaper=publication,
        url=url
    )


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == '__main__':
    # Example: Log a document processing session
    logger = DocumentLogger(
        session_id="test123",
        filename="Research Paper.docx",
        user_id=42
    )
    
    # Log successful Crossref lookup
    logger.log_citation(
        query="Smith et al 2020",
        source="crossref",
        success=True,
        title="Machine Learning in Medicine",
        authors=["John Smith", "Jane Doe", "Bob Wilson"],
        year="2020",
        journal="Nature Medicine",
        volume="26",
        issue="3",
        pages="445-452",
        doi="10.1038/s41591-020-0123-4"
    )
    
    # Log successful news API lookup
    logger.log_citation(
        query="https://www.nytimes.com/2024/12/21/...",
        source="thenewsapi",
        success=True,
        title="Breaking News Story",
        authors=["Jane Reporter"],
        newspaper="The New York Times",
        date="December 21, 2024",
        url="https://www.nytimes.com/2024/12/21/..."
    )
    
    # Log paid API usage (SerpAPI)
    logger.log_citation(
        query="https://www.washingtonpost.com/...",
        source="serpapi_news",
        success=True,
        title="Washington Post Article",
        authors=["John Journalist"],
        newspaper="The Washington Post",
        date="December 20, 2024"
    )
    
    # Log failed lookup
    logger.log_citation(
        query="Obscure reference 1887",
        source="crossref",
        success=False
    )
    
    # Save log
    log_path = logger.save()
    
    print(f"\nLog saved to: {log_path}")
    print(f"\nSummary:")
    import json
    print(json.dumps(logger.get_summary(), indent=2))
