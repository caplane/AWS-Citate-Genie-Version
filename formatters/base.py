"""
citeflex/formatters/base.py

Base formatter class and factory function.
All style-specific formatters inherit from BaseFormatter.

FIX APPLIED: Consistent period handling across all formatters.
All format methods now use _ensure_period() to guarantee consistent
ending punctuation.
"""

from abc import ABC, abstractmethod
from typing import Optional

from models import SourceComponents, CitationType, CitationStyle


class BaseFormatter(ABC):
    """
    Abstract base class for citation formatters.
    
    Each formatter must implement:
    - format(metadata) -> str: Full citation
    - format_short(metadata) -> str: Short form citation
    
    The base class provides:
    - format_ibid(): Standard ibid format
    - _ensure_period(): Consistent ending punctuation
    - _format_authors(): Common author formatting
    """
    
    style: CitationStyle = CitationStyle.CHICAGO
    
    # ==========================================================================
    # FIX: Consistent period handling
    # ==========================================================================
    
    @staticmethod
    def _ensure_period(text: str) -> str:
        """
        Ensure citation ends with a period.
        
        This method guarantees consistent ending punctuation across
        all formatters, fixing the inconsistency bug where some
        format_short methods ended with periods and others didn't.
        
        Args:
            text: Citation text
            
        Returns:
            Text ending with exactly one period
        """
        if not text:
            return ""
        
        text = text.rstrip()
        
        # Don't double-punctuate
        if text.endswith(('.', '?', '!')):
            return text
        
        return text + "."
    
    @staticmethod
    def format_ibid(page: Optional[str] = None) -> str:
        """
        Format an ibid reference.
        
        Standard across all styles: Ibid. or Ibid., PAGE.
        
        Args:
            page: Optional page number
            
        Returns:
            Formatted ibid string
        """
        if page:
            return f"Ibid., {page}."
        return "Ibid."
    
    @abstractmethod
    def format(self, metadata: SourceComponents) -> str:
        """
        Format a full citation.
        
        Args:
            metadata: Citation metadata
            
        Returns:
            Formatted citation string (with <i> tags for italics)
        """
        pass
    
    @abstractmethod
    def format_short(self, metadata: SourceComponents) -> str:
        """
        Format a short form citation (for subsequent references).
        
        Args:
            metadata: Citation metadata
            
        Returns:
            Formatted short citation string
        """
        pass
    
    def _format_authors(
        self,
        authors: list,
        max_authors: int = 3,
        et_al_threshold: int = 3,
        authors_parsed: list = None
    ) -> str:
        """
        Format author list according to style conventions.
        
        Default behavior (can be overridden):
        - 1 author: "First Last"
        - 2 authors: "First Last and First Last"
        - 3+ authors: "First Last et al."
        
        Args:
            authors: List of author names (raw strings, fallback)
            max_authors: Max authors to list before et al.
            et_al_threshold: Number of authors that triggers et al.
            authors_parsed: Structured author data [{"given": "Eric", "family": "Caplan"}, ...]
            
        Returns:
            Formatted author string
        """
        # Prefer structured data if available
        if authors_parsed and len(authors_parsed) > 0:
            formatted_names = []
            for author in authors_parsed:
                name = self._format_single_author(author)
                if name:
                    formatted_names.append(name)
            
            if formatted_names:
                if len(formatted_names) == 1:
                    return formatted_names[0]
                if len(formatted_names) == 2:
                    return f"{formatted_names[0]} and {formatted_names[1]}"
                if len(formatted_names) >= et_al_threshold:
                    return f"{formatted_names[0]} et al."
                return ", ".join(formatted_names[:-1]) + f", and {formatted_names[-1]}"
        
        # Fallback to raw author strings
        if not authors:
            return ""
        
        if len(authors) == 1:
            return authors[0]
        
        if len(authors) == 2:
            return f"{authors[0]} and {authors[1]}"
        
        if len(authors) >= et_al_threshold:
            return f"{authors[0]} et al."
        
        # 3+ but below threshold
        return ", ".join(authors[:-1]) + f", and {authors[-1]}"
    
    def _format_single_author(self, author: dict) -> str:
        """
        Format a single author from structured data.
        
        Handles:
        - Full names: {"given": "Eric", "family": "Caplan"} → "Eric Caplan"
        - Initials: {"given": "E.M.", "family": "Caplan"} → "E. M. Caplan"
        - Organizations: {"family": "CDC", "is_org": True} → "CDC"
        - Institutional: {"family": "CDC", "is_institutional": True} → "CDC"
        
        Args:
            author: Dict with "given" and/or "family" keys
            
        Returns:
            Formatted name string
        """
        if not author:
            return ""
        
        family = author.get('family', '').strip()
        given = author.get('given', '').strip()
        
        # Organizational/institutional authors - use name as-is
        if author.get('is_org') or author.get('is_institutional'):
            return family
        
        # Format initials with proper spacing: "E.M." → "E. M."
        if given:
            given = self._format_initials_with_spacing(given)
        
        # Combine given + family
        if given and family:
            return f"{given} {family}"
        elif family:
            return family
        elif given:
            return given
        else:
            return ""
    
    def _format_initials_with_spacing(self, name: str) -> str:
        """
        Add spacing between initials for proper formatting.
        
        Examples:
        - "E.M." → "E. M."
        - "E.M.C." → "E. M. C."
        - "Eric" → "Eric" (unchanged)
        - "E. M." → "E. M." (unchanged)
        
        Args:
            name: Given name or initials
            
        Returns:
            Properly spaced name/initials
        """
        if not name:
            return ""
        
        # Check if it looks like initials (short, has periods, mostly caps)
        cleaned = name.replace(".", "").replace(" ", "")
        
        # If it's a full name (longer than 3 chars, no periods originally, or mixed case)
        if len(cleaned) > 3 and '.' not in name:
            return name
        
        # If already has spaces after periods, it's properly formatted
        if '. ' in name:
            return name
        
        # Add spaces after periods: "E.M." → "E. M."
        result = ""
        for i, char in enumerate(name):
            result += char
            if char == '.' and i < len(name) - 1 and name[i + 1] != ' ':
                result += ' '
        
        return result.strip()
    
    def _get_last_name(self, full_name: str) -> str:
        """
        Extract last name from full name.
        
        Handles:
        - "First Last" -> "Last"
        - "First Middle Last" -> "Last"
        - "Last, First" -> "Last"
        
        Args:
            full_name: Full author name
            
        Returns:
            Last name
        """
        if not full_name:
            return ""
        
        full_name = full_name.strip()
        
        # Check for "Last, First" format
        if ',' in full_name:
            return full_name.split(',')[0].strip()
        
        # Otherwise assume "First Last"
        parts = full_name.split()
        return parts[-1] if parts else ""
    
    def _is_organizational_author(self, name: str) -> bool:
        """
        Check if a name is an organizational author (should NOT be inverted).
        
        Organizational authors like "World Health Organization" should appear
        verbatim, not be reformatted as "Organization, W. H."
        
        Args:
            name: Author name to check
            
        Returns:
            True if this appears to be an organization name
        """
        if not name:
            return False
        
        name_lower = name.lower()
        
        # Keywords that indicate organizational authors
        org_keywords = [
            # Generic org terms
            'organization', 'organisation', 'department', 'institute',
            'institution', 'university', 'college', 'school',
            'commission', 'committee', 'council', 'board',
            'agency', 'administration', 'bureau', 'office', 'service',
            'foundation', 'association', 'society', 'federation',
            'corporation', 'company', 'group', 'authority',
            'ministry', 'secretariat', 'directorate',
            'center', 'centre', 'centers', 'centres',  # CDC, research centers
            # Government indicators
            'government', 'federal', 'national', 'state of', 'commonwealth',
            'united states', 'united nations', 'european',
            # International bodies
            'world', 'international', 'global',
            # Common org name patterns
            'center for', 'centre for', 'office of', 'bureau of',
            'department of', 'ministry of', 'council on',
        ]
        
        return any(kw in name_lower for kw in org_keywords)


# =============================================================================
# FORMATTER FACTORY
# =============================================================================

def get_formatter(style: str) -> BaseFormatter:
    """
    Get a formatter instance for the specified style.
    
    Args:
        style: Style name (e.g., "Chicago Manual of Style", "APA", "MLA")
        
    Returns:
        Appropriate formatter instance
    
    Supported styles:
        - Chicago Manual of Style (17th) - humanities, history
        - Turabian (9th) - student papers (alias for Chicago)
        - APA (7th) - psychology, social sciences
        - MLA (9th) - literature, humanities
        - Bluebook - US legal
        - OSCOLA - UK legal
        - Harvard - author-date, common in UK/Australia
        - Vancouver (ICMJE) - medical/scientific journals
        - ASA - sociology
    """
    # Import here to avoid circular imports
    from formatters.chicago import ChicagoFormatter
    from formatters.apa import APAFormatter
    from formatters.mla import MLAFormatter
    from formatters.legal import BluebookFormatter, OSCOLAFormatter
    from formatters.harvard import HarvardFormatter
    from formatters.vancouver import VancouverFormatter
    from formatters.asa import ASAFormatter
    
    style_lower = style.lower().strip()
    
    # Notes-bibliography styles
    if 'chicago' in style_lower:
        return ChicagoFormatter()
    elif 'turabian' in style_lower:
        # Turabian is essentially Chicago for students
        return ChicagoFormatter()
    
    # Author-date styles
    elif 'apa' in style_lower:
        return APAFormatter()
    elif 'harvard' in style_lower:
        return HarvardFormatter()
    elif 'asa' in style_lower:
        return ASAFormatter()
    elif 'mla' in style_lower:
        return MLAFormatter()
    
    # Legal styles
    elif 'bluebook' in style_lower:
        return BluebookFormatter()
    elif 'oscola' in style_lower:
        return OSCOLAFormatter()
    
    # Scientific/numbered styles
    elif 'vancouver' in style_lower or 'icmje' in style_lower:
        return VancouverFormatter()
    
    else:
        # Default to Chicago
        return ChicagoFormatter()
