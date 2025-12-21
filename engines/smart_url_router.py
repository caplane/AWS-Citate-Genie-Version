"""
Cost-Effective URL Router for CitateGenie
Uses SerpAPI strategically only for paywalled content

Strategy:
- Paywalled sites (WaPo, NYT, etc.): Use SerpAPI ($0.005/search) - WORTH IT
- Open sites (CDC, .gov, etc.): Use direct fetch (free)
- AI fallback: Only when both fail

Cost comparison:
- SerpAPI: $0.005/search
- AI: $0.05/call (10x more expensive)
- Direct fetch: Free

For paywalled content:
- Old way: Fetch (fails) → AI ($0.05) = Expensive + unreliable
- New way: SerpAPI ($0.005) = Cheap + reliable
- Savings: 90% cost reduction on paywalled URLs!
"""

import requests
from typing import Optional
from urllib.parse import urlparse

from config import SERPAPI_KEY
from cost_tracker import log_api_call


# Domains known to block direct fetching
PAYWALLED_DOMAINS = {
    'washingtonpost.com',
    'nytimes.com', 
    'wsj.com',
    'economist.com',
    'ft.com',
    'bloomberg.com',
    'newyorker.com',
    'theatlantic.com',
    'wired.com',
    'foreignaffairs.com',
    'harpers.org',
    'scientificamerican.com',
}


class SmartURLRouter:
    """
    Cost-effective URL metadata extraction.
    
    Uses SerpAPI ONLY for paywalled sites where it saves money vs AI fallback.
    """
    
    def __init__(self, debug=False):
        self.debug = debug
        self.has_serpapi = bool(SERPAPI_KEY)
        
        if self.debug:
            print(f"[SmartURLRouter] SerpAPI available: {self.has_serpapi}")
    
    def resolve(self, url: str):
        """
        Resolve URL using most cost-effective method.
        
        Returns metadata object compatible with wrapper.
        """
        domain = self._extract_domain(url)
        
        # Decide routing based on domain
        if domain in PAYWALLED_DOMAINS:
            if self.has_serpapi:
                # Worth using SerpAPI - cheaper than AI and more reliable than fetch
                return self._search_via_serpapi(url)
            else:
                # No SerpAPI, will fall back to GenericURL in wrapper
                return self._empty_metadata(url)
        else:
            # Open access - let GenericURL handle it (free)
            return self._empty_metadata(url)
    
    def _search_via_serpapi(self, url: str):
        """
        Search for URL metadata via SerpAPI.
        
        Cost: $0.005/search (much cheaper than $0.05 AI call)
        """
        if self.debug:
            print(f"[SmartURLRouter] Using SerpAPI for paywalled URL: {url[:60]}")
        
        try:
            # Call SerpAPI
            params = {
                'engine': 'google',
                'q': url,  # Search for exact URL
                'api_key': SERPAPI_KEY,
                'num': 1
            }
            
            response = requests.get(
                'https://serpapi.com/search',
                params=params,
                timeout=10
            )
            
            # Log cost
            log_api_call('serpapi', query=url, function='url_metadata')
            
            if response.status_code == 200:
                data = response.json()
                
                if self.debug:
                    print(f"[SmartURLRouter] SerpAPI response status: {response.status_code}")
                    print(f"[SmartURLRouter] Organic results count: {len(data.get('organic_results', []))}")
                
                # Extract from organic results
                results = data.get('organic_results', [])
                if results:
                    result = results[0]
                    
                    # Extract metadata
                    title = result.get('title')
                    snippet = result.get('snippet', '')
                    date = result.get('date')
                    authors = self._extract_authors_from_snippet(snippet)
                    publication = self._extract_publication_name(url)
                    
                    if self.debug:
                        print(f"[SmartURLRouter] Extracted title: {title}")
                        print(f"[SmartURLRouter] Extracted authors: {authors}")
                        print(f"[SmartURLRouter] Extracted date: {date}")
                        print(f"[SmartURLRouter] Extracted publication: {publication}")
                    
                    # Create metadata object with actual values (not lambdas)
                    class Metadata:
                        def __init__(self):
                            self.title = title
                            self.authors = authors
                            self.publication = publication
                            self.date = date
                            self.url = url
                            self.method_used = 'serpapi'
                        
                        def is_complete(self):
                            # Must have at least title to be useful
                            return bool(self.title)
                    
                    metadata = Metadata()
                    
                    if self.debug:
                        print(f"[SmartURLRouter] ✓ SerpAPI found: {metadata.title[:50] if metadata.title else 'N/A'}")
                        print(f"[SmartURLRouter] is_complete: {metadata.is_complete()}")
                    
                    return metadata
        
        except Exception as e:
            if self.debug:
                print(f"[SmartURLRouter] SerpAPI error: {e}")
            import traceback
            if self.debug:
                traceback.print_exc()
        
        # Failed - return empty to trigger fallback
        if self.debug:
            print(f"[SmartURLRouter] SerpAPI failed, returning empty metadata")
        return self._empty_metadata(url)
    
    def _empty_metadata(self, url: str):
        """Return empty metadata to trigger GenericURL fallback."""
        class EmptyMetadata:
            def __init__(self):
                self.title = None
                self.authors = []
                self.publication = None
                self.date = None
                self.url = url
                self.method_used = 'none'
            
            def is_complete(self):
                return False
        
        return EmptyMetadata()
    
    def _extract_domain(self, url: str) -> str:
        """Extract clean domain from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    
    def _extract_publication_name(self, url: str) -> str:
        """Extract publication name from domain."""
        domain = self._extract_domain(url)
        
        # Map common domains to proper publication names
        publication_map = {
            'washingtonpost.com': 'Washington Post',
            'nytimes.com': 'New York Times',
            'wsj.com': 'Wall Street Journal',
            'economist.com': 'The Economist',
            'ft.com': 'Financial Times',
            'bloomberg.com': 'Bloomberg',
            'newyorker.com': 'The New Yorker',
            'theatlantic.com': 'The Atlantic',
            'wired.com': 'Wired',
            'foreignaffairs.com': 'Foreign Affairs',
            'scientificamerican.com': 'Scientific American',
            'axios.com': 'Axios',
            'npr.org': 'NPR',
        }
        
        if domain in publication_map:
            return publication_map[domain]
        
        # Fallback: capitalize domain name
        return domain.replace('.com', '').replace('.org', '').replace('.net', '').title()
    
    def _build_search_query(self, url: str) -> str:
        """Build search query from URL for better results."""
        # For now, just return the URL
        # SerpAPI will find the page
        return url
    
    def _extract_authors_from_snippet(self, snippet: str) -> list:
        """Extract author from snippet if present."""
        import re
        
        # Pattern: "By Author Name"
        match = re.search(r'[Bb]y\s+([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?[A-Z][a-z]+)', snippet)
        if match:
            return [match.group(1)]
        
        return []


# Cost tracking stats
def get_url_routing_stats():
    """
    Get statistics on URL routing costs.
    
    Use this to monitor if SerpAPI usage is cost-effective.
    """
    return {
        'serpapi_calls': 0,  # Tracked via cost_tracker
        'ai_fallbacks': 0,   # Tracked via cost_tracker
        'direct_fetches': 0, # Free
        'estimated_serpapi_cost': 0.0,
        'estimated_ai_cost': 0.0,
        'total_cost': 0.0,
    }
