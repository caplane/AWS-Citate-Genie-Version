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

# Institutional author mapping: domain → official author name
# These are organizations where the institution IS the author (not individual writers)
INSTITUTIONAL_AUTHORS = {
    # US Government - Health
    'cdc.gov': 'Centers for Disease Control and Prevention',
    'nih.gov': 'National Institutes of Health',
    'fda.gov': 'U.S. Food and Drug Administration',
    'hhs.gov': 'U.S. Department of Health and Human Services',
    'cms.gov': 'Centers for Medicare & Medicaid Services',
    'samhsa.gov': 'Substance Abuse and Mental Health Services Administration',
    
    # US Government - Other
    'whitehouse.gov': 'The White House',
    'state.gov': 'U.S. Department of State',
    'justice.gov': 'U.S. Department of Justice',
    'treasury.gov': 'U.S. Department of the Treasury',
    'ed.gov': 'U.S. Department of Education',
    'dol.gov': 'U.S. Department of Labor',
    'epa.gov': 'U.S. Environmental Protection Agency',
    'energy.gov': 'U.S. Department of Energy',
    'defense.gov': 'U.S. Department of Defense',
    'dhs.gov': 'U.S. Department of Homeland Security',
    'usda.gov': 'U.S. Department of Agriculture',
    'doi.gov': 'U.S. Department of the Interior',
    'commerce.gov': 'U.S. Department of Commerce',
    'va.gov': 'U.S. Department of Veterans Affairs',
    'hud.gov': 'U.S. Department of Housing and Urban Development',
    'dot.gov': 'U.S. Department of Transportation',
    'gao.gov': 'U.S. Government Accountability Office',
    'cbo.gov': 'Congressional Budget Office',
    'bls.gov': 'Bureau of Labor Statistics',
    'census.gov': 'U.S. Census Bureau',
    'ssa.gov': 'Social Security Administration',
    'irs.gov': 'Internal Revenue Service',
    'fbi.gov': 'Federal Bureau of Investigation',
    'cia.gov': 'Central Intelligence Agency',
    'nasa.gov': 'National Aeronautics and Space Administration',
    'nsf.gov': 'National Science Foundation',
    'nist.gov': 'National Institute of Standards and Technology',
    'noaa.gov': 'National Oceanic and Atmospheric Administration',
    'usgs.gov': 'U.S. Geological Survey',
    'fcc.gov': 'Federal Communications Commission',
    'ftc.gov': 'Federal Trade Commission',
    'sec.gov': 'U.S. Securities and Exchange Commission',
    'supremecourt.gov': 'Supreme Court of the United States',
    'uscourts.gov': 'United States Courts',
    'congress.gov': 'U.S. Congress',
    
    # International Organizations
    'who.int': 'World Health Organization',
    'un.org': 'United Nations',
    'worldbank.org': 'World Bank',
    'imf.org': 'International Monetary Fund',
    'wto.org': 'World Trade Organization',
    'oecd.org': 'Organisation for Economic Co-operation and Development',
    'nato.int': 'North Atlantic Treaty Organization',
    'europa.eu': 'European Union',
    'ecb.europa.eu': 'European Central Bank',
    
    # UK Government
    'gov.uk': 'UK Government',
    'nhs.uk': 'National Health Service',
    'bankofengland.co.uk': 'Bank of England',
    
    # Other Major Institutions
    'federalreserve.gov': 'Board of Governors of the Federal Reserve System',
    'archives.gov': 'National Archives and Records Administration',
    'loc.gov': 'Library of Congress',
    'smithsonian.edu': 'Smithsonian Institution',
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
        
        # FIRST: Check for institutional authors (government, organizations)
        # These domains have known institutional authors - no need to search
        institutional_author = self._get_institutional_author(domain)
        if institutional_author:
            if self.debug:
                print(f"[SmartURLRouter] Institutional author detected: {institutional_author}")
            return self._institutional_metadata(url, institutional_author)
        
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
        1. For newspapers/magazines: Use Google News API (returns structured author data!)
           - SerpAPI Google News returns: source.authors = ["John Smith", "Jane Doe"]
           - This gives us reliable author names for NYT, WSJ, WaPo, Guardian, etc.
        2. For other paywalled sites: Use regular Google Search
        3. If 0 results: Try keyword search fallback
        4. If still no authors: AI fallback (if enabled)
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
                    
                    # Extract source info - Google News returns source as dict with name and authors
                    # Example: {"name": "CNN", "authors": ["John Smith", "Jane Doe"]}
                    source_data = result.get('source', {})
                    authors = []
                    authors_parsed = []
                    
                    if isinstance(source_data, dict):
                        # Google News format: source.authors is an array of author names
                        source_authors = source_data.get('authors', [])
                        if source_authors and isinstance(source_authors, list):
                            authors = source_authors
                            # Parse author names into structured format
                            for author_name in source_authors:
                                if author_name and isinstance(author_name, str):
                                    parts = author_name.strip().split()
                                    if len(parts) >= 2:
                                        authors_parsed.append({
                                            'given': ' '.join(parts[:-1]),
                                            'family': parts[-1]
                                        })
                                    elif len(parts) == 1:
                                        authors_parsed.append({'family': parts[0], 'given': ''})
                        
                        publication = source_data.get('name') or self._extract_publication_name(url)
                    else:
                        # Fallback for non-dict source (regular Google search)
                        publication = source_data or self._extract_publication_name(url)
                    
                    # Fallback to snippet parsing if no authors from source
                    if not authors:
                        authors = self._extract_authors_from_snippet(snippet)
                    
                    if self.debug:
                        print(f"[SmartURLRouter] Extracted title: {title}")
                        print(f"[SmartURLRouter] Extracted authors: {authors}")
                        print(f"[SmartURLRouter] Extracted authors_parsed: {authors_parsed}")
                        print(f"[SmartURLRouter] Extracted date: {date}")
                        print(f"[SmartURLRouter] Extracted publication: {publication}")
                    
                    # Create metadata object with the authors_parsed from Google News
                    class Metadata:
                        def __init__(self):
                            self.title = title
                            self.authors = authors
                            self.authors_parsed = authors_parsed  # From source.authors parsing
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
                        print(f"[SmartURLRouter] Title found but no authors - trying AI fallback for: {url[:60]}...")
                        try:
                            ai_result = lookup_newspaper_url(url, verify=False)  # No verification needed, just author extraction
                            if ai_result and ai_result.authors:
                                metadata.authors = ai_result.authors
                                # Also copy structured authors if available
                                if hasattr(ai_result, 'authors_parsed') and ai_result.authors_parsed:
                                    metadata.authors_parsed = ai_result.authors_parsed
                                metadata.method_used += '+ai_author'
                                print(f"[SmartURLRouter] ✓ AI found authors: {metadata.authors}")
                                # Also grab date if AI found it and we didn't
                                if not metadata.date and ai_result.date:
                                    metadata.date = ai_result.date
                            else:
                                print(f"[SmartURLRouter] ✗ AI returned no authors for: {url[:60]}")
                        except Exception as ai_err:
                            print(f"[SmartURLRouter] ✗ AI author fallback FAILED: {ai_err}")
                    
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
                        print(f"[SmartURLRouter] TheNewsAPI: Title found but no authors - trying AI fallback...")
                        try:
                            ai_result = lookup_newspaper_url(url, verify=False)
                            if ai_result and ai_result.authors:
                                metadata.authors = ai_result.authors
                                # Also copy structured authors if available
                                if hasattr(ai_result, 'authors_parsed') and ai_result.authors_parsed:
                                    metadata.authors_parsed = ai_result.authors_parsed
                                metadata.method_used += '+ai_author'
                                print(f"[SmartURLRouter] ✓ AI found authors: {metadata.authors}")
                            else:
                                print(f"[SmartURLRouter] ✗ TheNewsAPI AI returned no authors")
                        except Exception as ai_err:
                            print(f"[SmartURLRouter] ✗ TheNewsAPI AI fallback FAILED: {ai_err}")
                    
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
                        print(f"[SmartURLRouter] NewsData: Title found but no authors - trying AI fallback...")
                        try:
                            ai_result = lookup_newspaper_url(url, verify=False)
                            if ai_result and ai_result.authors:
                                metadata.authors = ai_result.authors
                                # Also copy structured authors if available
                                if hasattr(ai_result, 'authors_parsed') and ai_result.authors_parsed:
                                    metadata.authors_parsed = ai_result.authors_parsed
                                metadata.method_used += '+ai_author'
                                print(f"[SmartURLRouter] ✓ AI found authors: {metadata.authors}")
                            else:
                                print(f"[SmartURLRouter] ✗ NewsData AI returned no authors")
                        except Exception as ai_err:
                            print(f"[SmartURLRouter] ✗ NewsData AI fallback FAILED: {ai_err}")
                    
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
    
    def _get_institutional_author(self, domain: str) -> str:
        """
        Check if domain belongs to an institution that should be the author.
        
        Returns institutional author name if found, None otherwise.
        """
        # Direct match
        if domain in INSTITUTIONAL_AUTHORS:
            return INSTITUTIONAL_AUTHORS[domain]
        
        # Check for subdomains (e.g., 'ncbi.nlm.nih.gov' should match 'nih.gov')
        parts = domain.split('.')
        for i in range(len(parts) - 1):
            parent_domain = '.'.join(parts[i:])
            if parent_domain in INSTITUTIONAL_AUTHORS:
                return INSTITUTIONAL_AUTHORS[parent_domain]
        
        return None
    
    def _institutional_metadata(self, url: str, author: str):
        """
        Return metadata for institutional URLs with the institution as author.
        
        These URLs need title extraction but we already know the author.
        """
        class InstitutionalMetadata:
            def __init__(self, url, author):
                self.title = None  # Will be filled by GenericURL or AI
                self.authors = [author]
                self.authors_parsed = [{'family': author, 'given': '', 'is_institutional': True}]
                self.publication = None
                self.date = None
                self.url = url
                self.method_used = 'institutional_author'
                self.institutional_author = author  # Flag for formatters
            
            def is_complete(self):
                # Return False so title can still be extracted
                # But authors are already set correctly
                return False
        
        return InstitutionalMetadata(url, author)
    
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
        
        # Remove leading/trailing slashes and file extensions
        path = path.strip('/')
        path = re.sub(r'\.(html?|php|aspx?)$', '', path, flags=re.IGNORECASE)
        
        # Split on slashes and hyphens
        parts = re.split(r'[/\-_]', path)
        
        # Filter out:
        # - Date-like patterns (2024, 08, 02)
        # - Short parts (< 3 chars)
        # - Common URL segments
        # - Hash codes (alphanumeric strings that look like IDs)
        skip_words = {'style', 'media', 'article', 'post', 'blog', 'news', 'story', 
                      'opinion', 'world', 'politics', 'books', 'us', 'uk', 'dec', 'jan',
                      'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov'}
        
        keywords = []
        for part in parts:
            # Skip dates (pure numbers)
            if re.match(r'^\d+$', part):
                continue
            # Skip short parts
            if len(part) < 3:
                continue
            # Skip common URL words
            if part.lower() in skip_words:
                continue
            # Skip hash codes (8+ char alphanumeric that aren't real words)
            if re.match(r'^[a-f0-9]{8,}$', part.lower()):
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
