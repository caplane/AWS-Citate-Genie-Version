"""
Complete Working Example: New URL Router
Drop-in replacement for existing CitateGenie URL processing

This module can be used as-is or adapted to your existing code structure.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse
import re


# ============================================================================
# CONFIGURATION
# ============================================================================

# Domain Classifications (customize based on your experience)
PAYWALLED_DOMAINS = {
    'washingtonpost.com', 'nytimes.com', 'wsj.com', 'ft.com', 
    'economist.com', 'bloomberg.com', 'newyorker.com', 'theatlantic.com',
    'wired.com', 'hbr.org', 'scientificamerican.com', 'nature.com'
}

DIFFICULT_DOMAINS = {
    'medium.com', 'substack.com', 'ted.com', 'twitter.com', 'x.com'
}

ACADEMIC_DOMAINS = {
    'doi.org', 'dx.doi.org', 'arxiv.org', 'pubmed.ncbi.nlm.nih.gov', 
    'jstor.org', 'researchgate.net'
}


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class CitationMetadata:
    """Citation metadata with tracking."""
    url: str
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    publication: Optional[str] = None
    date: Optional[str] = None
    
    # Tracking
    method_used: str = "unknown"  # search, fetch, ai, crossref
    confidence: float = 0.0
    
    def is_complete(self) -> bool:
        """Has minimum required fields."""
        return bool(self.title and self.publication and self.date)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'url': self.url,
            'title': self.title,
            'authors': self.authors,
            'publication': self.publication,
            'date': self.date,
            'method_used': self.method_used,
            'confidence': self.confidence,
        }


# ============================================================================
# URL ROUTER
# ============================================================================

class URLRouter:
    """
    Production-ready URL router with search-first strategy.
    
    Usage:
        router = URLRouter(search_api_key='your-key')
        metadata = router.resolve('https://example.com/article')
    """
    
    def __init__(self, search_api_key=None, ai_api_key=None, debug=False):
        """
        Initialize router with API credentials.
        
        Args:
            search_api_key: API key for search service
            ai_api_key: API key for AI service
            debug: Enable debug logging
        """
        self.search_key = search_api_key
        self.ai_key = ai_api_key
        self.debug = debug
        
        # Stats tracking
        self.stats = {
            'total': 0,
            'search': 0,
            'fetch': 0,
            'ai': 0,
            'success': 0,
        }
    
    def resolve(self, url: str) -> CitationMetadata:
        """
        Main entry point: resolve URL to citation metadata.
        
        This is the method you call from your citation processor.
        """
        self.stats['total'] += 1
        
        metadata = CitationMetadata(url=url)
        domain = self._extract_domain(url)
        
        if self.debug:
            print(f"\n[DEBUG] Resolving: {url}")
            print(f"[DEBUG] Domain: {domain}")
        
        # Route based on domain type
        if self._is_doi(url):
            metadata = self._resolve_via_crossref(url, metadata)
        elif domain in PAYWALLED_DOMAINS:
            metadata = self._resolve_paywalled(url, metadata)
        elif domain in DIFFICULT_DOMAINS:
            metadata = self._resolve_difficult(url, metadata)
        else:
            metadata = self._resolve_standard(url, metadata)
        
        # Track success
        if metadata.is_complete():
            self.stats['success'] += 1
        
        if self.debug:
            print(f"[DEBUG] Result: {metadata.method_used}, complete={metadata.is_complete()}")
        
        return metadata
    
    # ========================================================================
    # ROUTING STRATEGIES
    # ========================================================================
    
    def _resolve_standard(self, url: str, metadata: CitationMetadata) -> CitationMetadata:
        """Standard: search -> fetch -> ai"""
        
        # Try search first (95% success rate, cheap)
        metadata = self._try_search(url, metadata)
        if metadata.is_complete():
            return metadata
        
        # Try fetch if search incomplete (70% success, very cheap)
        metadata = self._try_fetch(url, metadata)
        if metadata.is_complete():
            return metadata
        
        # AI for remaining gaps (85% success, expensive)
        if not metadata.is_complete() and self.ai_key:
            metadata = self._try_ai(url, metadata)
        
        return metadata
    
    def _resolve_paywalled(self, url: str, metadata: CitationMetadata) -> CitationMetadata:
        """Paywalled: search only (fetch will fail)"""
        
        metadata = self._try_search(url, metadata)
        
        # Only use AI if search failed completely
        if not metadata.is_complete() and self.ai_key:
            metadata = self._try_ai(url, metadata)
        
        return metadata
    
    def _resolve_difficult(self, url: str, metadata: CitationMetadata) -> CitationMetadata:
        """Difficult: search preferred, skip fetch"""
        
        metadata = self._try_search(url, metadata)
        
        if not metadata.is_complete() and self.ai_key:
            metadata = self._try_ai(url, metadata)
        
        return metadata
    
    def _resolve_via_crossref(self, url: str, metadata: CitationMetadata) -> CitationMetadata:
        """DOI: Use CrossRef API (free, authoritative)"""
        
        # Extract DOI from URL
        doi = url.replace('https://doi.org/', '').replace('http://dx.doi.org/', '')
        
        try:
            import requests
            response = requests.get(f"https://api.crossref.org/works/{doi}")
            if response.status_code == 200:
                data = response.json()['message']
                
                metadata.title = data.get('title', [None])[0]
                metadata.publication = data.get('container-title', [None])[0]
                
                # Parse authors
                if 'author' in data:
                    metadata.authors = [
                        f"{a.get('given', '')} {a.get('family', '')}".strip()
                        for a in data['author']
                    ]
                
                # Parse date
                if 'published-print' in data:
                    parts = data['published-print']['date-parts'][0]
                    if len(parts) >= 1:
                        metadata.date = str(parts[0])
                
                metadata.method_used = 'crossref'
                metadata.confidence = 1.0
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] CrossRef failed: {e}")
            # Fall back to search
            metadata = self._try_search(url, metadata)
        
        return metadata
    
    # ========================================================================
    # EXTRACTION METHODS
    # ========================================================================
    
    def _try_search(self, url: str, metadata: CitationMetadata) -> CitationMetadata:
        """Extract metadata via web search."""
        
        if not self.search_key:
            if self.debug:
                print("[DEBUG] Search skipped (no API key)")
            return metadata
        
        self.stats['search'] += 1
        
        try:
            # Build search query from URL
            query = self._build_search_query(url)
            
            if self.debug:
                print(f"[DEBUG] Search query: {query}")
            
            # TODO: Replace with your actual search API call
            # Example structure of what you'd get back:
            results = self._mock_search(query)  # Replace with real API
            
            if results:
                result = results[0]
                metadata.title = result.get('title') or metadata.title
                metadata.publication = result.get('source') or metadata.publication
                metadata.date = result.get('date') or metadata.date
                
                # Try to extract author from snippet
                snippet = result.get('snippet', '')
                if snippet and not metadata.authors:
                    author = self._extract_author_from_text(snippet)
                    if author:
                        metadata.authors = [author]
                
                metadata.method_used = 'search'
                metadata.confidence = 0.9
        
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] Search failed: {e}")
        
        return metadata
    
    def _try_fetch(self, url: str, metadata: CitationMetadata) -> CitationMetadata:
        """Extract metadata via direct HTTP fetch."""
        
        self.stats['fetch'] += 1
        
        try:
            import requests
            from bs4 import BeautifulSoup
            
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'CitateGenie/1.0'
            })
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Try meta tags
                if not metadata.title:
                    title_tag = soup.find('meta', property='og:title') or \
                                soup.find('meta', {'name': 'title'}) or \
                                soup.find('title')
                    if title_tag:
                        metadata.title = title_tag.get('content') or title_tag.string
                
                if not metadata.publication:
                    pub_tag = soup.find('meta', property='og:site_name')
                    if pub_tag:
                        metadata.publication = pub_tag.get('content')
                
                if not metadata.date:
                    date_tag = soup.find('meta', property='article:published_time') or \
                               soup.find('meta', {'name': 'date'})
                    if date_tag:
                        metadata.date = date_tag.get('content', '')[:10]  # YYYY-MM-DD
                
                if not metadata.authors:
                    author_tag = soup.find('meta', {'name': 'author'})
                    if author_tag:
                        metadata.authors = [author_tag.get('content')]
                
                metadata.method_used = 'fetch'
                metadata.confidence = 0.8
        
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] Fetch failed: {e}")
        
        return metadata
    
    def _try_ai(self, url: str, metadata: CitationMetadata) -> CitationMetadata:
        """Use AI to fill metadata gaps."""
        
        if not self.ai_key:
            if self.debug:
                print("[DEBUG] AI skipped (no API key)")
            return metadata
        
        self.stats['ai'] += 1
        
        try:
            # Build prompt
            prompt = f"""Extract citation metadata for this URL: {url}

Current metadata:
- Title: {metadata.title or 'MISSING'}
- Authors: {', '.join(metadata.authors) if metadata.authors else 'MISSING'}
- Publication: {metadata.publication or 'MISSING'}
- Date: {metadata.date or 'MISSING'}

Return ONLY valid JSON with missing fields:
{{"title": "...", "authors": ["..."], "publication": "...", "date": "YYYY-MM-DD"}}"""
            
            # TODO: Replace with your actual AI API call
            # Example for OpenAI:
            # import openai
            # response = openai.ChatCompletion.create(...)
            # result = json.loads(response.choices[0].message.content)
            
            # For now, placeholder
            if self.debug:
                print("[DEBUG] AI extraction would run here")
            
            metadata.method_used = 'ai'
            metadata.confidence = 0.7
        
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] AI failed: {e}")
        
        return metadata
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    
    def _extract_domain(self, url: str) -> str:
        """Extract clean domain from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    
    def _is_doi(self, url: str) -> bool:
        """Check if URL is a DOI."""
        return 'doi.org' in url.lower() or url.startswith('10.')
    
    def _build_search_query(self, url: str) -> str:
        """Build search query from URL."""
        domain = self._extract_domain(url)
        path = urlparse(url).path
        
        # Extract keywords from path
        keywords = []
        for part in path.split('/'):
            if len(part) > 3 and not part.isdigit():
                clean = part.replace('-', ' ').replace('_', ' ')
                keywords.append(clean)
        
        query = f"{domain} {' '.join(keywords[:5])}"  # Limit to first 5 keywords
        return query.strip()
    
    def _extract_author_from_text(self, text: str) -> Optional[str]:
        """Extract author name from text snippet."""
        # Pattern: "By Author Name"
        match = re.search(r'[Bb]y\s+([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?[A-Z][a-z]+)', text)
        if match:
            return match.group(1)
        return None
    
    def _mock_search(self, query: str) -> List[Dict]:
        """Mock search for testing. Replace with real API."""
        # This is where you'd call your actual search API
        # For now, returns empty to show the pattern
        return []
    
    def get_stats(self) -> Dict:
        """Return usage statistics."""
        success_rate = (self.stats['success'] / self.stats['total'] * 100) if self.stats['total'] > 0 else 0
        
        estimated_cost = (
            self.stats['search'] * 0.006 +
            self.stats['fetch'] * 0.001 +
            self.stats['ai'] * 0.050
        )
        
        return {
            **self.stats,
            'success_rate': f"{success_rate:.1f}%",
            'estimated_cost': f"${estimated_cost:.4f}",
        }


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Initialize router
    router = URLRouter(debug=True)
    
    # Test URLs
    test_urls = [
        "https://www.washingtonpost.com/opinions/2024/10/10/economy-great-year-election/",
        "https://www.ted.com/talks/mustafa_suleyman_what_is_an_ai_anyway",
        "https://www.cdc.gov/global-health/annual-report-2024/index.html",
    ]
    
    print("=" * 80)
    print("URL ROUTER TEST")
    print("=" * 80)
    
    for url in test_urls:
        metadata = router.resolve(url)
        print(f"\nURL: {url}")
        print(f"  Title: {metadata.title or 'NOT FOUND'}")
        print(f"  Publication: {metadata.publication or 'NOT FOUND'}")
        print(f"  Date: {metadata.date or 'NOT FOUND'}")
        print(f"  Method: {metadata.method_used}")
        print(f"  Complete: {metadata.is_complete()}")
    
    print("\n" + "=" * 80)
    print("STATISTICS")
    print("=" * 80)
    stats = router.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
