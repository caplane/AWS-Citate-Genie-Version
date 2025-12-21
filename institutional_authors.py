"""
institutional_authors.py

Mapping of domains to institutional authors with full names and acronyms.

Used for:
1. Detecting when a URL is authored by an institution (not a person)
2. Providing acronyms for author-date in-text citations: (CDC, 2024)
3. Providing full names for footnotes/endnotes/reference lists

Rules:
- In-text parenthetical (author-date): Use ACRONYM
- Footnotes, endnotes, reference lists: Use FULL NAME
"""

from typing import Dict, Optional, Tuple

# Comprehensive institutional author mapping
INSTITUTIONAL_AUTHORS = {
    # ==========================================================================
    # UNITED STATES - FEDERAL GOVERNMENT
    # ==========================================================================
    
    # Health & Human Services
    'cdc.gov': {
        'full_name': 'Centers for Disease Control and Prevention',
        'acronym': 'CDC',
        'type': 'government',
        'country': 'US'
    },
    'nih.gov': {
        'full_name': 'National Institutes of Health',
        'acronym': 'NIH',
        'type': 'government',
        'country': 'US'
    },
    'fda.gov': {
        'full_name': 'Food and Drug Administration',
        'acronym': 'FDA',
        'type': 'government',
        'country': 'US'
    },
    'cms.gov': {
        'full_name': 'Centers for Medicare & Medicaid Services',
        'acronym': 'CMS',
        'type': 'government',
        'country': 'US'
    },
    'hhs.gov': {
        'full_name': 'Department of Health and Human Services',
        'acronym': 'HHS',
        'type': 'government',
        'country': 'US'
    },
    
    # Environmental
    'epa.gov': {
        'full_name': 'Environmental Protection Agency',
        'acronym': 'EPA',
        'type': 'government',
        'country': 'US'
    },
    'noaa.gov': {
        'full_name': 'National Oceanic and Atmospheric Administration',
        'acronym': 'NOAA',
        'type': 'government',
        'country': 'US'
    },
    'usgs.gov': {
        'full_name': 'United States Geological Survey',
        'acronym': 'USGS',
        'type': 'government',
        'country': 'US'
    },
    
    # Energy & Infrastructure
    'energy.gov': {
        'full_name': 'Department of Energy',
        'acronym': 'DOE',
        'type': 'government',
        'country': 'US'
    },
    'eia.gov': {
        'full_name': 'Energy Information Administration',
        'acronym': 'EIA',
        'type': 'government',
        'country': 'US'
    },
    'transportation.gov': {
        'full_name': 'Department of Transportation',
        'acronym': 'DOT',
        'type': 'government',
        'country': 'US'
    },
    'faa.gov': {
        'full_name': 'Federal Aviation Administration',
        'acronym': 'FAA',
        'type': 'government',
        'country': 'US'
    },
    
    # Defense & Security
    'defense.gov': {
        'full_name': 'Department of Defense',
        'acronym': 'DOD',
        'type': 'government',
        'country': 'US'
    },
    'dhs.gov': {
        'full_name': 'Department of Homeland Security',
        'acronym': 'DHS',
        'type': 'government',
        'country': 'US'
    },
    'state.gov': {
        'full_name': 'Department of State',
        'acronym': 'State Department',
        'type': 'government',
        'country': 'US'
    },
    
    # Justice & Law Enforcement
    'justice.gov': {
        'full_name': 'Department of Justice',
        'acronym': 'DOJ',
        'type': 'government',
        'country': 'US'
    },
    'fbi.gov': {
        'full_name': 'Federal Bureau of Investigation',
        'acronym': 'FBI',
        'type': 'government',
        'country': 'US'
    },
    
    # Economic & Financial
    'treasury.gov': {
        'full_name': 'Department of the Treasury',
        'acronym': 'Treasury',
        'type': 'government',
        'country': 'US'
    },
    'federalreserve.gov': {
        'full_name': 'Federal Reserve',
        'acronym': 'Federal Reserve',
        'type': 'government',
        'country': 'US'
    },
    'sec.gov': {
        'full_name': 'Securities and Exchange Commission',
        'acronym': 'SEC',
        'type': 'government',
        'country': 'US'
    },
    'ftc.gov': {
        'full_name': 'Federal Trade Commission',
        'acronym': 'FTC',
        'type': 'government',
        'country': 'US'
    },
    
    # Labor & Education
    'dol.gov': {
        'full_name': 'Department of Labor',
        'acronym': 'DOL',
        'type': 'government',
        'country': 'US'
    },
    'ed.gov': {
        'full_name': 'Department of Education',
        'acronym': 'ED',
        'type': 'government',
        'country': 'US'
    },
    
    # Agriculture & Food
    'usda.gov': {
        'full_name': 'Department of Agriculture',
        'acronym': 'USDA',
        'type': 'government',
        'country': 'US'
    },
    
    # Veterans Affairs
    'va.gov': {
        'full_name': 'Department of Veterans Affairs',
        'acronym': 'VA',
        'type': 'government',
        'country': 'US'
    },
    
    # ==========================================================================
    # INTERNATIONAL ORGANIZATIONS
    # ==========================================================================
    
    'who.int': {
        'full_name': 'World Health Organization',
        'acronym': 'WHO',
        'type': 'international',
        'country': 'International'
    },
    'un.org': {
        'full_name': 'United Nations',
        'acronym': 'UN',
        'type': 'international',
        'country': 'International'
    },
    'unicef.org': {
        'full_name': 'United Nations Children\'s Fund',
        'acronym': 'UNICEF',
        'type': 'international',
        'country': 'International'
    },
    'worldbank.org': {
        'full_name': 'World Bank',
        'acronym': 'World Bank',
        'type': 'international',
        'country': 'International'
    },
    'imf.org': {
        'full_name': 'International Monetary Fund',
        'acronym': 'IMF',
        'type': 'international',
        'country': 'International'
    },
    'wto.org': {
        'full_name': 'World Trade Organization',
        'acronym': 'WTO',
        'type': 'international',
        'country': 'International'
    },
    'oecd.org': {
        'full_name': 'Organisation for Economic Co-operation and Development',
        'acronym': 'OECD',
        'type': 'international',
        'country': 'International'
    },
    'iea.org': {
        'full_name': 'International Energy Agency',
        'acronym': 'IEA',
        'type': 'international',
        'country': 'International'
    },
    'ipcc.ch': {
        'full_name': 'Intergovernmental Panel on Climate Change',
        'acronym': 'IPCC',
        'type': 'international',
        'country': 'International'
    },
    'nato.int': {
        'full_name': 'North Atlantic Treaty Organization',
        'acronym': 'NATO',
        'type': 'international',
        'country': 'International'
    },
    
    # ==========================================================================
    # NONPROFITS & ADVOCACY ORGANIZATIONS
    # ==========================================================================
    
    'acore.org': {
        'full_name': 'American Council on Renewable Energy',
        'acronym': 'ACORE',
        'type': 'nonprofit',
        'country': 'US'
    },
    'nrdc.org': {
        'full_name': 'Natural Resources Defense Council',
        'acronym': 'NRDC',
        'type': 'nonprofit',
        'country': 'US'
    },
    'sierraclub.org': {
        'full_name': 'Sierra Club',
        'acronym': 'Sierra Club',
        'type': 'nonprofit',
        'country': 'US'
    },
    'aclu.org': {
        'full_name': 'American Civil Liberties Union',
        'acronym': 'ACLU',
        'type': 'nonprofit',
        'country': 'US'
    },
    'redcross.org': {
        'full_name': 'American Red Cross',
        'acronym': 'Red Cross',
        'type': 'nonprofit',
        'country': 'US'
    },
    'amnesty.org': {
        'full_name': 'Amnesty International',
        'acronym': 'Amnesty International',
        'type': 'nonprofit',
        'country': 'International'
    },
    'hrw.org': {
        'full_name': 'Human Rights Watch',
        'acronym': 'HRW',
        'type': 'nonprofit',
        'country': 'International'
    },
    
    # ==========================================================================
    # RESEARCH & THINK TANKS
    # ==========================================================================
    
    'rand.org': {
        'full_name': 'RAND Corporation',
        'acronym': 'RAND',
        'type': 'research',
        'country': 'US'
    },
    'brookings.edu': {
        'full_name': 'Brookings Institution',
        'acronym': 'Brookings',
        'type': 'research',
        'country': 'US'
    },
    'aei.org': {
        'full_name': 'American Enterprise Institute',
        'acronym': 'AEI',
        'type': 'research',
        'country': 'US'
    },
    'heritage.org': {
        'full_name': 'Heritage Foundation',
        'acronym': 'Heritage Foundation',
        'type': 'research',
        'country': 'US'
    },
    'cfr.org': {
        'full_name': 'Council on Foreign Relations',
        'acronym': 'CFR',
        'type': 'research',
        'country': 'US'
    },
    'csis.org': {
        'full_name': 'Center for Strategic and International Studies',
        'acronym': 'CSIS',
        'type': 'research',
        'country': 'US'
    },
    'atlanticcouncil.org': {
        'full_name': 'Atlantic Council',
        'acronym': 'Atlantic Council',
        'type': 'research',
        'country': 'US'
    },
    
    # ==========================================================================
    # MEDICAL & SCIENTIFIC ORGANIZATIONS
    # ==========================================================================
    
    'ama-assn.org': {
        'full_name': 'American Medical Association',
        'acronym': 'AMA',
        'type': 'professional',
        'country': 'US'
    },
    'cancer.org': {
        'full_name': 'American Cancer Society',
        'acronym': 'ACS',
        'type': 'nonprofit',
        'country': 'US'
    },
    'heart.org': {
        'full_name': 'American Heart Association',
        'acronym': 'AHA',
        'type': 'nonprofit',
        'country': 'US'
    },
    'mayoclinic.org': {
        'full_name': 'Mayo Clinic',
        'acronym': 'Mayo Clinic',
        'type': 'medical',
        'country': 'US'
    },
}


def get_institutional_author(domain: str) -> Optional[Dict[str, str]]:
    """
    Get institutional author info from domain.
    
    Args:
        domain: Domain like 'cdc.gov', 'who.int'
        
    Returns:
        Dict with full_name, acronym, type, country or None
        
    Example:
        >>> info = get_institutional_author('cdc.gov')
        >>> info['full_name']
        'Centers for Disease Control and Prevention'
        >>> info['acronym']
        'CDC'
    """
    domain_lower = domain.lower().replace('www.', '')
    
    # Direct match
    if domain_lower in INSTITUTIONAL_AUTHORS:
        return INSTITUTIONAL_AUTHORS[domain_lower]
    
    # Partial match (e.g., 'nimh.nih.gov' should match 'nih.gov')
    for inst_domain, info in INSTITUTIONAL_AUTHORS.items():
        if inst_domain in domain_lower:
            return info
    
    return None


def format_institutional_author(domain: str, use_acronym: bool = False) -> Optional[str]:
    """
    Format institutional author for citation.
    
    Args:
        domain: Domain like 'cdc.gov'
        use_acronym: If True, return acronym (for author-date in-text)
                    If False, return full name (for footnotes/references)
    
    Returns:
        Formatted author name or None
        
    Example:
        >>> format_institutional_author('cdc.gov', use_acronym=True)
        'CDC'
        >>> format_institutional_author('cdc.gov', use_acronym=False)
        'Centers for Disease Control and Prevention'
    """
    info = get_institutional_author(domain)
    if not info:
        return None
    
    return info['acronym'] if use_acronym else info['full_name']


def is_institutional_domain(domain: str) -> bool:
    """Check if domain belongs to an institutional author."""
    return get_institutional_author(domain) is not None


def extract_domain_from_url(url: str) -> str:
    """Extract clean domain from URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc.replace('www.', '')
    return domain


def get_institutional_author_from_url(url: str) -> Optional[Dict[str, str]]:
    """
    Get institutional author info directly from URL.
    
    Args:
        url: Full URL like 'https://www.cdc.gov/reports/...'
        
    Returns:
        Dict with full_name, acronym, type, country or None
    """
    domain = extract_domain_from_url(url)
    return get_institutional_author(domain)


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == '__main__':
    # Test examples
    test_urls = [
        'https://www.cdc.gov/covid/reports/2024.html',
        'https://who.int/publications/health-report',
        'https://www.epa.gov/climate-change',
        'https://acore.org/renewable-energy-report',
        'https://www.nytimes.com/article'  # Not institutional
    ]
    
    print("Institutional Author Detection Test")
    print("=" * 60)
    
    for url in test_urls:
        info = get_institutional_author_from_url(url)
        if info:
            print(f"\nURL: {url}")
            print(f"  Full name: {info['full_name']}")
            print(f"  Acronym: {info['acronym']}")
            print(f"  In-text: ({info['acronym']}, 2024)")
            print(f"  Reference: {info['full_name']}. (2024). Title.")
        else:
            print(f"\nURL: {url}")
            print(f"  → Not an institutional author (regular citation)")
