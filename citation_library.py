"""
engines/citation_library.py

Citation Library - Two-tier caching system for CitateGenie.

Tier 1: Global Library - All successful lookups, shared across users
Tier 2: User Library - Per-user citations with overrides

Lookup hierarchy:
    1. User Library (if user_id provided) → FREE, instant
    2. Global Library → FREE, instant  
    3. Free APIs (CrossRef, OpenAlex) → FREE, slower
    4. AI (GPT-4o, Claude) → COSTS $, result cached to global

Over time, hit rate on tiers 1-2 approaches 90%+, making marginal cost → $0.

Version History:
    2025-12-11 V1.0: Initial implementation
"""

import re
import json
import os
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime

# Database connection (use environment variable)
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# Try to import psycopg2, fall back gracefully if not available
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False
    print("[CitationLibrary] psycopg2 not installed - library features disabled")


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class LibraryCitation:
    """A citation record from the library."""
    id: int
    lookup_key: str
    citation_type: str
    title: str
    year: str
    authors: List[str]  # Full formatted names
    journal: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    publisher: Optional[str] = None
    doi: Optional[str] = None
    source_engine: str = "library"
    confidence: float = 1.0
    lookup_count: int = 0
    
    def to_components(self):
        """Convert to SourceComponents for formatter compatibility."""
        from models import SourceComponents, CitationType
        
        type_map = {
            'journal': CitationType.JOURNAL,
            'book': CitationType.BOOK,
            'chapter': CitationType.BOOK,
            'newspaper': CitationType.NEWSPAPER,
        }
        
        return SourceComponents(
            citation_type=type_map.get(self.citation_type, CitationType.JOURNAL),
            title=self.title,
            authors=self.authors,
            year=self.year,
            journal=self.journal or '',
            volume=self.volume or '',
            issue=self.issue or '',
            pages=self.pages or '',
            publisher=self.publisher or '',
            doi=self.doi or '',
            source_engine=f"Library ({self.source_engine})",
            confidence=self.confidence
        )


# =============================================================================
# KEY NORMALIZATION
# =============================================================================

def normalize_author_name(name: str) -> str:
    """
    Normalize an author name for lookup key generation.
    
    "Endler" → "endler"
    "O'Brien" → "obrien"
    "van der Berg" → "vanderberg"
    """
    # Lowercase
    name = name.lower()
    # Remove punctuation
    name = re.sub(r'[^a-z]', '', name)
    return name


def generate_lookup_key(authors: List[str], year: str) -> str:
    """
    Generate a normalized lookup key from authors and year.
    
    Args:
        authors: List of author last names ["Endler", "Rushton", "Roediger"]
        year: Publication year "1978"
        
    Returns:
        Normalized key: "endler_roediger_rushton_1978" (sorted alphabetically)
    """
    # Normalize each author
    normalized = [normalize_author_name(a) for a in authors if a]
    # Remove empty strings
    normalized = [n for n in normalized if n]
    # Sort alphabetically for consistent keys regardless of author order
    normalized.sort()
    # Join with underscores, add year
    key = '_'.join(normalized) + '_' + str(year)
    return key


def generate_alias_keys(author: str, year: str, second_author: str = None, 
                        third_author: str = None, is_et_al: bool = False) -> List[str]:
    """
    Generate all possible lookup keys for a citation reference.
    
    A citation "(Endler, Rushton, & Roediger, 1978)" might be cited as:
    - Full: "endler_roediger_rushton_1978"
    - Et al: "endler_et_al_1978"
    - First only: "endler_1978"
    
    Returns all variants to check.
    """
    keys = []
    authors = [author]
    if second_author:
        authors.append(second_author)
    if third_author:
        authors.append(third_author)
    
    # Primary key with all known authors
    keys.append(generate_lookup_key(authors, year))
    
    # If more than 1 author, also generate "et al" variant
    if len(authors) > 1 or is_et_al:
        keys.append(f"{normalize_author_name(author)}_et_al_{year}")
    
    # First author only (for broad matching)
    if len(authors) > 1:
        keys.append(f"{normalize_author_name(author)}_{year}")
    
    return keys


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def get_connection():
    """Get a database connection."""
    if not HAS_POSTGRES or not DATABASE_URL:
        return None
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"[CitationLibrary] DB connection error: {e}")
        return None


def lookup_global(lookup_key: str) -> Optional[LibraryCitation]:
    """
    Look up a citation in the global library.
    
    Args:
        lookup_key: Normalized key like "endler_rushton_roediger_1978"
        
    Returns:
        LibraryCitation if found, None otherwise
    """
    conn = get_connection()
    if not conn:
        return None
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Check main lookup_key first
            cur.execute("""
                SELECT c.*, ARRAY_AGG(ca.full_name ORDER BY ca.position) as authors
                FROM citations c
                LEFT JOIN citation_authors ca ON c.id = ca.citation_id
                WHERE c.lookup_key = %s
                GROUP BY c.id
            """, (lookup_key,))
            
            row = cur.fetchone()
            
            if not row:
                # Check aliases
                cur.execute("""
                    SELECT c.*, ARRAY_AGG(ca.full_name ORDER BY ca.position) as authors
                    FROM citations c
                    JOIN lookup_aliases a ON c.id = a.citation_id
                    LEFT JOIN citation_authors ca ON c.id = ca.citation_id
                    WHERE a.alias_key = %s
                    GROUP BY c.id
                """, (lookup_key,))
                row = cur.fetchone()
            
            if row:
                return LibraryCitation(
                    id=row['id'],
                    lookup_key=row['lookup_key'],
                    citation_type=row['citation_type'],
                    title=row['title'],
                    year=row['year'],
                    authors=row['authors'] or [],
                    journal=row.get('journal'),
                    volume=row.get('volume'),
                    issue=row.get('issue'),
                    pages=row.get('pages'),
                    publisher=row.get('publisher'),
                    doi=row.get('doi'),
                    source_engine=row.get('source_engine', 'unknown'),
                    confidence=float(row.get('confidence', 0.8)),
                    lookup_count=row.get('lookup_count', 0)
                )
            
            return None
            
    except Exception as e:
        print(f"[CitationLibrary] Lookup error: {e}")
        return None
    finally:
        conn.close()


def lookup_user_library(user_id: int, lookup_key: str) -> Optional[LibraryCitation]:
    """
    Look up a citation in a user's personal library.
    
    Checks for user-specific overrides first.
    """
    conn = get_connection()
    if not conn:
        return None
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT c.*, ul.override_data,
                       ARRAY_AGG(ca.full_name ORDER BY ca.position) as authors
                FROM user_libraries ul
                JOIN citations c ON ul.citation_id = c.id
                LEFT JOIN citation_authors ca ON c.id = ca.citation_id
                WHERE ul.user_id = %s AND c.lookup_key = %s
                GROUP BY c.id, ul.override_data
            """, (user_id, lookup_key))
            
            row = cur.fetchone()
            
            if row:
                citation = LibraryCitation(
                    id=row['id'],
                    lookup_key=row['lookup_key'],
                    citation_type=row['citation_type'],
                    title=row['title'],
                    year=row['year'],
                    authors=row['authors'] or [],
                    journal=row.get('journal'),
                    volume=row.get('volume'),
                    issue=row.get('issue'),
                    pages=row.get('pages'),
                    publisher=row.get('publisher'),
                    doi=row.get('doi'),
                    source_engine=row.get('source_engine', 'unknown'),
                    confidence=1.0,  # User library = high confidence
                    lookup_count=row.get('lookup_count', 0)
                )
                
                # Apply user overrides if any
                if row.get('override_data'):
                    overrides = row['override_data']
                    if isinstance(overrides, str):
                        overrides = json.loads(overrides)
                    for key, value in overrides.items():
                        if hasattr(citation, key):
                            setattr(citation, key, value)
                
                return citation
            
            return None
            
    except Exception as e:
        print(f"[CitationLibrary] User lookup error: {e}")
        return None
    finally:
        conn.close()


def save_to_global(components, lookup_keys: List[str]) -> Optional[int]:
    """
    Save a citation to the global library.
    
    Args:
        components: SourceComponents object from API lookup
        lookup_keys: List of keys to associate with this citation
        
    Returns:
        citation_id if saved, None on error
    """
    conn = get_connection()
    if not conn:
        return None
    
    try:
        with conn.cursor() as cur:
            # Check if primary key already exists
            primary_key = lookup_keys[0]
            cur.execute("SELECT id FROM citations WHERE lookup_key = %s", (primary_key,))
            existing = cur.fetchone()
            
            if existing:
                # Update lookup count
                cur.execute("""
                    UPDATE citations SET lookup_count = lookup_count + 1, 
                                         last_lookup_at = NOW()
                    WHERE id = %s
                """, (existing[0],))
                conn.commit()
                return existing[0]
            
            # Insert new citation
            cur.execute("""
                INSERT INTO citations (
                    lookup_key, citation_type, title, year, journal, volume, 
                    issue, pages, publisher, doi, source_engine, confidence
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                primary_key,
                components.citation_type.value if hasattr(components.citation_type, 'value') else str(components.citation_type),
                components.title,
                components.year,
                components.journal,
                components.volume,
                components.issue,
                components.pages,
                components.publisher,
                components.doi,
                components.source_engine,
                components.confidence
            ))
            
            citation_id = cur.fetchone()[0]
            
            # Insert authors
            for i, author in enumerate(components.authors, 1):
                # Parse author name
                last_name = author.split(',')[0].strip() if ',' in author else author.split()[-1]
                first_name = author.split(',')[1].strip() if ',' in author else ' '.join(author.split()[:-1])
                
                cur.execute("""
                    INSERT INTO citation_authors (
                        citation_id, position, last_name, first_name, 
                        full_name, name_normalized
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    citation_id, i, last_name, first_name,
                    author, normalize_author_name(last_name)
                ))
            
            # Insert alias keys
            for alias in lookup_keys[1:]:
                try:
                    cur.execute("""
                        INSERT INTO lookup_aliases (citation_id, alias_key)
                        VALUES (%s, %s)
                        ON CONFLICT (alias_key) DO NOTHING
                    """, (citation_id, alias))
                except:
                    pass  # Ignore duplicate aliases
            
            conn.commit()
            print(f"[CitationLibrary] Saved to global: {components.title[:50]}...")
            return citation_id
            
    except Exception as e:
        print(f"[CitationLibrary] Save error: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def add_to_user_library(user_id: int, citation_id: int) -> bool:
    """Add a citation to a user's personal library."""
    conn = get_connection()
    if not conn:
        return False
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_libraries (user_id, citation_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, citation_id) 
                DO UPDATE SET use_count = user_libraries.use_count + 1,
                              last_used_at = NOW()
            """, (user_id, citation_id))
            conn.commit()
            return True
    except Exception as e:
        print(f"[CitationLibrary] Add to user library error: {e}")
        return False
    finally:
        conn.close()


def log_lookup(raw_query: str, normalized_key: str, hit_source: str,
               citation_id: int = None, user_id: int = None, 
               session_id: str = None, lookup_time_ms: int = None):
    """Log a lookup for analytics."""
    conn = get_connection()
    if not conn:
        return
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO lookup_log (
                    raw_query, normalized_key, hit_source, citation_id,
                    user_id, session_id, lookup_time_ms
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (raw_query, normalized_key, hit_source, citation_id,
                  user_id, session_id, lookup_time_ms))
            conn.commit()
    except Exception as e:
        print(f"[CitationLibrary] Log error: {e}")
    finally:
        conn.close()


# =============================================================================
# MAIN LOOKUP FUNCTION
# =============================================================================

def library_lookup(
    author: str,
    year: str,
    second_author: str = None,
    third_author: str = None,
    is_et_al: bool = False,
    user_id: int = None,
    session_id: str = None
) -> Tuple[Optional[LibraryCitation], str]:
    """
    Look up a citation in the library system.
    
    Checks in order:
        1. User's personal library (if user_id provided)
        2. Global library
    
    Args:
        author: Primary author surname
        year: Publication year
        second_author: Optional second author
        third_author: Optional third author
        is_et_al: Whether citation was "et al."
        user_id: Optional user ID for personal library
        session_id: Optional session ID for logging
        
    Returns:
        Tuple of (LibraryCitation or None, hit_source)
        hit_source is one of: "user", "global", "miss"
    """
    import time
    start = time.time()
    
    # Generate all possible keys
    keys = generate_alias_keys(author, year, second_author, third_author, is_et_al)
    raw_query = f"({author}"
    if second_author:
        raw_query += f", {second_author}"
    if third_author:
        raw_query += f", & {third_author}"
    raw_query += f", {year})"
    
    primary_key = keys[0]
    result = None
    hit_source = "miss"
    
    # 1. Check user library first
    if user_id:
        for key in keys:
            result = lookup_user_library(user_id, key)
            if result:
                hit_source = "user"
                print(f"[CitationLibrary] USER HIT: {result.title[:50]}...")
                break
    
    # 2. Check global library
    if not result:
        for key in keys:
            result = lookup_global(key)
            if result:
                hit_source = "global"
                print(f"[CitationLibrary] GLOBAL HIT: {result.title[:50]}...")
                # Add to user library for faster future lookups
                if user_id:
                    add_to_user_library(user_id, result.id)
                break
    
    # Log the lookup
    elapsed_ms = int((time.time() - start) * 1000)
    log_lookup(
        raw_query=raw_query,
        normalized_key=primary_key,
        hit_source=hit_source,
        citation_id=result.id if result else None,
        user_id=user_id,
        session_id=session_id,
        lookup_time_ms=elapsed_ms
    )
    
    return result, hit_source


# =============================================================================
# STATISTICS
# =============================================================================

def get_library_stats() -> Dict[str, Any]:
    """Get statistics about the citation library."""
    conn = get_connection()
    if not conn:
        return {"error": "No database connection"}
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            stats = {}
            
            # Total citations
            cur.execute("SELECT COUNT(*) as count FROM citations")
            stats['total_citations'] = cur.fetchone()['count']
            
            # Total users
            cur.execute("SELECT COUNT(*) as count FROM users")
            stats['total_users'] = cur.fetchone()['count']
            
            # Total lookups
            cur.execute("SELECT COUNT(*) as count FROM lookup_log")
            stats['total_lookups'] = cur.fetchone()['count']
            
            # Hit rate (last 7 days)
            cur.execute("""
                SELECT hit_source, COUNT(*) as count
                FROM lookup_log
                WHERE created_at > NOW() - INTERVAL '7 days'
                GROUP BY hit_source
            """)
            hits = {row['hit_source']: row['count'] for row in cur.fetchall()}
            total = sum(hits.values()) or 1
            stats['hit_rate_7d'] = {
                'global': round(hits.get('global', 0) / total * 100, 1),
                'user': round(hits.get('user', 0) / total * 100, 1),
                'api': round(hits.get('api', 0) / total * 100, 1),
                'ai': round(hits.get('ai', 0) / total * 100, 1),
                'miss': round(hits.get('miss', 0) / total * 100, 1),
            }
            
            # Most looked up citations
            cur.execute("""
                SELECT title, year, lookup_count 
                FROM citations 
                ORDER BY lookup_count DESC 
                LIMIT 10
            """)
            stats['most_popular'] = [dict(row) for row in cur.fetchall()]
            
            return stats
            
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()
