"""
processors/endnote_to_author_date.py

Converts documents with footnotes/endnotes to author-date format (APA, MLA, ASA, etc.).

This processor handles the workflow where users:
1. Write drafts using Word's footnote/endnote function
2. Want final output in author-date style with References section

The transformation:
1. Extract citations from footnotes/endnotes
2. Extract URLs and (Author, Year) patterns from body text (edge case)
3. Look up metadata for all citations
4. Remove superscript numbers from body
5. Insert (Author, Date) at each superscript location
6. Remove the footnotes/endnotes section
7. Append alphabetized References section

Uses SourceComponents nomenclature throughout (not "metadata").

Version History:
    2025-12-20: Initial implementation
"""

import os
import re
import copy
import zipfile
import tempfile
import shutil
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from models import SourceComponents, CitationType
from formatters.base import get_formatter


# =============================================================================
# XML NAMESPACES
# =============================================================================

NAMESPACES = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}

# Extended namespaces to preserve Word document structure
ALL_NAMESPACES = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
    'w14': 'http://schemas.microsoft.com/office/word/2010/wordml',
    'w15': 'http://schemas.microsoft.com/office/word/2012/wordml',
    'w16': 'http://schemas.microsoft.com/office/word/2018/wordml',
    'wps': 'http://schemas.microsoft.com/office/word/2010/wordprocessingShape',
}

# Register namespaces to preserve prefixes
for prefix, uri in ALL_NAMESPACES.items():
    ET.register_namespace(prefix, uri)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class NoteReference:
    """Represents a footnote/endnote reference found in document body."""
    note_id: str
    note_type: str  # 'footnote' or 'endnote'
    paragraph_index: int
    run_element: ET.Element  # The run containing the reference
    paragraph_element: ET.Element  # The paragraph containing the run
    position_in_body: int  # Character position for sorting


@dataclass
class NoteContent:
    """Represents content extracted from a footnote/endnote."""
    note_id: str
    note_type: str
    text: str  # Plain text content
    xml_element: ET.Element  # Original XML element


@dataclass
class CitationMatch:
    """A citation found in the document (from notes or body)."""
    source: str  # 'footnote', 'endnote', 'body_url', 'body_parenthetical'
    original_text: str
    note_id: Optional[str] = None  # For footnote/endnote sources
    position: int = 0  # Position in document for ordering
    components: Optional[SourceComponents] = None  # Looked-up data
    parenthetical: str = ""  # Formatted (Author, Year)
    reference_entry: str = ""  # Formatted reference list entry


# =============================================================================
# STYLE CONFIGURATION
# =============================================================================

AUTHOR_DATE_STYLES = {
    'apa', 'apa 7', 'apa7',
    'mla', 'mla 9', 'mla9',
    'chicago author-date', 'chicago-author-date', 'chicago ad',
    'harvard',
    'vancouver',
    'asa',
}

STYLE_REFERENCE_HEADERS = {
    'apa': 'References',
    'mla': 'Works Cited',
    'chicago': 'References',
    'harvard': 'References',
    'vancouver': 'References',
    'asa': 'References',
}


def is_author_date_style(style: str) -> bool:
    """Check if style uses author-date (parenthetical) format."""
    return style.lower().strip() in AUTHOR_DATE_STYLES


def get_reference_header(style: str) -> str:
    """Get the appropriate header for the references section."""
    style_lower = style.lower()
    for key, header in STYLE_REFERENCE_HEADERS.items():
        if key in style_lower:
            return header
    return 'References'


# =============================================================================
# MAIN PROCESSOR CLASS
# =============================================================================

class EndnoteToAuthorDateProcessor:
    """
    Converts documents with footnotes/endnotes to author-date format.
    
    Usage:
        processor = EndnoteToAuthorDateProcessor(docx_bytes, style='apa')
        result_bytes, citations = processor.process()
    """
    
    def __init__(self, docx_bytes: bytes, style: str = 'apa'):
        """
        Initialize processor.
        
        Args:
            docx_bytes: Raw bytes of input .docx file
            style: Citation style (apa, mla, chicago author-date, etc.)
        """
        self.docx_bytes = docx_bytes
        self.style = style
        self.temp_dir = tempfile.mkdtemp()
        
        # Parsed XML trees
        self.document_xml = None
        self.footnotes_xml = None
        self.endnotes_xml = None
        
        # Extracted data
        self.note_references: List[NoteReference] = []
        self.note_contents: Dict[str, NoteContent] = {}  # note_id -> content
        self.citations: List[CitationMatch] = []
        
        # Processing state
        self.components_map: Dict[str, SourceComponents] = {}  # original_text -> components
    
    def process(self) -> Tuple[bytes, List[CitationMatch]]:
        """
        Main processing pipeline.
        
        Returns:
            Tuple of (transformed document bytes, list of processed citations)
        """
        try:
            # Step 1: Extract docx
            self._extract_docx()
            
            # Step 2: Parse XML files
            self._parse_xml_files()
            
            # Step 3: Find all note references in body
            self._find_note_references()
            
            # Step 4: Read note contents
            self._read_note_contents()
            
            # Step 5: Extract citations from body text (URLs, parentheticals)
            self._extract_body_citations()
            
            # Step 6: Look up metadata for all citations
            self._lookup_all_citations()
            
            # Step 7: Transform document
            self._transform_document()
            
            # Step 8: Repackage and return
            result_bytes = self._repackage_docx()
            
            return result_bytes, self.citations
            
        finally:
            self.cleanup()
    
    def has_notes(self) -> bool:
        """Check if document has footnotes or endnotes."""
        try:
            self._extract_docx()
            self._parse_xml_files()
            return self.footnotes_xml is not None or self.endnotes_xml is not None
        except:
            return False
        finally:
            self.cleanup()
    
    # =========================================================================
    # EXTRACTION METHODS
    # =========================================================================
    
    def _extract_docx(self):
        """Extract docx zip archive to temp directory."""
        with zipfile.ZipFile(BytesIO(self.docx_bytes), 'r') as zf:
            zf.extractall(self.temp_dir)
    
    def _parse_xml_files(self):
        """Parse document.xml, footnotes.xml, and endnotes.xml."""
        doc_path = os.path.join(self.temp_dir, 'word', 'document.xml')
        footnotes_path = os.path.join(self.temp_dir, 'word', 'footnotes.xml')
        endnotes_path = os.path.join(self.temp_dir, 'word', 'endnotes.xml')
        
        if os.path.exists(doc_path):
            self.document_xml = ET.parse(doc_path)
        else:
            raise ValueError("No document.xml found in docx file")
        
        if os.path.exists(footnotes_path):
            self.footnotes_xml = ET.parse(footnotes_path)
        
        if os.path.exists(endnotes_path):
            self.endnotes_xml = ET.parse(endnotes_path)
    
    def _find_note_references(self):
        """Find all footnote/endnote references in document body."""
        root = self.document_xml.getroot()
        body = root.find('.//w:body', NAMESPACES)
        
        if body is None:
            return
        
        position = 0
        paragraphs = body.findall('.//w:p', NAMESPACES)
        
        for para_idx, para in enumerate(paragraphs):
            runs = para.findall('.//w:r', NAMESPACES)
            
            for run in runs:
                # Check for footnote reference
                footnote_ref = run.find('.//w:footnoteReference', NAMESPACES)
                if footnote_ref is not None:
                    note_id = footnote_ref.get(f'{{{NAMESPACES["w"]}}}id')
                    if note_id and note_id not in ('0', '-1'):  # Skip separator/continuation
                        self.note_references.append(NoteReference(
                            note_id=note_id,
                            note_type='footnote',
                            paragraph_index=para_idx,
                            run_element=run,
                            paragraph_element=para,
                            position_in_body=position
                        ))
                
                # Check for endnote reference
                endnote_ref = run.find('.//w:endnoteReference', NAMESPACES)
                if endnote_ref is not None:
                    note_id = endnote_ref.get(f'{{{NAMESPACES["w"]}}}id')
                    if note_id and note_id not in ('0', '-1'):
                        self.note_references.append(NoteReference(
                            note_id=note_id,
                            note_type='endnote',
                            paragraph_index=para_idx,
                            run_element=run,
                            paragraph_element=para,
                            position_in_body=position
                        ))
                
                # Track position (approximate by counting text elements)
                for text_elem in run.findall('.//w:t', NAMESPACES):
                    if text_elem.text:
                        position += len(text_elem.text)
        
        print(f"[EndnoteToAuthorDate] Found {len(self.note_references)} note references")
    
    def _read_note_contents(self):
        """Read content from footnotes and endnotes."""
        # Read footnotes
        if self.footnotes_xml is not None:
            root = self.footnotes_xml.getroot()
            for note in root.findall('.//w:footnote', NAMESPACES):
                note_id = note.get(f'{{{NAMESPACES["w"]}}}id')
                if note_id and note_id not in ('0', '-1'):
                    text = self._extract_text_from_element(note)
                    self.note_contents[f'fn_{note_id}'] = NoteContent(
                        note_id=note_id,
                        note_type='footnote',
                        text=text,
                        xml_element=note
                    )
        
        # Read endnotes
        if self.endnotes_xml is not None:
            root = self.endnotes_xml.getroot()
            for note in root.findall('.//w:endnote', NAMESPACES):
                note_id = note.get(f'{{{NAMESPACES["w"]}}}id')
                if note_id and note_id not in ('0', '-1'):
                    text = self._extract_text_from_element(note)
                    self.note_contents[f'en_{note_id}'] = NoteContent(
                        note_id=note_id,
                        note_type='endnote',
                        text=text,
                        xml_element=note
                    )
        
        print(f"[EndnoteToAuthorDate] Read {len(self.note_contents)} note contents")
        
        # Create citation entries for each note
        for ref in self.note_references:
            key = f"{'fn' if ref.note_type == 'footnote' else 'en'}_{ref.note_id}"
            if key in self.note_contents:
                content = self.note_contents[key]
                self.citations.append(CitationMatch(
                    source=ref.note_type,
                    original_text=content.text,
                    note_id=ref.note_id,
                    position=ref.position_in_body
                ))
    
    def _extract_text_from_element(self, element: ET.Element) -> str:
        """Extract plain text from an XML element."""
        texts = []
        for text_elem in element.iter(f'{{{NAMESPACES["w"]}}}t'):
            if text_elem.text:
                texts.append(text_elem.text)
        return ' '.join(texts).strip()
    
    def _extract_body_citations(self):
        """Extract URLs and (Author, Year) patterns from body text."""
        # Get body text
        root = self.document_xml.getroot()
        body = root.find('.//w:body', NAMESPACES)
        if body is None:
            return
        
        body_text = self._extract_text_from_element(body)
        
        # Extract URLs
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        for match in re.finditer(url_pattern, body_text):
            self.citations.append(CitationMatch(
                source='body_url',
                original_text=match.group(),
                position=match.start()
            ))
        
        # Extract (Author, Year) patterns - these need verification, not replacement
        # Pattern: (Name, YYYY) or (Name & Name, YYYY) or (Name et al., YYYY)
        parenthetical_pattern = r'\([A-Z][a-z]+(?:\s+(?:&|and)\s+[A-Z][a-z]+)?(?:\s+et\s+al\.?)?,\s*\d{4}[a-z]?\)'
        for match in re.finditer(parenthetical_pattern, body_text):
            self.citations.append(CitationMatch(
                source='body_parenthetical',
                original_text=match.group(),
                position=match.start()
            ))
        
        print(f"[EndnoteToAuthorDate] Found {len([c for c in self.citations if c.source.startswith('body_')])} body citations")
    
    # =========================================================================
    # METADATA LOOKUP
    # =========================================================================
    
    def _lookup_all_citations(self):
        """Look up metadata for all citations using unified router."""
        from unified_router import get_citation
        
        def lookup_single(citation: CitationMatch) -> CitationMatch:
            """Look up a single citation."""
            try:
                components, formatted = get_citation(citation.original_text, self.style)
                if components and components.has_minimum_data():
                    citation.components = components
                    citation.parenthetical = self._format_parenthetical(components)
                    citation.reference_entry = formatted
            except Exception as e:
                print(f"[EndnoteToAuthorDate] Lookup failed for '{citation.original_text[:50]}': {e}")
            return citation
        
        # Process in parallel for speed
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(lookup_single, c): c for c in self.citations}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"[EndnoteToAuthorDate] Error in parallel lookup: {e}")
        
        # Build components map for deduplication
        for citation in self.citations:
            if citation.components:
                self.components_map[citation.original_text] = citation.components
        
        successful = len([c for c in self.citations if c.components is not None])
        print(f"[EndnoteToAuthorDate] Looked up {successful}/{len(self.citations)} citations successfully")
    
    def _format_parenthetical(self, components: SourceComponents) -> str:
        """Format components as (Author, Year) parenthetical citation."""
        # Get author text
        if components.authors:
            if len(components.authors) == 1:
                author_text = self._get_last_name(components.authors[0])
            elif len(components.authors) == 2:
                author_text = f"{self._get_last_name(components.authors[0])} & {self._get_last_name(components.authors[1])}"
            else:
                author_text = f"{self._get_last_name(components.authors[0])} et al."
        elif components.authors_parsed:
            # Use parsed author data if available
            parsed = components.authors_parsed
            if len(parsed) == 1:
                author_text = parsed[0].get('family', 'Unknown')
            elif len(parsed) == 2:
                author_text = f"{parsed[0].get('family', '')} & {parsed[1].get('family', '')}"
            else:
                author_text = f"{parsed[0].get('family', '')} et al."
        elif components.case_name:
            # Legal citation
            author_text = self._get_short_case_name(components.case_name)
        else:
            # Fallback to title
            author_text = self._get_short_title(components.title)
        
        year = components.year or 'n.d.'
        
        # Style-specific formatting
        style_lower = self.style.lower()
        if 'mla' in style_lower:
            # MLA uses author only in parenthetical (page numbers added separately)
            return f"({author_text})"
        else:
            # APA, Chicago Author-Date, etc.
            return f"({author_text}, {year})"
    
    def _get_last_name(self, author: str) -> str:
        """Extract last name from author string."""
        if not author:
            return ""
        author = author.strip()
        if ',' in author:
            return author.split(',')[0].strip()
        parts = author.split()
        return parts[-1] if parts else author
    
    def _get_short_case_name(self, case_name: str) -> str:
        """Get shortened case name."""
        if not case_name:
            return ""
        parts = re.split(r'\s+v\.?\s+', case_name, flags=re.IGNORECASE)
        return parts[0].strip() if parts else case_name
    
    def _get_short_title(self, title: str) -> str:
        """Get shortened title for parenthetical."""
        if not title:
            return "Untitled"
        words = title.split()[:3]
        short = ' '.join(words)
        if len(title.split()) > 3:
            short += '...'
        return short
    
    # =========================================================================
    # DOCUMENT TRANSFORMATION
    # =========================================================================
    
    def _transform_document(self):
        """Apply all transformations to the document."""
        # Step 1: Remove superscripts and insert parentheticals
        self._replace_note_references()
        
        # Step 2: Remove footnotes/endnotes sections
        self._remove_notes_sections()
        
        # Step 3: Append References section
        self._append_references_section()
        
        # Step 4: Save modified XML
        self._save_xml_files()
    
    def _replace_note_references(self):
        """Remove superscript references and insert (Author, Year) citations."""
        # Build lookup: note_id -> parenthetical
        note_parentheticals = {}
        for citation in self.citations:
            if citation.note_id and citation.parenthetical:
                note_parentheticals[citation.note_id] = citation.parenthetical
        
        # Process each reference
        for ref in self.note_references:
            parenthetical = note_parentheticals.get(ref.note_id, '')
            
            if parenthetical:
                # Insert parenthetical text before removing the reference
                self._insert_text_in_run(ref.run_element, parenthetical)
            
            # Remove the footnote/endnote reference element
            self._remove_note_reference(ref)
        
        print(f"[EndnoteToAuthorDate] Replaced {len(self.note_references)} note references with parentheticals")
    
    def _insert_text_in_run(self, run: ET.Element, text: str):
        """Insert text into a run element."""
        w = NAMESPACES['w']
        
        # Create text element
        text_elem = ET.Element(f'{{{w}}}t')
        text_elem.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        text_elem.text = f" {text}"  # Add space before parenthetical
        
        # Insert at beginning of run (before the reference)
        run.insert(0, text_elem)
    
    def _remove_note_reference(self, ref: NoteReference):
        """Remove footnote/endnote reference element from run."""
        w = NAMESPACES['w']
        
        if ref.note_type == 'footnote':
            tag = f'{{{w}}}footnoteReference'
        else:
            tag = f'{{{w}}}endnoteReference'
        
        # Find and remove the reference element
        for elem in list(ref.run_element):
            if elem.tag == tag:
                ref.run_element.remove(elem)
    
    def _remove_notes_sections(self):
        """Clear content from footnotes.xml and endnotes.xml."""
        w = NAMESPACES['w']
        
        # Clear footnotes (keep separator notes 0 and -1)
        if self.footnotes_xml is not None:
            root = self.footnotes_xml.getroot()
            for note in list(root.findall(f'.//{{{w}}}footnote', NAMESPACES)):
                note_id = note.get(f'{{{w}}}id')
                if note_id not in ('0', '-1'):
                    # Clear content but keep element (Word needs it)
                    for child in list(note):
                        note.remove(child)
        
        # Clear endnotes
        if self.endnotes_xml is not None:
            root = self.endnotes_xml.getroot()
            for note in list(root.findall(f'.//{{{w}}}endnote', NAMESPACES)):
                note_id = note.get(f'{{{w}}}id')
                if note_id not in ('0', '-1'):
                    for child in list(note):
                        note.remove(child)
        
        print("[EndnoteToAuthorDate] Cleared footnotes/endnotes sections")
    
    def _append_references_section(self):
        """Append alphabetized References section to document."""
        # Collect all unique references
        references = []
        seen_keys = set()
        
        for citation in self.citations:
            if citation.components and citation.reference_entry:
                key = self._get_dedup_key(citation.components)
                if key not in seen_keys:
                    seen_keys.add(key)
                    references.append((citation.components, citation.reference_entry))
        
        if not references:
            print("[EndnoteToAuthorDate] No references to append")
            return
        
        # Sort alphabetically by author last name
        references.sort(key=lambda x: self._get_sort_key(x[0]))
        
        # Build References section XML
        root = self.document_xml.getroot()
        body = root.find('.//w:body', NAMESPACES)
        
        if body is None:
            return
        
        w = NAMESPACES['w']
        
        # Add page break before References
        page_break_para = ET.Element(f'{{{w}}}p')
        page_break_run = ET.SubElement(page_break_para, f'{{{w}}}r')
        br = ET.SubElement(page_break_run, f'{{{w}}}br')
        br.set(f'{{{w}}}type', 'page')
        body.append(page_break_para)
        
        # Add "References" header
        header = get_reference_header(self.style)
        header_para = ET.Element(f'{{{w}}}p')
        header_pPr = ET.SubElement(header_para, f'{{{w}}}pPr')
        header_jc = ET.SubElement(header_pPr, f'{{{w}}}jc')
        header_jc.set(f'{{{w}}}val', 'center')
        header_run = ET.SubElement(header_para, f'{{{w}}}r')
        header_rPr = ET.SubElement(header_run, f'{{{w}}}rPr')
        ET.SubElement(header_rPr, f'{{{w}}}b')  # Bold
        header_text = ET.SubElement(header_run, f'{{{w}}}t')
        header_text.text = header
        body.append(header_para)
        
        # Add blank line
        blank_para = ET.Element(f'{{{w}}}p')
        body.append(blank_para)
        
        # Add each reference entry
        for components, entry in references:
            entry_para = ET.Element(f'{{{w}}}p')
            
            # Hanging indent for APA/MLA style
            entry_pPr = ET.SubElement(entry_para, f'{{{w}}}pPr')
            entry_ind = ET.SubElement(entry_pPr, f'{{{w}}}ind')
            entry_ind.set(f'{{{w}}}left', '720')  # 0.5 inch
            entry_ind.set(f'{{{w}}}hanging', '720')  # Hanging indent
            
            entry_run = ET.SubElement(entry_para, f'{{{w}}}r')
            entry_text = ET.SubElement(entry_run, f'{{{w}}}t')
            entry_text.text = self._strip_html(entry)
            
            body.append(entry_para)
        
        print(f"[EndnoteToAuthorDate] Appended References section with {len(references)} entries")
    
    def _get_dedup_key(self, components: SourceComponents) -> str:
        """Generate unique key for deduplication."""
        if components.doi:
            return f"doi:{components.doi.lower()}"
        if components.isbn:
            return f"isbn:{components.isbn}"
        if components.url:
            return f"url:{components.url.lower()}"
        # Fallback to title + first author
        key = (components.title or '').lower()[:50]
        if components.authors:
            key += f":{components.authors[0].lower()}"
        return key
    
    def _get_sort_key(self, components: SourceComponents) -> str:
        """Generate sort key for alphabetizing references."""
        author_key = ""
        if components.authors:
            author_key = self._get_last_name(components.authors[0]).lower()
        elif components.authors_parsed:
            author_key = components.authors_parsed[0].get('family', '').lower()
        elif components.case_name:
            author_key = self._get_short_case_name(components.case_name).lower()
        elif components.title:
            # Skip articles for sorting
            title = components.title.lower()
            for article in ['the ', 'a ', 'an ']:
                if title.startswith(article):
                    title = title[len(article):]
                    break
            author_key = title
        
        year_key = components.year or '9999'
        title_key = (components.title or '').lower()[:50]
        
        return f"{author_key}|{year_key}|{title_key}"
    
    def _strip_html(self, text: str) -> str:
        """Remove HTML tags from formatted citation."""
        # Remove <i>...</i> and <b>...</b> tags
        text = re.sub(r'</?[ib]>', '', text)
        return text
    
    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================
    
    def _save_xml_files(self):
        """Save modified XML files back to temp directory."""
        doc_path = os.path.join(self.temp_dir, 'word', 'document.xml')
        self.document_xml.write(doc_path, encoding='UTF-8', xml_declaration=True)
        
        if self.footnotes_xml:
            footnotes_path = os.path.join(self.temp_dir, 'word', 'footnotes.xml')
            self.footnotes_xml.write(footnotes_path, encoding='UTF-8', xml_declaration=True)
        
        if self.endnotes_xml:
            endnotes_path = os.path.join(self.temp_dir, 'word', 'endnotes.xml')
            self.endnotes_xml.write(endnotes_path, encoding='UTF-8', xml_declaration=True)
    
    def _repackage_docx(self) -> bytes:
        """Repackage temp directory as docx file."""
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, self.temp_dir)
                    zf.write(file_path, arcname)
        buffer.seek(0)
        return buffer.read()
    
    def cleanup(self):
        """Remove temporary files."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def process_endnotes_to_author_date(
    docx_bytes: bytes,
    style: str = 'apa'
) -> Tuple[bytes, List[CitationMatch]]:
    """
    Convenience function to process a document.
    
    Args:
        docx_bytes: Raw bytes of input .docx file
        style: Citation style (apa, mla, chicago author-date, etc.)
        
    Returns:
        Tuple of (transformed document bytes, list of processed citations)
    """
    processor = EndnoteToAuthorDateProcessor(docx_bytes, style=style)
    return processor.process()


def document_has_notes(docx_bytes: bytes) -> bool:
    """
    Check if a document has footnotes or endnotes.
    
    Args:
        docx_bytes: Raw bytes of .docx file
        
    Returns:
        True if document has footnotes or endnotes
    """
    try:
        with zipfile.ZipFile(BytesIO(docx_bytes), 'r') as zf:
            names = zf.namelist()
            return 'word/footnotes.xml' in names or 'word/endnotes.xml' in names
    except:
        return False


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    print("EndnoteToAuthorDate Processor")
    print("=" * 50)
    print("This module converts documents with footnotes/endnotes")
    print("to author-date format (APA, MLA, etc.)")
    print()
    print("Usage:")
    print("  from processors.endnote_to_author_date import process_endnotes_to_author_date")
    print("  result_bytes, citations = process_endnotes_to_author_date(docx_bytes, style='apa')")
