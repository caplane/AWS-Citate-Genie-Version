"""
citation_components_exporter.py

Export citation components to downloadable CSV for every processed document.

Creates a detailed spreadsheet showing:
- All citation components extracted
- Which API was used
- Success/failure status
- Costs per citation

For institutional authors:
- Stores BOTH full name and acronym
- Full name used in reference lists
- Acronym used in author-date parentheticals
"""

import csv
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from models import SourceComponents
from institutional_authors import get_institutional_author_from_url


class CitationComponentsExporter:
    """
    Export citation components to CSV for document processing.
    
    Usage:
        exporter = CitationComponentsExporter(session_id="abc123", filename="Paper.docx")
        
        for citation in citations:
            exporter.add_citation(
                citation_number=1,
                original_query="Smith 2020",
                source_api="crossref",
                success=True,
                cost=0.0,
                components=source_components_obj
            )
        
        csv_path = exporter.save()
    """
    
    def __init__(self, session_id: str, filename: str):
        self.session_id = session_id
        self.filename = filename
        self.timestamp = datetime.now()
        
        # Store citation rows
        self.citations: List[Dict[str, Any]] = []
        
        # Create exports directory
        self.export_dir = Path('exports/citations')
        self.export_dir.mkdir(parents=True, exist_ok=True)
    
    def add_citation(
        self,
        citation_number: int,
        original_query: str,
        source_api: str,
        success: bool,
        cost: float,
        components: Optional[SourceComponents] = None
    ):
        """
        Add a citation to the export.
        
        Args:
            citation_number: Sequential number (1, 2, 3...)
            original_query: Original citation text or URL
            source_api: API used (crossref, serpapi, thenewsapi, etc.)
            success: Whether citation was resolved successfully
            cost: API call cost in dollars
            components: SourceComponents object with extracted metadata
        """
        # Extract all components
        if components:
            # Check for institutional author
            institutional_info = None
            if components.url:
                institutional_info = get_institutional_author_from_url(components.url)
            
            # Build author fields
            author_1_full = ''
            author_1_acronym = ''
            author_2 = ''
            author_3 = ''
            author_4_plus = ''
            
            if institutional_info:
                # Institutional author detected
                author_1_full = institutional_info['full_name']
                author_1_acronym = institutional_info['acronym']
                
                # If there are additional human authors after institutional
                if components.authors and len(components.authors) > 0:
                    # Check if first author is the institutional name
                    if components.authors[0] != institutional_info['full_name']:
                        # Human authors present, institutional is additional
                        author_2 = components.authors[0] if len(components.authors) > 0 else ''
                        author_3 = components.authors[1] if len(components.authors) > 1 else ''
                    else:
                        # First author is institutional, rest are human
                        author_2 = components.authors[1] if len(components.authors) > 1 else ''
                        author_3 = components.authors[2] if len(components.authors) > 2 else ''
                        
                    if len(components.authors) > 3:
                        author_4_plus = '; '.join(components.authors[3:])
            else:
                # Regular authors (not institutional)
                if components.authors:
                    author_1_full = components.authors[0] if len(components.authors) > 0 else ''
                    author_2 = components.authors[1] if len(components.authors) > 1 else ''
                    author_3 = components.authors[2] if len(components.authors) > 2 else ''
                    if len(components.authors) > 3:
                        author_4_plus = '; '.join(components.authors[3:])
            
            row = {
                'citation_number': citation_number,
                'original_query': original_query,
                'source_api': source_api,
                'success': success,
                'cost': f'${cost:.4f}',
                
                # Authors (with institutional support)
                'author_1_full_name': author_1_full,
                'author_1_acronym': author_1_acronym,  # Only for institutional
                'author_2': author_2,
                'author_3': author_3,
                'additional_authors': author_4_plus,
                
                # Title & Publication Info
                'title': components.title or '',
                'year': components.year or '',
                'date': components.date or '',
                
                # Publication venue
                'journal': components.journal or '',
                'newspaper': components.newspaper or '',
                'publisher': components.publisher or '',
                'place': components.place or '',
                
                # Volume/Issue/Pages
                'volume': components.volume or '',
                'issue': components.issue or '',
                'pages': components.pages or '',
                
                # Identifiers
                'doi': components.doi or '',
                'url': components.url or '',
                'pmid': components.pmid or '',
                'isbn': components.isbn or '',
                
                # Legal fields
                'case_name': components.case_name or '',
                'court': components.court or '',
                'citation': components.citation or '',
                'jurisdiction': components.jurisdiction or '',
                
                # Interview fields
                'interviewee': components.interviewee or '',
                'interviewer': components.interviewer or '',
                'location': components.location or '',
                
                # Letter fields
                'sender': components.sender or '',
                'recipient': components.recipient or '',
                
                # Book fields
                'edition': components.edition or '',
                
                # Metadata
                'citation_type': components.citation_type.name if components.citation_type else '',
                'source_engine': components.source_engine or source_api,
            }
        else:
            # Failed citation - no components
            row = {
                'citation_number': citation_number,
                'original_query': original_query,
                'source_api': source_api,
                'success': False,
                'cost': f'${cost:.4f}',
                'author_1_full_name': '',
                'author_1_acronym': '',
                'author_2': '',
                'author_3': '',
                'additional_authors': '',
                'title': '',
                'year': '',
                'date': '',
                'journal': '',
                'newspaper': '',
                'publisher': '',
                'place': '',
                'volume': '',
                'issue': '',
                'pages': '',
                'doi': '',
                'url': '',
                'pmid': '',
                'isbn': '',
                'case_name': '',
                'court': '',
                'citation': '',
                'jurisdiction': '',
                'interviewee': '',
                'interviewer': '',
                'location': '',
                'sender': '',
                'recipient': '',
                'edition': '',
                'citation_type': '',
                'source_engine': source_api,
            }
        
        self.citations.append(row)
    
    def save(self) -> str:
        """
        Save citation components to CSV.
        
        Returns:
            Path to saved CSV file
        """
        # Generate filename: YYYYMMDD_HHMMSS_sessionid_components.csv
        timestamp_str = self.timestamp.strftime('%Y%m%d_%H%M%S')
        csv_filename = f"{timestamp_str}_{self.session_id}_components.csv"
        csv_path = self.export_dir / csv_filename
        
        # Define column order
        fieldnames = [
            'citation_number',
            'original_query',
            'source_api',
            'success',
            'cost',
            
            # Authors
            'author_1_full_name',
            'author_1_acronym',  # For institutional authors only
            'author_2',
            'author_3',
            'additional_authors',
            
            # Core citation info
            'title',
            'year',
            'date',
            
            # Publication venue
            'journal',
            'newspaper',
            'publisher',
            'place',
            
            # Volume/Issue/Pages
            'volume',
            'issue',
            'pages',
            
            # Identifiers
            'doi',
            'url',
            'pmid',
            'isbn',
            
            # Legal
            'case_name',
            'court',
            'citation',
            'jurisdiction',
            
            # Interview
            'interviewee',
            'interviewer',
            'location',
            
            # Letter
            'sender',
            'recipient',
            
            # Book
            'edition',
            
            # Metadata
            'citation_type',
            'source_engine',
        ]
        
        # Write CSV
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.citations)
        
        print(f"[CitationExporter] Saved components CSV: {csv_path}")
        
        # Also save a summary
        self._save_summary(csv_path)
        
        return str(csv_path)
    
    def _save_summary(self, csv_path: Path):
        """Save summary stats alongside CSV."""
        summary_path = csv_path.with_suffix('.summary.txt')
        
        total_cost = sum(
            float(row['cost'].replace('$', '')) 
            for row in self.citations
        )
        successful = sum(1 for row in self.citations if row['success'])
        failed = len(self.citations) - successful
        
        # Count by API
        api_counts = {}
        for row in self.citations:
            api = row['source_api']
            if api not in api_counts:
                api_counts[api] = 0
            api_counts[api] += 1
        
        # Count institutional vs regular authors
        institutional_count = sum(
            1 for row in self.citations 
            if row['author_1_acronym']  # Has acronym = institutional
        )
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(f"Citation Components Export Summary\n")
            f.write(f"{'=' * 60}\n\n")
            
            f.write(f"Document: {self.filename}\n")
            f.write(f"Session ID: {self.session_id}\n")
            f.write(f"Exported: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write(f"TOTALS\n")
            f.write(f"{'-' * 60}\n")
            f.write(f"Total Citations: {len(self.citations)}\n")
            f.write(f"Successful: {successful}\n")
            f.write(f"Failed: {failed}\n")
            f.write(f"Success Rate: {(successful/len(self.citations)*100):.1f}%\n\n")
            
            f.write(f"AUTHORS\n")
            f.write(f"{'-' * 60}\n")
            f.write(f"Institutional Authors: {institutional_count}\n")
            f.write(f"Regular Authors: {len(self.citations) - institutional_count}\n\n")
            
            f.write(f"COSTS\n")
            f.write(f"{'-' * 60}\n")
            f.write(f"Total Cost: ${total_cost:.4f}\n")
            f.write(f"Average per Citation: ${(total_cost/len(self.citations)):.4f}\n\n")
            
            f.write(f"API USAGE\n")
            f.write(f"{'-' * 60}\n")
            for api, count in sorted(api_counts.items(), key=lambda x: x[1], reverse=True):
                f.write(f"{api:20s} {count:4d} citations\n")
            
            f.write(f"\nCSV file: {csv_path.name}\n")


# =============================================================================
# INTEGRATION WITH DocumentLogger
# =============================================================================

def create_exporter_from_document_logger(doc_logger) -> CitationComponentsExporter:
    """
    Create CitationComponentsExporter from a DocumentLogger's data.
    
    This allows you to export to CSV format using the same data
    that's already logged in DocumentLogger.
    
    Args:
        doc_logger: DocumentLogger instance
        
    Returns:
        CitationComponentsExporter with all citations loaded
    """
    exporter = CitationComponentsExporter(
        session_id=doc_logger.session_id,
        filename=doc_logger.filename
    )
    
    # Copy all citations from document logger
    for citation_data in doc_logger.citations:
        # Reconstruct SourceComponents-like object for exporter
        # (exporter expects SourceComponents, logger stores dict)
        
        # Note: This is a simplified reconstruction
        # In practice, you might want to store the actual SourceComponents
        # in DocumentLogger as well
        
        exporter.add_citation(
            citation_number=citation_data['citation_number'],
            original_query=citation_data['query'],
            source_api=citation_data['source'],
            success=citation_data['success'],
            cost=citation_data['cost'],
            components=None  # Would need to reconstruct from citation_data
        )
    
    return exporter


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == '__main__':
    # Example: Export citation components
    exporter = CitationComponentsExporter(
        session_id="test123",
        filename="Research Paper.docx"
    )
    
    # Simulate adding citations
    from models import SourceComponents, CitationType
    
    # Regular author
    components1 = SourceComponents(
        title="Machine Learning in Medicine",
        authors=["Smith, John", "Doe, Jane"],
        year="2020",
        journal="Nature Medicine",
        volume="26",
        issue="3",
        pages="445-452",
        doi="10.1038/s41591-020-0123-4",
        citation_type=CitationType.JOURNAL
    )
    
    exporter.add_citation(
        citation_number=1,
        original_query="Smith et al 2020",
        source_api="crossref",
        success=True,
        cost=0.0,
        components=components1
    )
    
    # Institutional author (CDC)
    components2 = SourceComponents(
        title="COVID-19 Surveillance Report",
        authors=["Centers for Disease Control and Prevention"],
        date="December 21, 2024",
        url="https://www.cdc.gov/covid/reports/2024.html",
        citation_type=CitationType.URL
    )
    
    exporter.add_citation(
        citation_number=2,
        original_query="https://www.cdc.gov/covid/reports/2024.html",
        source_api="html_scrape",
        success=True,
        cost=0.0,
        components=components2
    )
    
    # Failed citation
    exporter.add_citation(
        citation_number=3,
        original_query="Obscure reference 1887",
        source_api="crossref",
        success=False,
        cost=0.0,
        components=None
    )
    
    # Save
    csv_path = exporter.save()
    print(f"\nExported to: {csv_path}")
