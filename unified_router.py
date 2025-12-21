"""
unified_router_institutional_authors_patch.py

Patch for unified_router.py to detect and properly format institutional authors.

CRITICAL RULES:
1. In-text (author-date parenthetical): Use ACRONYM - (CDC, 2024)
2. Footnotes/Endnotes/Reference Lists: Use FULL NAME - Centers for Disease Control...
3. Never show acronyms in footnotes, endnotes, or reference lists

HOW TO APPLY:
Add these imports and update the _route_url function in unified_router.py
"""

# =============================================================================
# ADD TO TOP OF unified_router.py (after other imports)
# =============================================================================

from institutional_authors import (
    get_institutional_author_from_url,
    is_institutional_domain,
    extract_domain_from_url
)


# =============================================================================
# UPDATE THE _route_url FUNCTION
# =============================================================================

def _route_url(url: str) -> Optional[SourceComponents]:
    """
    Route URL to appropriate handler and return metadata.
    
    UPDATED: Now detects institutional authors and adds both full name and acronym.
    """
    try:
        # Check for institutional author FIRST
        institutional_info = get_institutional_author_from_url(url)
        
        # ... existing code for routing (DOI, smart router, generic, etc.) ...
        
        # After getting metadata from any source, check if we need to add institutional author
        if metadata and institutional_info:
            # This is an institutional source
            # Make sure the institutional author is set properly
            
            # If metadata has no authors, or authors don't include the institution, add it
            if not metadata.authors or institutional_info['full_name'] not in metadata.authors:
                # Prepend institutional author
                existing_authors = metadata.authors if metadata.authors else []
                metadata.authors = [institutional_info['full_name']] + existing_authors
            
            # Store institutional info in metadata for formatters
            # Formatters can use this to decide acronym vs full name
            if not hasattr(metadata, 'institutional_author'):
                metadata.institutional_author = institutional_info
        
        return metadata
        
    except Exception as e:
        print(f"[UnifiedRouter] Error in _route_url: {e}")
        return None


# =============================================================================
# EXAMPLE: Updated SmartURLWrapper in unified_router.py
# =============================================================================

"""
In unified_router.py, in the SmartURLWrapper class:

class _SmartURLWrapper:
    def fetch_by_url(self, url):
        try:
            # Check for institutional author
            institutional_info = get_institutional_author_from_url(url)
            
            # Try smart router
            metadata = self.smart_router.resolve(url)
            
            if metadata.is_complete():
                # Build SourceComponents
                components = SourceComponents(
                    title=metadata.title,
                    authors=metadata.authors,
                    newspaper=metadata.publication,
                    date=metadata.date,
                    url=url,
                    citation_type=CitationType.URL
                )
                
                # Add institutional author info if detected
                if institutional_info:
                    # Ensure institutional author is in the authors list
                    if not components.authors or institutional_info['full_name'] not in components.authors:
                        existing = components.authors if components.authors else []
                        components.authors = [institutional_info['full_name']] + existing
                    
                    # Store institutional info for formatters
                    components.institutional_author = institutional_info
                
                return components
            else:
                return self.fallback.fetch_by_url(url)
                
        except Exception as e:
            print(f"[SmartRouter] Error: {e}")
            return self.fallback.fetch_by_url(url)
"""


# =============================================================================
# UPDATE models.py - Add institutional_author field
# =============================================================================

"""
In models.py, in the SourceComponents class, add:

class SourceComponents:
    # ... existing fields ...
    
    # Institutional author info (for organizations like CDC, WHO, EPA)
    institutional_author: Optional[Dict[str, str]] = None
    # Contains: {'full_name': 'Centers for Disease Control...', 'acronym': 'CDC', 'type': 'government'}
    
    def get_author_for_parenthetical(self) -> str:
        '''
        Get author name for in-text parenthetical citations.
        
        For institutional authors: Returns ACRONYM
        For regular authors: Returns first author last name
        
        Example:
            >>> components.institutional_author = {'acronym': 'CDC', ...}
            >>> components.get_author_for_parenthetical()
            'CDC'
            
            >>> components.authors = ['Smith, John']
            >>> components.get_author_for_parenthetical()
            'Smith'
        '''
        if self.institutional_author:
            return self.institutional_author['acronym']
        
        if self.authors and len(self.authors) > 0:
            # Extract last name from first author
            first_author = self.authors[0]
            if ',' in first_author:
                return first_author.split(',')[0].strip()
            else:
                # Handle "John Smith" format
                parts = first_author.split()
                return parts[-1] if parts else first_author
        
        return ''
    
    def get_author_for_reference(self) -> str:
        '''
        Get author name for reference lists, footnotes, endnotes.
        
        For institutional authors: Returns FULL NAME (never acronym!)
        For regular authors: Returns formatted author names
        
        Example:
            >>> components.institutional_author = {'full_name': 'Centers for Disease Control...', ...}
            >>> components.get_author_for_reference()
            'Centers for Disease Control and Prevention'
            
            >>> components.authors = ['Smith, John', 'Doe, Jane']
            >>> components.get_author_for_reference()
            'Smith, John and Jane Doe'
        '''
        if self.institutional_author:
            return self.institutional_author['full_name']
        
        if self.authors:
            return self._format_authors_for_reference()
        
        return ''
    
    def _format_authors_for_reference(self) -> str:
        '''Format author list for reference entries.'''
        if not self.authors:
            return ''
        
        # This would use your existing author formatting logic
        # Just a simple example:
        if len(self.authors) == 1:
            return self.authors[0]
        elif len(self.authors) == 2:
            return f"{self.authors[0]} and {self.authors[1]}"
        else:
            return f"{self.authors[0]} et al."
"""


# =============================================================================
# UPDATE FORMATTERS - Use institutional author info
# =============================================================================

"""
In your citation formatters (apa_formatter.py, chicago_formatter.py, etc.):

def format_author_date_parenthetical(components: SourceComponents, year: str) -> str:
    '''
    Format in-text parenthetical citation.
    
    CRITICAL: Use ACRONYM for institutional authors!
    '''
    author = components.get_author_for_parenthetical()  # Returns acronym for institutions
    return f"({author}, {year})"


def format_reference_entry(components: SourceComponents) -> str:
    '''
    Format reference list entry.
    
    CRITICAL: Use FULL NAME for institutional authors!
    '''
    author = components.get_author_for_reference()  # Returns full name for institutions
    
    # APA example:
    # Centers for Disease Control and Prevention. (2024). Title. URL
    
    # Chicago example:
    # Centers for Disease Control and Prevention. "Title." 2024. URL
    
    return f"{author}. ({components.year}). {components.title}..."
"""


# =============================================================================
# TESTING
# =============================================================================

"""
Test the institutional author detection:

from unified_router import route_citation
from institutional_authors import get_institutional_author_from_url

# Test CDC URL
url = "https://www.cdc.gov/covid/reports/2024.html"
components, formatted = route_citation(url, style="apa")

print(f"URL: {url}")
print(f"Authors: {components.authors}")
# Should print: ['Centers for Disease Control and Prevention']

print(f"Institutional: {components.institutional_author}")
# Should print: {'full_name': 'Centers for Disease Control...', 'acronym': 'CDC', ...}

print(f"Parenthetical: {components.get_author_for_parenthetical()}")
# Should print: CDC

print(f"Reference: {components.get_author_for_reference()}")
# Should print: Centers for Disease Control and Prevention


# Test WHO URL
url = "https://who.int/health-topics/covid-19"
components, formatted = route_citation(url, style="apa")

print(f"Parenthetical: (WHO, 2024)")  # Acronym
print(f"Reference: World Health Organization. (2024)...")  # Full name
"""


# =============================================================================
# DEPLOYMENT CHECKLIST
# =============================================================================

"""
1. Add institutional_authors.py to project root
2. Update models.py with institutional_author field and helper methods
3. Update unified_router.py with institutional detection in _route_url
4. Update formatters to use get_author_for_parenthetical() and get_author_for_reference()
5. Test with CDC, WHO, EPA URLs
6. Verify:
   - In-text: (CDC, 2024) ✓
   - Reference: Centers for Disease Control and Prevention. (2024)... ✓
   - Never: (Centers for Disease Control..., 2024) ✗
   - Never: CDC. (2024)... in reference list ✗
"""
