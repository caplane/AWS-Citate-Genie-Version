"""
Waterfall News Metadata Resolver
Cost-optimized news URL resolution with free sources first

WATERFALL STRATEGY:
1. Google News RSS (FREE, unlimited)
2. The News API (FREE, 100/day limit)
3. NewsData.io (FREE, 200/day limit)
4. Direct HTML scraping (FREE)
5. SerpAPI (PAID, $0.01/call) - LAST RESORT

Expected cost reduction: 90%+ 
(Most queries resolved by free tier, SerpAPI only for edge cases)
"""

import requests
import feedparser
import re
from typing import Optional, Dict
from urllib.parse import urlparse, quote_plus
from datetime import datetime

from config import SERPAPI_KEY, THENEWSAPI_KEY, NEWSDATA_KEY
from cost_tracker import log_api_call


class WaterfallNewsResolver:
    """
    Cost-optimized news metadata resolver.
    
    Tries free sources first, falls back to paid only when necessary.
    """
    
    def __init__(self, debug=False):
        self.debug = debug
        
        # Track daily usage for rate-limited free APIs
        self.thenewsapi_calls_today = 0
        self.newsdata_calls_today = 0
        self.last_reset = datetime.now().date()
        
        # Check which APIs are available
        self.has_serpapi = bool(SERPAPI_KEY)
        self.has_thenewsapi = bool(THENEWSAPI_KEY) if 'THENEWSAPI_KEY' in dir() else False
        self.has_newsdata = bool(NEWSDATA_KEY) if 'NEWSDATA_KEY' in dir() else False
        
        if self.debug:
            print(f"[WaterfallNews] Available APIs:")
            print(f"  - Google News RSS: Always available (FREE)")
            print(f"  - The News API: {self.has_thenewsapi} (FREE 100/day)")
            print(f"  - NewsData.io: {self.has_newsdata} (FREE 200/day)")
            print(f"  - SerpAPI: {self.has_serpapi} (PAID $0.01/call)")
    
    def resolve(self, url: str):
        """
        Resolve news URL metadata using waterfall strategy.
        
        Returns metadata object compatible with SmartURLRouter.
        """
        # Reset daily counters if new day
        self._check_daily_reset()
        
        if self.debug:
            print(f"[WaterfallNews] Resolving: {url[:60]}...")
        
        # Extract search parameters from URL
        domain = self._extract_domain(url)
        keywords = self._extract_keywords_from_url(url)
        
        if not keywords:
            if self.debug:
                print(f"[WaterfallNews] No keywords extracted, will use direct HTML scraping")
            return self._empty_metadata(url)
        
        # TIER 1: Google News RSS (FREE, unlimited, ALWAYS TRY FIRST)
        result = self._try_google_news_rss(url, domain, keywords)
        if result and result.is_complete():
            return result
        
        # TIER 2: The News API (FREE, 100/day limit)
        if self.has_thenewsapi and self.thenewsapi_calls_today < 100:
            result = self._try_thenewsapi(url, keywords)
            if result and result.is_complete():
                return result
        
        # TIER 3: NewsData.io (FREE, 200/day limit)
        if self.has_newsdata and self.newsdata_calls_today < 200:
            result = self._try_newsdata(url, keywords)
            if result and result.is_complete():
                return result
        
        # TIER 4: Direct HTML scraping (FREE, but often fails for paywalls)
        # Skip this - it's already handled by GenericURLEngine in the wrapper
        
        # TIER 5: SerpAPI (PAID, last resort)
        if self.has_serpapi:
            if self.debug:
                print(f"[WaterfallNews] All free sources exhausted, falling back to SerpAPI")
            result = self._try_serpapi(url, domain, keywords)
            if result and result.is_complete():
                return result
        
        # All methods failed
        if self.debug:
            print(f"[WaterfallNews] All resolution methods failed")
        return self._empty_metadata(url)
    
    def _try_google_news_rss(self, url: str, domain: str, keywords: str):
        """
        Try Google News RSS feed (FREE, unlimited).
        
        Strategy: Search Google News for site-specific keywords.
        Example: site:washingtonpost.com economy great year election
        """
        if self.debug:
            print(f"[WaterfallNews] Trying Google News RSS (FREE)...")
        
        try:
            # Build Google News RSS search URL
            search_query = f"site:{domain} {keywords}"
            rss_url = f"https://news.google.com/rss/search?q={quote_plus(search_query)}&hl=en-US&gl=US&ceid=US:en"
            
            if self.debug:
                print(f"[WaterfallNews] RSS query: {search_query}")
            
            # Fetch RSS feed
            response = requests.get(rss_url, timeout=10)
            
            # Log as free (no cost)
            log_api_call('google_news_rss', query=search_query, function='news_metadata', cost=0.0)
            
            if response.status_code == 200:
                # Parse RSS feed
                feed = feedparser.parse(response.content)
                
                if self.debug:
                    print(f"[WaterfallNews] RSS returned {len(feed.entries)} entries")
                
                if feed.entries:
                    entry = feed.entries[0]
                    
                    # Extract metadata from RSS entry
                    title = entry.get('title', '')
                    
                    # Get source/publication
                    # RSS format: "Title - Source Name"
                    source = None
                    if hasattr(entry, 'source') and hasattr(entry.source, 'title'):
                        source = entry.source.title
                    elif ' - ' in title:
                        # Sometimes source is in title
                        parts = title.rsplit(' - ', 1)
                        if len(parts) == 2:
                            title = parts[0]
                            source = parts[1]
                    
                    if not source:
                        source = self._extract_publication_name(url)
                    
                    # Get date
                    date = entry.get('published', '')
                    
                    # Get description/snippet for author extraction
                    snippet = entry.get('summary', '') or entry.get('description', '')
                    authors = self._extract_authors_from_snippet(snippet)
                    
                    if self.debug:
                        print(f"[WaterfallNews] ✓ Google RSS found: {title[:50]}")
                        print(f"[WaterfallNews]   Source: {source}")
                        print(f"[WaterfallNews]   Authors: {authors}")
                        print(f"[WaterfallNews]   Date: {date}")
                    
                    # Create metadata object
                    class Metadata:
                        def __init__(self):
                            self.title = title
                            self.authors = authors
                            self.publication = source
                            self.date = date
                            self.url = url
                            self.method_used = 'google_news_rss'
                        
                        def is_complete(self):
                            return bool(self.title)
                    
                    return Metadata()
        
        except Exception as e:
            if self.debug:
                print(f"[WaterfallNews] Google RSS error: {e}")
        
        return None
    
    def _try_thenewsapi(self, url: str, keywords: str):
        """
        Try The News API (FREE, 100 calls/day).
        
        Requires API key: https://www.thenewsapi.com/
        """
        if self.debug:
            print(f"[WaterfallNews] Trying The News API (FREE 100/day, used: {self.thenewsapi_calls_today})...")
        
        try:
            # The News API search endpoint
            api_url = "https://api.thenewsapi.com/v1/news/all"
            
            params = {
                'api_token': THENEWSAPI_KEY,
                'search': keywords,
                'language': 'en',
                'limit': 1
            }
            
            response = requests.get(api_url, params=params, timeout=10)
            self.thenewsapi_calls_today += 1
            
            # Log as free (within free tier)
            log_api_call('thenewsapi', query=keywords, function='news_metadata', cost=0.0)
            
            if response.status_code == 200:
                data = response.json()
                articles = data.get('data', [])
                
                if self.debug:
                    print(f"[WaterfallNews] The News API returned {len(articles)} articles")
                
                if articles:
                    article = articles[0]
                    
                    title = article.get('title', '')
                    source = article.get('source', '')
                    date = article.get('published_at', '')
                    snippet = article.get('description', '')
                    authors = self._extract_authors_from_snippet(snippet)
                    
                    if self.debug:
                        print(f"[WaterfallNews] ✓ The News API found: {title[:50]}")
                    
                    class Metadata:
                        def __init__(self):
                            self.title = title
                            self.authors = authors
                            self.publication = source
                            self.date = date
                            self.url = url
                            self.method_used = 'thenewsapi'
                        
                        def is_complete(self):
                            return bool(self.title)
                    
                    return Metadata()
        
        except Exception as e:
            if self.debug:
                print(f"[WaterfallNews] The News API error: {e}")
        
        return None
    
    def _try_newsdata(self, url: str, keywords: str):
        """
        Try NewsData.io (FREE, 200 calls/day).
        
        Requires API key: https://newsdata.io/
        """
        if self.debug:
            print(f"[WaterfallNews] Trying NewsData.io (FREE 200/day, used: {self.newsdata_calls_today})...")
        
        try:
            # NewsData.io search endpoint
            api_url = "https://newsdata.io/api/1/news"
            
            params = {
                'apikey': NEWSDATA_KEY,
                'q': keywords,
                'language': 'en',
                'size': 1
            }
            
            response = requests.get(api_url, params=params, timeout=10)
            self.newsdata_calls_today += 1
            
            # Log as free (within free tier)
            log_api_call('newsdata', query=keywords, function='news_metadata', cost=0.0)
            
            if response.status_code == 200:
                data = response.json()
                articles = data.get('results', [])
                
                if self.debug:
                    print(f"[WaterfallNews] NewsData.io returned {len(articles)} articles")
                
                if articles:
                    article = articles[0]
                    
                    title = article.get('title', '')
                    source = article.get('source_id', '')
                    date = article.get('pubDate', '')
                    snippet = article.get('description', '')
                    authors = article.get('creator', []) or self._extract_authors_from_snippet(snippet)
                    
                    if self.debug:
                        print(f"[WaterfallNews] ✓ NewsData.io found: {title[:50]}")
                    
                    class Metadata:
                        def __init__(self):
                            self.title = title
                            self.authors = authors if isinstance(authors, list) else [authors]
                            self.publication = source
                            self.date = date
                            self.url = url
                            self.method_used = 'newsdata'
                        
                        def is_complete(self):
                            return bool(self.title)
                    
                    return Metadata()
        
        except Exception as e:
            if self.debug:
                print(f"[WaterfallNews] NewsData.io error: {e}")
        
        return None
    
    def _try_serpapi(self, url: str, domain: str, keywords: str):
        """
        Try SerpAPI Google News (PAID, $0.01/call).
        
        Only called as last resort when all free sources fail.
        """
        if self.debug:
            print(f"[WaterfallNews] Trying SerpAPI Google News (PAID $0.01)...")
        
        try:
            # Use Google News engine (better for news than regular Google)
            params = {
                'engine': 'google_news',
                'q': keywords,
                'api_key': SERPAPI_KEY,
            }
            
            response = requests.get(
                'https://serpapi.com/search',
                params=params,
                timeout=10
            )
            
            # Log cost ($0.01)
            log_api_call('serpapi', query=keywords, function='news_metadata_paid')
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('news_results', [])
                
                if self.debug:
                    print(f"[WaterfallNews] SerpAPI returned {len(results)} results")
                
                if results:
                    result = results[0]
                    
                    title = result.get('title', '')
                    source = result.get('source', '') or self._extract_publication_name(url)
                    date = result.get('date', '') or result.get('published_date', '')
                    snippet = result.get('snippet', '')
                    authors = self._extract_authors_from_snippet(snippet)
                    
                    if self.debug:
                        print(f"[WaterfallNews] ✓ SerpAPI found: {title[:50]}")
                    
                    class Metadata:
                        def __init__(self):
                            self.title = title
                            self.authors = authors
                            self.publication = source
                            self.date = date
                            self.url = url
                            self.method_used = 'serpapi_news'
                        
                        def is_complete(self):
                            return bool(self.title)
                    
                    return Metadata()
        
        except Exception as e:
            if self.debug:
                print(f"[WaterfallNews] SerpAPI error: {e}")
        
        return None
    
    def _extract_domain(self, url: str) -> str:
        """Extract clean domain from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    
    def _extract_keywords_from_url(self, url: str) -> str:
        """
        Extract searchable keywords from URL path.
        
        Example:
        https://www.washingtonpost.com/opinions/2024/10/10/economy-great-year-election/
        → "economy great year election"
        """
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        # Split on slashes and hyphens
        parts = re.split(r'[/\-_]', path)
        
        # Filter out dates, short parts, and common URL segments
        skip_words = {'style', 'media', 'article', 'post', 'blog', 'news', 'story', 
                      'opinions', 'editorial', 'commentary'}
        
        keywords = []
        for part in parts:
            # Skip dates (YYYY, MM, DD patterns)
            if re.match(r'^\d+$', part):
                continue
            # Skip short parts
            if len(part) < 3:
                continue
            # Skip common URL words
            if part.lower() in skip_words:
                continue
            
            keywords.append(part)
        
        return ' '.join(keywords)
    
    def _extract_publication_name(self, url: str) -> str:
        """Map domain to publication name."""
        domain = self._extract_domain(url)
        
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
            'axios.com': 'Axios',
            'npr.org': 'NPR',
            'politico.com': 'Politico',
            'reuters.com': 'Reuters',
        }
        
        return publication_map.get(domain, domain.replace('.com', '').title())
    
    def _extract_authors_from_snippet(self, snippet: str) -> list:
        """Extract author from snippet if present."""
        if not snippet:
            return []
        
        # Pattern: "By Author Name" or "Author Name writes"
        match = re.search(r'[Bb]y\s+([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?[A-Z][a-z]+)', snippet)
        if match:
            return [match.group(1)]
        
        return []
    
    def _empty_metadata(self, url: str):
        """Return empty metadata to trigger fallback."""
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
    
    def _check_daily_reset(self):
        """Reset daily API call counters at midnight."""
        today = datetime.now().date()
        if today != self.last_reset:
            if self.debug:
                print(f"[WaterfallNews] Daily reset: The News API and NewsData.io counters reset to 0")
            self.thenewsapi_calls_today = 0
            self.newsdata_calls_today = 0
            self.last_reset = today
    
    def get_stats(self):
        """Get usage statistics."""
        return {
            'thenewsapi_used_today': self.thenewsapi_calls_today,
            'newsdata_used_today': self.newsdata_calls_today,
            'thenewsapi_remaining': 100 - self.thenewsapi_calls_today,
            'newsdata_remaining': 200 - self.newsdata_calls_today,
        }
