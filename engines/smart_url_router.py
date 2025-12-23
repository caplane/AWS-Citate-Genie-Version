"""
Cost-Effective URL Router for CitateGenie
Uses News APIs first, then SerpAPI fallback for paywalled content

Strategy:
- News sites: Try TheNewsAPI (free 100/day) → NewsData (free 200/day) → SerpAPI ($0.005) → AI ($0.05)
- Open sites (CDC, .gov, etc.): Use direct fetch (free)
- AI fallback: Only when all else fails

Cost comparison:
- TheNewsAPI: FREE (100/day limit)
- NewsData: FREE (200/day limit)
- SerpAPI: $0.005/search
- AI: $0.05/call (10x more expensive than SerpAPI)
- Direct fetch: Free

Total free daily capacity: 300 news URLs before hitting paid APIs!
"""

import requests
from typing import Optional
from urllib.parse import urlparse
import time

from config import SERPAPI_KEY, THENEWSAPI_KEY, NEWSDATA_KEY
from cost_tracker import log_api_call

# AI fallback for author extraction when SERPAPI/News APIs return title but no author
try:
    from engines.ai_lookup import lookup_newspaper_url
    AI_AUTHOR_FALLBACK = True
except ImportError:
    AI_AUTHOR_FALLBACK = False
    lookup_newspaper_url = None


# News/magazine domains that should use news APIs
NEWS_DOMAINS = {
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
    'politico.com',
    'reuters.com',
    'apnews.com',
    'forbes.com',
    'time.com',
    'newsweek.com',
    'vox.com',
    'vice.com',
    'cnn.com',
    'foxnews.com',
    'nbcnews.com',
    'cbsnews.com',
    'abcnews.go.com',
    'latimes.com',
    'chicagotribune.com',
    'bostonglobe.com',
    'usatoday.com',
    'nypost.com',
    'theguardian.com',
    'bbc.com',
    'bbc.co.uk',
    'telegraph.co.uk',
    'independent.co.uk',
    'npr.org',
}

# Domains known to block direct fetching (subset of NEWS_DOMAINS)
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
    
    Priority cascade:
    1. TheNewsAPI (free, 100/day)
    2. NewsData (free, 200/day)
    3. SerpAPI ($0.005/search)
    4. GenericURL fallback (caller handles AI)
    """
    
    def __init__(self, debug=False):
        self.debug = debug
        self.has_thenewsapi = bool(THENEWSAPI_KEY)
        self.has_newsdata = bool(NEWSDATA_KEY)
        self.has_serpapi = bool(SERPAPI_KEY)
        
        if self.debug:
            print(f"[SmartURLRouter] TheNewsAPI: {self.has_thenewsapi}")
            print(f"[SmartURLRouter] NewsData: {self.has_newsdata}")
            print(f"[SmartURLRouter] SerpAPI: {self.has_serpapi}")
    
    def resolve(self, url: str):
        """
        Resolve URL using most cost-effective method.
        
        Returns metadata object compatible with wrapper.
        """
        domain = self._extract_domain(url)
        
        # For news domains, try news APIs first (free!)
        if domain in NEWS_DOMAINS:
            # Try free APIs first
            if self.has_thenewsapi:
                result = self._search_thenewsapi(url)
                if result.is_complete():
                    return result
            
            if self.has_newsdata:
                result = self._search_newsdata(url)
                if result.is_complete():
                    return result
            
            # Fall back to SerpAPI if news APIs failed
            if self.has_serpapi:
                return self._search_via_serpapi(url)
            
            # No APIs available, fall back to GenericURL
            return self._empty_metadata(url)
        else:
            # Non-news domain - let GenericURL handle it (free)
            return self._empty_metadata(url)
    
    def _search_via_serpapi(self, url: str):
        """
        Search for URL metadata via SerpAPI.
        
        Cost: $0.005/search (much cheaper than $0.05 AI call)
        
        Strategy:
        1. For newspapers/magazines: Use Google News API (better indexing)
        2. For other paywalled sites: Use regular Google Search
        3. If 0 results: Try keyword search fallback
        """
        if self.debug:
            print(f"[SmartURLRouter] Using SerpAPI for paywalled URL: {url[:60]}")
        
        try:
            domain = self._extract_domain(url)
            
            # Decide which engine to use
            # Google News is better for newspapers and magazines
            is_news = self._is_news_domain(domain)
            
            if is_news:
                # Extract keywords from URL for news search
                keywords = self._extract_keywords_from_url(url)
                publication = self._extract_publication_name(url)
                
                if self.debug:
                    print(f"[SmartURLRouter] Using Google News API for news domain")
                    print(f"[SmartURLRouter] Search keywords: {keywords}")
                
                # Google News works better with keywords than exact URLs
                params = {
                    'engine': 'google_news',
                    'q': keywords,  # Search with keywords, not exact URL
                    'api_key': SERPAPI_KEY,
                }
            else:
                # Regular Google for non-news paywalled sites
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
            engine_name = 'google_news' if is_news else 'google_search'
            log_api_call('serpapi', query=params['q'], function=f'url_metadata_{engine_name}')
            
            if response.status_code == 200:
                data = response.json()
                
                if self.debug:
                    print(f"[SmartURLRouter] SerpAPI response status: {response.status_code}")
                
                # Extract results based on engine type
                if is_news:
                    # Google News returns 'news_results'
                    results = data.get('news_results', [])
                    if self.debug:
                        print(f"[SmartURLRouter] Google News results count: {len(results)}")
                else:
                    # Regular Google returns 'organic_results'
                    results = data.get('organic_results', [])
                    if self.debug:
                        print(f"[SmartURLRouter] Google organic results count: {len(results)}")
                
                # If 0 results and we used regular Google, try keyword fallback
                if not results and not is_news:
                    if self.debug:
                        print(f"[SmartURLRouter] No results, trying keyword search...")
                    
                    keywords = self._extract_keywords_from_url(url)
                    
                    if keywords:
                        keyword_query = f"site:{domain} {keywords}"
                        
                        if self.debug:
                            print(f"[SmartURLRouter] Keyword query: {keyword_query}")
                        
                        params['q'] = keyword_query
                        response = requests.get(
                            'https://serpapi.com/search',
                            params=params,
                            timeout=10
                        )
                        
                        log_api_call('serpapi', query=keyword_query, function='url_metadata_keywords')
                        
                        if response.status_code == 200:
                            data = response.json()
                            results = data.get('organic_results', [])
                            
                            if self.debug:
                                print(f"[SmartURLRouter] Keyword search found {len(results)} results")
                
                if results:
                    result = results[0]
                    
                    # Extract metadata (works for both news_results and organic_results)
                    title = result.get('title')
                    snippet = result.get('snippet', '')
                    
                    # Google News might have different date field
                    date = result.get('date') or result.get('published_date') or result.get('timestamp')
                    
                    # Try to get source/publication from result
                    source_from_result = result.get('source') or result.get('source_name')
                    
                    authors = self._extract_authors_from_snippet(snippet)
                    publication = source_from_result or self._extract_publication_name(url)
                    
                    if self.debug:
                        print(f"[SmartURLRouter] Extracted title: {title}")
                        print(f"[SmartURLRouter] Extracted authors: {authors}")
                        print(f"[SmartURLRouter] Extracted date: {date}")
                        print(f"[SmartURLRouter] Extracted publication: {publication}")
                    
                    # Create metadata object
                    class Metadata:
                        def __init__(self):
                            self.title = title
                            self.authors = authors
                            self.authors_parsed = []  # Structured: [{"family": "Smith", "given": "John"}]
                            self.publication = publication
                            self.date = date
                            self.url = url
                            self.method_used = 'serpapi_news' if is_news else 'serpapi'
                        
                        def is_complete(self):
                            # Must have at least title to be useful
                            return bool(self.title)
                    
                    metadata = Metadata()
                    
                    # AI AUTHOR FALLBACK: If we got title but no authors, use AI
                    if metadata.title and not metadata.authors and AI_AUTHOR_FALLBACK:
                        if self.debug:
                            print(f"[SmartURLRouter] Title found but no authors - trying AI fallback...")
                        try:
                            ai_result = lookup_newspaper_url(url, verify=False)  # No verification needed, just author extraction
                            if ai_result and ai_result.authors:
                                metadata.authors = ai_result.authors
                                # Also copy structured authors if available
                                if hasattr(ai_result, 'authors_parsed') and ai_result.authors_parsed:
                                    metadata.authors_parsed = ai_result.authors_parsed
                                metadata.method_used += '+ai_author'
                                if self.debug:
                                    print(f"[SmartURLRouter] ✓ AI found authors: {metadata.authors}")
                                # Also grab date if AI found it and we didn't
                                if not metadata.date and ai_result.date:
                                    metadata.date = ai_result.date
                        except Exception as ai_err:
                            if self.debug:
                                print(f"[SmartURLRouter] AI author fallback failed: {ai_err}")
                    
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
    
    def _search_thenewsapi(self, url: str):
        """
        Search TheNewsAPI for article metadata.
        
        FREE tier: 100 requests/day
        Endpoint: https://api.thenewsapi.com/v1/news/all
        """
        if self.debug:
            print(f"[SmartURLRouter] Trying TheNewsAPI: {url[:60]}")
        
        try:
            # Extract domain for search
            domain = self._extract_domain(url)
            
            # TheNewsAPI search by URL or keywords
            params = {
                'api_token': THENEWSAPI_KEY,
                'search': url,  # Search for the URL
                'limit': 1,
            }
            
            response = requests.get(
                'https://api.thenewsapi.com/v1/news/all',
                params=params,
                timeout=10
            )
            
            # Log the call (free API, no cost)
            log_api_call('thenewsapi', query=url, function='url_metadata', cost=0.0)
            
            if response.status_code == 200:
                data = response.json()
                
                if self.debug:
                    print(f"[SmartURLRouter] TheNewsAPI status: {response.status_code}")
                
                # Check for results
                articles = data.get('data', [])
                if articles and len(articles) > 0:
                    article = articles[0]
                    
                    title = article.get('title', '')
                    snippet = article.get('snippet', '')
                    description = article.get('description', '')
                    
                    # Extract authors
                    authors = []
                    if article.get('author'):
                        authors = [article['author']]
                    
                    # Extract publication
                    publication = article.get('source', '')
                    
                    # Extract date
                    date = article.get('published_at', '')
                    if date:
                        # Format: "2024-12-21T10:30:00Z" -> "December 21, 2024"
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(date.replace('Z', '+00:00'))
                            date = dt.strftime('%B %d, %Y')
                        except:
                            pass
                    
                    if self.debug:
                        print(f"[SmartURLRouter] TheNewsAPI found: {title[:50] if title else 'N/A'}")
                        print(f"[SmartURLRouter] Authors: {authors}")
                        print(f"[SmartURLRouter] Publication: {publication}")
                    
                    # Create metadata object
                    class Metadata:
                        def __init__(self):
                            self.title = title
                            self.authors = authors
                            self.authors_parsed = []  # Structured: [{"family": "Smith", "given": "John"}]
                            self.publication = publication
                            self.date = date
                            self.url = url
                            self.method_used = 'thenewsapi'
                        
                        def is_complete(self):
                            return bool(self.title)
                    
                    metadata = Metadata()
                    
                    # AI AUTHOR FALLBACK: If we got title but no authors, use AI
                    if metadata.title and not metadata.authors and AI_AUTHOR_FALLBACK:
                        if self.debug:
                            print(f"[SmartURLRouter] TheNewsAPI: Title found but no authors - trying AI fallback...")
                        try:
                            ai_result = lookup_newspaper_url(url, verify=False)
                            if ai_result and ai_result.authors:
                                metadata.authors = ai_result.authors
                                # Also copy structured authors if available
                                if hasattr(ai_result, 'authors_parsed') and ai_result.authors_parsed:
                                    metadata.authors_parsed = ai_result.authors_parsed
                                metadata.method_used += '+ai_author'
                                if self.debug:
                                    print(f"[SmartURLRouter] ✓ AI found authors: {metadata.authors}")
                        except Exception as ai_err:
                            if self.debug:
                                print(f"[SmartURLRouter] AI author fallback failed: {ai_err}")
                    
                    return metadata
        
        except Exception as e:
            if self.debug:
                print(f"[SmartURLRouter] TheNewsAPI error: {e}")
        
        return self._empty_metadata(url)
    
    def _search_newsdata(self, url: str):
        """
        Search NewsData.io for article metadata.
        
        FREE tier: 200 requests/day
        Endpoint: https://newsdata.io/api/1/news
        """
        if self.debug:
            print(f"[SmartURLRouter] Trying NewsData: {url[:60]}")
        
        try:
            # NewsData search by URL pattern
            params = {
                'apikey': NEWSDATA_KEY,
                'qInUrl': url,  # Search URLs containing this pattern
            }
            
            response = requests.get(
                'https://newsdata.io/api/1/news',
                params=params,
                timeout=10
            )
            
            # Log the call (free API, no cost)
            log_api_call('newsdata', query=url, function='url_metadata', cost=0.0)
            
            if response.status_code == 200:
                data = response.json()
                
                if self.debug:
                    print(f"[SmartURLRouter] NewsData status: {response.status_code}")
                
                # Check for results
                results = data.get('results', [])
                if results and len(results) > 0:
                    article = results[0]
                    
                    title = article.get('title', '')
                    description = article.get('description', '')
                    
                    # Extract authors
                    authors = []
                    creators = article.get('creator', [])
                    if creators:
                        authors = creators if isinstance(creators, list) else [creators]
                    
                    # Extract publication
                    publication = article.get('source_id', '')
                    
                    # Extract date
                    date = article.get('pubDate', '')
                    if date:
                        # Format: "2024-12-21 10:30:00" -> "December 21, 2024"
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(date.replace(' ', 'T'))
                            date = dt.strftime('%B %d, %Y')
                        except:
                            pass
                    
                    if self.debug:
                        print(f"[SmartURLRouter] NewsData found: {title[:50] if title else 'N/A'}")
                        print(f"[SmartURLRouter] Authors: {authors}")
                        print(f"[SmartURLRouter] Publication: {publication}")
                    
                    # Create metadata object
                    class Metadata:
                        def __init__(self):
                            self.title = title
                            self.authors = authors
                            self.authors_parsed = []  # Structured: [{"family": "Smith", "given": "John"}]
                            self.publication = publication
                            self.date = date
                            self.url = url
                            self.method_used = 'newsdata'
                        
                        def is_complete(self):
                            return bool(self.title)
                    
                    metadata = Metadata()
                    
                    # AI AUTHOR FALLBACK: If we got title but no authors, use AI
                    if metadata.title and not metadata.authors and AI_AUTHOR_FALLBACK:
                        if self.debug:
                            print(f"[SmartURLRouter] NewsData: Title found but no authors - trying AI fallback...")
                        try:
                            ai_result = lookup_newspaper_url(url, verify=False)
                            if ai_result and ai_result.authors:
                                metadata.authors = ai_result.authors
                                # Also copy structured authors if available
                                if hasattr(ai_result, 'authors_parsed') and ai_result.authors_parsed:
                                    metadata.authors_parsed = ai_result.authors_parsed
                                metadata.method_used += '+ai_author'
                                if self.debug:
                                    print(f"[SmartURLRouter] ✓ AI found authors: {metadata.authors}")
                        except Exception as ai_err:
                            if self.debug:
                                print(f"[SmartURLRouter] AI author fallback failed: {ai_err}")
                    
                    return metadata
        
        except Exception as e:
            if self.debug:
                print(f"[SmartURLRouter] NewsData error: {e}")
        
        return self._empty_metadata(url)
    
    def _empty_metadata(self, url: str):
        """Return empty metadata to trigger GenericURL fallback."""
        class EmptyMetadata:
            def __init__(self):
                self.title = None
                self.authors = []
                self.authors_parsed = []
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
    
    def _is_news_domain(self, domain: str) -> bool:
        """
        Check if domain is a newspaper or magazine.
        
        Returns True for news sites where Google News API works better.
        """
        news_domains = {
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
            'cnn.com',
            'bbc.com',
            'theguardian.com',
            'usatoday.com',
            'latimes.com',
            'chicagotribune.com',
            'bostonglobe.com',
        }
        
        return domain in news_domains
    
    def _extract_keywords_from_url(self, url: str) -> str:
        """
        Extract searchable keywords from URL path.
        
        Example:
        https://www.washingtonpost.com/style/media/2024/08/02/atlantic-writers-protest-ai/
        → "atlantic writers protest ai"
        """
        import re
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        path = parsed.path
        
        # Remove leading/trailing slashes
        path = path.strip('/')
        
        # Split on slashes and hyphens
        parts = re.split(r'[/\-_]', path)
        
        # Filter out:
        # - Date-like patterns (2024, 08, 02)
        # - Short parts (< 3 chars)
        # - Common URL segments
        skip_words = {'style', 'media', 'article', 'post', 'blog', 'news', 'story'}
        
        keywords = []
        for part in parts:
            # Skip dates
            if re.match(r'^\d+$', part):
                continue
            # Skip short parts
            if len(part) < 3:
                continue
            # Skip common URL words
            if part.lower() in skip_words:
                continue
            
            keywords.append(part)
        
        # Join with spaces
        keyword_string = ' '.join(keywords)
        
        return keyword_string
    
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
