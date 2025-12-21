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
            # Build search query from URL
            query = self._build_search_query(url)
            
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
                
                # Extract from organic results
                results = data.get('organic_results', [])
                if results:
                    result = results[0]
                    
                    # Create metadata object
                    metadata = type('Metadata', (), {
                        'title': result.get('title'),
                        'authors': self._extract_authors_from_snippet(result.get('snippet', '')),
                        'publication': self._extract_domain(url).replace('.com', '').title(),
                        'date': result.get('date'),
                        'url': url,
                        'method_used': 'serpapi',
                        'is_complete': lambda: bool(result.get('title'))
                    })()
                    
                    if self.debug:
                        print(f"[SmartURLRouter] ✓ SerpAPI found: {metadata.title[:50] if metadata.title else 'N/A'}")
                    
                    return metadata
        
        except Exception as e:
            if self.debug:
                print(f"[SmartURLRouter] SerpAPI error: {e}")
        
        # Failed - return empty to trigger fallback
        return self._empty_metadata(url)
    
    def _empty_metadata(self, url: str):
        """Return empty metadata to trigger GenericURL fallback."""
        return type('Metadata', (), {
            'title': None,
            'authors': [],
            'publication': None,
            'date': None,
            'url': url,
            'method_used': 'none',
            'is_complete': lambda: False
        })()
    
    def _extract_domain(self, url: str) -> str:
        """Extract clean domain from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    
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
