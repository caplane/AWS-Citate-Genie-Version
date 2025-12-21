"""
Smart URL Router V4 - Waterfall News Resolution
Cost-optimized routing with free sources first

STRATEGY:
1. News domains → WaterfallNewsResolver (FREE sources first)
2. Non-news paywalled → SerpAPI regular Google (PAID)
3. Open content → Return empty for GenericURL (FREE)

COST REDUCTION:
- News URLs: 90%+ resolved by free tier (Google RSS, etc.)
- SerpAPI only used as last resort for news
- Expected savings: $45+ per month (from $50 to ~$5)
"""

import requests
from typing import Optional
from urllib.parse import urlparse

from config import SERPAPI_KEY
from cost_tracker import log_api_call
from waterfall_news_resolver import WaterfallNewsResolver


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
    'axios.com',
    'npr.org',
    'politico.com',
    'reuters.com',
    'apnews.com',
}

# News domains (use waterfall instead of SerpAPI directly)
NEWS_DOMAINS = {
    'washingtonpost.com',
    'nytimes.com',
    'wsj.com',
    'theatlantic.com',
    'newyorker.com',
    'wired.com',
    'axios.com',
    'npr.org',
    'politico.com',
    'reuters.com',
    'apnews.com',
    'cnn.com',
    'bbc.com',
    'theguardian.com',
    'usatoday.com',
    'latimes.com',
    'chicagotribune.com',
    'bostonglobe.com',
}


class SmartURLRouter:
    """
    Cost-effective URL metadata extraction with waterfall strategy.
    
    Uses free news sources first, SerpAPI only as last resort.
    """
    
    def __init__(self, debug=False):
        self.debug = debug
        self.has_serpapi = bool(SERPAPI_KEY)
        
        # Initialize waterfall resolver for news
        self.waterfall = WaterfallNewsResolver(debug=debug)
        
        if self.debug:
            print(f"[SmartURLRouter] Initialized with waterfall strategy")
            print(f"[SmartURLRouter] SerpAPI available: {self.has_serpapi}")
    
    def resolve(self, url: str):
        """
        Resolve URL using cost-optimized method.
        
        Returns metadata object compatible with wrapper.
        """
        domain = self._extract_domain(url)
        
        # Route based on domain type
        if domain in NEWS_DOMAINS:
            # NEWS: Use waterfall (FREE sources first)
            if self.debug:
                print(f"[SmartURLRouter] News domain detected, using waterfall...")
            return self.waterfall.resolve(url)
        
        elif domain in PAYWALLED_DOMAINS:
            # NON-NEWS PAYWALL: Use SerpAPI directly (no free alternative)
            if self.has_serpapi:
                if self.debug:
                    print(f"[SmartURLRouter] Non-news paywall, using SerpAPI...")
                return self._search_via_serpapi(url)
            else:
                return self._empty_metadata(url)
        
        else:
            # OPEN ACCESS: Let GenericURL handle it (free HTML scraping)
            return self._empty_metadata(url)
    
    def _search_via_serpapi(self, url: str):
        """
        Search via SerpAPI (PAID, for non-news paywalled content).
        
        Only called for paywalled non-news sites (Economist, Bloomberg, etc.)
        """
        if self.debug:
            print(f"[SmartURLRouter] Using SerpAPI for non-news paywall: {url[:60]}")
        
        try:
            # Use regular Google search for non-news
            params = {
                'engine': 'google',
                'q': url,
                'api_key': SERPAPI_KEY,
                'num': 1
            }
            
            response = requests.get(
                'https://serpapi.com/search',
                params=params,
                timeout=10
            )
            
            # Log cost
            log_api_call('serpapi', query=url, function='url_metadata_nonnews')
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('organic_results', [])
                
                if self.debug:
                    print(f"[SmartURLRouter] SerpAPI response status: {response.status_code}")
                    print(f"[SmartURLRouter] Organic results count: {len(results)}")
                
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
                    
                    # Create metadata object
                    class Metadata:
                        def __init__(self):
                            self.title = title
                            self.authors = authors
                            self.publication = publication
                            self.date = date
                            self.url = url
                            self.method_used = 'serpapi'
                        
                        def is_complete(self):
                            return bool(self.title)
                    
                    metadata = Metadata()
                    
                    if self.debug:
                        print(f"[SmartURLRouter] ✓ SerpAPI found: {metadata.title[:50] if metadata.title else 'N/A'}")
                    
                    return metadata
        
        except Exception as e:
            if self.debug:
                print(f"[SmartURLRouter] SerpAPI error: {e}")
        
        # Failed
        if self.debug:
            print(f"[SmartURLRouter] SerpAPI failed, returning empty metadata")
        return self._empty_metadata(url)
    
    def _extract_domain(self, url: str) -> str:
        """Extract clean domain from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    
    def _extract_publication_name(self, url: str) -> str:
        """Map domain to publication name."""
        domain = self._extract_domain(url)
        
        publication_map = {
            'economist.com': 'The Economist',
            'ft.com': 'Financial Times',
            'bloomberg.com': 'Bloomberg',
            'foreignaffairs.com': 'Foreign Affairs',
            'harpers.org': "Harper's Magazine",
            'scientificamerican.com': 'Scientific American',
        }
        
        return publication_map.get(domain, domain.replace('.com', '').title())
    
    def _extract_authors_from_snippet(self, snippet: str) -> list:
        """Extract author from snippet if present."""
        if not snippet:
            return []
        
        import re
        match = re.search(r'[Bb]y\s+([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?[A-Z][a-z]+)', snippet)
        if match:
            return [match.group(1)]
        
        return []
    
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
    
    def get_stats(self):
        """Get usage statistics."""
        return self.waterfall.get_stats()
