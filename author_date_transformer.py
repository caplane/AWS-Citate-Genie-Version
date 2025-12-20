"""
citeflex/author_date_transformer.py

Transforms footnote/endnote documents to author-date format.

This module handles the conversion for APA, MLA, ASA, and other author-date styles:
1. Extracts footnotes/endnotes from document
2. Removes superscript references from document body
3. Inserts parenthetical citations at superscript locations
4. Appends alphabetized References section at end of document

Adapted from Incipit Genie's superscript removal pattern.

Nomenclature:
    - Raw citation: The text in footnote/endnote before lookup
    - Citation components: Looked-up data (author, title, year, etc.)
    - Parenthetical: The in-text citation "(Smith, 2020)"
    - Reference entry: The full citation in References section

Architecture:
    Input:  Word document with footnotes/endnotes
    Output: Word document with parentheticals + References section
    
    The footnotes/endnotes section is cleared after transformation.

XML Manipulation:
    - Uses direct XML manipulation for precise control
    - Preserves all document formatting and namespaces
    - Handles both endnotes.xml and footnotes.xml

Version History:
    2025-12-20 V1.0: Initial implementation from Incipit Genie pattern
"""

import os
import re
import copy
import zipfile
import tempfile
import shutil
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field


# =============================================================================
# XML NAMESPACES (from Incipit Genie)
# =============================================================================

NAMESPACES = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}

# Register all common Word namespaces to preserve prefixes
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

# Register namespaces before any parsing
for prefix, uri in ALL_NAMESPACES.items():
    ET.register_namespace(prefix, uri)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class NoteReference:
    """
    A footnote/endnote reference found in the document body.
    
    Captures the location and context needed to:
    1. Remove the superscript reference
    2. Insert the parenthetical citation
    """
    note_id: str
    note_type: str  # 'endnote' or 'footnote'
    paragraph_index: int
    run_index: int
    raw_text: str = ""  # Original note content


@dataclass
class ResolvedNote:
    """
    A note with its looked-up citation components and formatted outputs.
    """
    reference: NoteReference
    components: Optional[Any] = None  # SourceComponents
    parenthetical: str = ""  # e.g., "(Smith, 2020)"
    reference_entry: str = ""  # Full reference for References section
    success: bool = False
    sort_key: str = ""  # For alphabetizing References


# =============================================================================
# AUTHOR-DATE TRANSFORMER
# =============================================================================

class AuthorDateTransformer:
    """
    Transforms a Word document from footnote/endnote format to author-date format.
    
    Process:
    1. Extract document as zip, parse XML
    2. Find all endnote/footnote references in body
    3. For each reference:
       - Remove the superscript from body
       - Insert parenthetical citation text
    4. Clear endnotes/footnotes section
    5. Append References section at end of document
    6. Repackage as docx
    
    Usage:
        transformer = AuthorDateTransformer(docx_bytes)
        result_bytes = transformer.transform(resolved_notes)
    """
    
    def __init__(self, docx_bytes: bytes):
        """
        Initialize with the bytes of a .docx file.
        
        Args:
            docx_bytes: The raw bytes of the input .docx file
        """
        self.docx_bytes = docx_bytes
        self.temp_dir = tempfile.mkdtemp()
        self.document_xml = None
        self.endnotes_xml = None
        self.footnotes_xml = None
        self.references: List[NoteReference] = []
    
    def transform(
        self,
        resolved_notes: Dict[str, ResolvedNote],
        references_heading: str = "References"
    ) -> bytes:
        """
        Transform the document to author-date format.
        
        Args:
            resolved_notes: Dict mapping note_id to ResolvedNote with 
                           parenthetical and reference_entry
            references_heading: Title for References section (default: "References")
        
        Returns:
            Bytes of the transformed .docx file
        """
        try:
            # Step 1: Extract the docx
            self._extract_docx()
            
            # Step 2: Parse XML files
            self._parse_xml_files()
            
            # Step 3: Find all note references in body
            self._find_note_references()
            
            # Step 4: Transform body - remove superscripts, insert parentheticals
            self._transform_body(resolved_notes)
            
            # Step 5: Clear endnotes/footnotes
            self._clear_notes()
            
            # Step 6: Append References section
            self._append_references_section(resolved_notes, references_heading)
            
            # Step 7: Save and repackage
            self._save_xml_files()
            return self._repackage_docx()
            
        finally:
            self.cleanup()
    
    def extract_note_texts(self) -> Dict[str, str]:
        """
        Extract the text content of all notes without transforming.
        
        Used for the lookup phase before transformation.
        
        Returns:
            Dict mapping note_id to note text content
        """
        try:
            self._extract_docx()
            self._parse_xml_files()
            
            note_texts = {}
            
            # Extract endnote texts
            if self.endnotes_xml is not None:
                root = self.endnotes_xml.getroot()
                for endnote in root.findall('.//w:endnote', NAMESPACES):
                    note_id = endnote.get(f'{{{NAMESPACES["w"]}}}id')
                    if note_id and note_id not in ['0', '-1']:
                        text = self._extract_note_content(endnote)
                        note_texts[f"endnote_{note_id}"] = text
            
            # Extract footnote texts
            if self.footnotes_xml is not None:
                root = self.footnotes_xml.getroot()
                for footnote in root.findall('.//w:footnote', NAMESPACES):
                    note_id = footnote.get(f'{{{NAMESPACES["w"]}}}id')
                    if note_id and note_id not in ['0', '-1']:
                        text = self._extract_note_content(footnote)
                        note_texts[f"footnote_{note_id}"] = text
            
            return note_texts
            
        finally:
            self.cleanup()
    
    # =========================================================================
    # EXTRACTION METHODS
    # =========================================================================
    
    def _extract_docx(self):
        """Extract the docx zip archive to temp directory."""
        with zipfile.ZipFile(BytesIO(self.docx_bytes), 'r') as zf:
            zf.extractall(self.temp_dir)
    
    def _parse_xml_files(self):
        """Parse the main XML files."""
        doc_path = os.path.join(self.temp_dir, 'word', 'document.xml')
        endnotes_path = os.path.join(self.temp_dir, 'word', 'endnotes.xml')
        footnotes_path = os.path.join(self.temp_dir, 'word', 'footnotes.xml')
        
        if os.path.exists(doc_path):
            self.document_xml = ET.parse(doc_path)
        else:
            raise ValueError("No document.xml found in docx file")
        
        if os.path.exists(endnotes_path):
            self.endnotes_xml = ET.parse(endnotes_path)
        
        if os.path.exists(footnotes_path):
            self.footnotes_xml = ET.parse(footnotes_path)
    
    def _find_note_references(self):
        """Find all endnote and footnote references in the document body."""
        root = self.document_xml.getroot()
        body = root.find('.//w:body', NAMESPACES)
        
        if body is None:
            return
        
        paragraphs = body.findall('.//w:p', NAMESPACES)
        
        for para_idx, para in enumerate(paragraphs):
            runs = para.findall('.//w:r', NAMESPACES)
            
            for run_idx, run in enumerate(runs):
                # Check for endnote reference
                endnote_ref = run.find('.//w:endnoteReference', NAMESPACES)
                if endnote_ref is not None:
                    note_id = endnote_ref.get(f'{{{NAMESPACES["w"]}}}id')
                    if note_id and note_id not in ['0', '-1']:
                        self.references.append(NoteReference(
                            note_id=note_id,
                            note_type='endnote',
                            paragraph_index=para_idx,
                            run_index=run_idx
                        ))
                
                # Check for footnote reference
                footnote_ref = run.find('.//w:footnoteReference', NAMESPACES)
                if footnote_ref is not None:
                    note_id = footnote_ref.get(f'{{{NAMESPACES["w"]}}}id')
                    if note_id and note_id not in ['0', '-1']:
                        self.references.append(NoteReference(
                            note_id=note_id,
                            note_type='footnote',
                            paragraph_index=para_idx,
                            run_index=run_idx
                        ))
    
    def _extract_note_content(self, note_elem: ET.Element) -> str:
        """Extract text content from a note element."""
        content = ""
        for para in note_elem.findall('.//w:p', NAMESPACES):
            para_text = ""
            for run in para.findall('.//w:r', NAMESPACES):
                # Skip runs that contain the note reference marker
                if run.find('.//w:endnoteRef', NAMESPACES) is not None:
                    continue
                if run.find('.//w:footnoteRef', NAMESPACES) is not None:
                    continue
                
                for t_elem in run.findall('.//w:t', NAMESPACES):
                    if t_elem.text:
                        para_text += t_elem.text
            
            content += para_text.strip() + " "
        
        return content.strip()
    
    # =========================================================================
    # TRANSFORMATION METHODS
    # =========================================================================
    
    def _transform_body(self, resolved_notes: Dict[str, ResolvedNote]):
        """
        Transform document body: remove superscripts, insert parentheticals.
        
        Process in reverse order to maintain paragraph/run indices.
        """
        root = self.document_xml.getroot()
        body = root.find('.//w:body', NAMESPACES)
        paragraphs = body.findall('.//w:p', NAMESPACES)
        
        # Process in reverse order to maintain indices
        for ref in reversed(self.references):
            para = paragraphs[ref.paragraph_index]
            runs = para.findall('.//w:r', NAMESPACES)
            
            if ref.run_index >= len(runs):
                continue
            
            run = runs[ref.run_index]
            
            # Get the resolved note
            note_key = f"{ref.note_type}_{ref.note_id}"
            resolved = resolved_notes.get(note_key)
            
            if resolved and resolved.parenthetical:
                # Replace superscript with parenthetical
                self._replace_reference_with_parenthetical(
                    para, run, ref, resolved.parenthetical
                )
            else:
                # Just remove the superscript if no parenthetical available
                self._remove_reference(run, ref.note_type)
    
    def _replace_reference_with_parenthetical(
        self,
        para: ET.Element,
        run: ET.Element,
        ref: NoteReference,
        parenthetical: str
    ):
        """
        Replace a note reference (superscript) with parenthetical citation text.
        
        Example: "text¹ continues" -> "text (Smith, 2020) continues"
        """
        w = NAMESPACES['w']
        
        # Find the run's position in paragraph
        run_index = None
        for i, child in enumerate(para):
            if child == run:
                run_index = i
                break
        
        if run_index is None:
            return
        
        # Remove the note reference element from the run
        self._remove_reference(run, ref.note_type)
        
        # Check if run is now empty
        has_text = run.find('.//w:t', NAMESPACES) is not None
        
        if not has_text:
            # Run is empty, replace it with parenthetical text
            new_run = self._create_text_run(parenthetical)
            para.remove(run)
            para.insert(run_index, new_run)
        else:
            # Run still has text, insert parenthetical after it
            new_run = self._create_text_run(parenthetical)
            para.insert(run_index + 1, new_run)
    
    def _remove_reference(self, run: ET.Element, note_type: str):
        """Remove the note reference element from a run."""
        if note_type == 'endnote':
            ref_tag = 'endnoteReference'
        else:
            ref_tag = 'footnoteReference'
        
        for elem in run.findall(f'.//w:{ref_tag}', NAMESPACES):
            parent = self._find_parent(run, elem)
            if parent is not None:
                parent.remove(elem)
    
    def _create_text_run(self, text: str) -> ET.Element:
        """Create a Word XML run element with text content."""
        w = NAMESPACES['w']
        
        run = ET.Element(f'{{{w}}}r')
        t_elem = ET.SubElement(run, f'{{{w}}}t')
        t_elem.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        t_elem.text = text
        
        return run
    
    def _find_parent(self, root: ET.Element, target: ET.Element) -> Optional[ET.Element]:
        """Find the parent of a target element."""
        for parent in root.iter():
            for child in parent:
                if child == target:
                    return parent
        return None
    
    # =========================================================================
    # NOTES CLEARING
    # =========================================================================
    
    def _clear_notes(self):
        """Clear endnotes and footnotes, keeping only separator entries."""
        # Clear endnotes
        if self.endnotes_xml is not None:
            root = self.endnotes_xml.getroot()
            for endnote in list(root.findall('w:endnote', NAMESPACES)):
                note_id = endnote.get(f'{{{NAMESPACES["w"]}}}id')
                if note_id not in ['-1', '0']:
                    root.remove(endnote)
        
        # Clear footnotes
        if self.footnotes_xml is not None:
            root = self.footnotes_xml.getroot()
            for footnote in list(root.findall('w:footnote', NAMESPACES)):
                note_id = footnote.get(f'{{{NAMESPACES["w"]}}}id')
                if note_id not in ['-1', '0']:
                    root.remove(footnote)
    
    # =========================================================================
    # REFERENCES SECTION
    # =========================================================================
    
    def _append_references_section(
        self,
        resolved_notes: Dict[str, ResolvedNote],
        heading: str
    ):
        """
        Append alphabetized References section at end of document.
        
        Structure:
            [Page Break]
            References (Heading 1)
            
            Author, A. (2020). Title. Journal...
            Author, B. (2019). Another title...
        """
        root = self.document_xml.getroot()
        body = root.find('.//w:body', NAMESPACES)
        
        # Find sectPr (section properties) - insert before it
        sectPr = body.find('w:sectPr', NAMESPACES)
        
        # Collect unique references and sort alphabetically
        unique_refs = {}
        for note_key, resolved in resolved_notes.items():
            if resolved.reference_entry and resolved.reference_entry not in unique_refs:
                sort_key = resolved.sort_key or resolved.reference_entry
                unique_refs[resolved.reference_entry] = sort_key
        
        # Sort by sort_key (typically author last name)
        sorted_refs = sorted(unique_refs.keys(), key=lambda x: unique_refs[x].lower())
        
        if not sorted_refs:
            return  # No references to add
        
        # Create elements to insert
        elements = []
        
        # Page break
        elements.append(self._create_page_break())
        
        # Heading
        elements.append(self._create_heading(heading))
        
        # Empty paragraph for spacing
        elements.append(self._create_empty_paragraph())
        
        # Reference entries
        for ref_entry in sorted_refs:
            elements.append(self._create_reference_paragraph(ref_entry))
        
        # Insert elements
        if sectPr is not None:
            insert_idx = list(body).index(sectPr)
            for i, elem in enumerate(elements):
                body.insert(insert_idx + i, elem)
        else:
            for elem in elements:
                body.append(elem)
    
    def _create_page_break(self) -> ET.Element:
        """Create a page break paragraph."""
        w = NAMESPACES['w']
        para = ET.Element(f'{{{w}}}p')
        run = ET.SubElement(para, f'{{{w}}}r')
        br = ET.SubElement(run, f'{{{w}}}br')
        br.set(f'{{{w}}}type', 'page')
        return para
    
    def _create_heading(self, text: str) -> ET.Element:
        """Create a Heading 1 paragraph."""
        w = NAMESPACES['w']
        
        para = ET.Element(f'{{{w}}}p')
        
        # Paragraph properties for Heading 1
        pPr = ET.SubElement(para, f'{{{w}}}pPr')
        pStyle = ET.SubElement(pPr, f'{{{w}}}pStyle')
        pStyle.set(f'{{{w}}}val', 'Heading1')
        
        # The heading text
        run = ET.SubElement(para, f'{{{w}}}r')
        t = ET.SubElement(run, f'{{{w}}}t')
        t.text = text
        
        return para
    
    def _create_empty_paragraph(self) -> ET.Element:
        """Create an empty paragraph for spacing."""
        w = NAMESPACES['w']
        return ET.Element(f'{{{w}}}p')
    
    def _create_reference_paragraph(self, text: str) -> ET.Element:
        """
        Create a paragraph for a reference entry.
        
        Uses hanging indent formatting typical of reference lists.
        """
        w = NAMESPACES['w']
        
        para = ET.Element(f'{{{w}}}p')
        
        # Paragraph properties with hanging indent
        pPr = ET.SubElement(para, f'{{{w}}}pPr')
        
        # Hanging indent: first line at 0, rest at 720 twips (0.5 inch)
        ind = ET.SubElement(pPr, f'{{{w}}}ind')
        ind.set(f'{{{w}}}left', '720')
        ind.set(f'{{{w}}}hanging', '720')
        
        # Create runs for the text, handling italic markers
        self._add_formatted_text(para, text)
        
        return para
    
    def _add_formatted_text(self, para: ET.Element, text: str):
        """
        Add text to paragraph, handling <i>italic</i> markers.
        """
        w = NAMESPACES['w']
        
        # Split by italic tags
        parts = re.split(r'(<i>.*?</i>)', text)
        
        for part in parts:
            if not part:
                continue
            
            run = ET.SubElement(para, f'{{{w}}}r')
            
            if part.startswith('<i>') and part.endswith('</i>'):
                # Italic text
                inner = part[3:-4]
                rPr = ET.SubElement(run, f'{{{w}}}rPr')
                ET.SubElement(rPr, f'{{{w}}}i')
                t = ET.SubElement(run, f'{{{w}}}t')
                t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                t.text = inner
            else:
                # Normal text
                t = ET.SubElement(run, f'{{{w}}}t')
                t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                t.text = part
    
    # =========================================================================
    # SAVE AND CLEANUP
    # =========================================================================
    
    def _save_xml_files(self):
        """Save modified XML files back to temp directory."""
        doc_path = os.path.join(self.temp_dir, 'word', 'document.xml')
        endnotes_path = os.path.join(self.temp_dir, 'word', 'endnotes.xml')
        footnotes_path = os.path.join(self.temp_dir, 'word', 'footnotes.xml')
        
        self.document_xml.write(doc_path, encoding='UTF-8', xml_declaration=True)
        
        if self.endnotes_xml:
            self.endnotes_xml.write(endnotes_path, encoding='UTF-8', xml_declaration=True)
        
        if self.footnotes_xml:
            self.footnotes_xml.write(footnotes_path, encoding='UTF-8', xml_declaration=True)
    
    def _repackage_docx(self) -> bytes:
        """Repackage the temp directory as a docx file."""
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
# HELPER FUNCTIONS
# =============================================================================

def build_parenthetical(
    components: Any,  # SourceComponents
    style: str = "apa"
) -> str:
    """
    Build parenthetical citation from citation components.
    
    Examples:
        APA: (Smith, 2020)
        APA 2 authors: (Smith & Jones, 2020)
        APA 3+ authors: (Smith et al., 2020)
        MLA: (Smith 45)
    
    Args:
        components: SourceComponents with authors and year
        style: Citation style (apa, mla, etc.)
        
    Returns:
        Parenthetical string like "(Smith, 2020)"
    """
    if not components:
        return ""
    
    # Get authors
    authors_parsed = getattr(components, 'authors_parsed', [])
    authors = getattr(components, 'authors', [])
    year = getattr(components, 'year', '') or 'n.d.'
    
    # Helper to get family name
    def get_family(author):
        if isinstance(author, dict):
            return author.get('family', 'Unknown')
        elif isinstance(author, str):
            # Try to parse
            parts = author.split()
            return parts[-1] if parts else 'Unknown'
        return 'Unknown'
    
    # Use authors_parsed if available, else parse from authors
    if authors_parsed:
        family_names = [get_family(a) for a in authors_parsed]
    elif authors:
        family_names = [get_family(a) for a in authors]
    else:
        # No authors - use title
        title = getattr(components, 'title', 'Unknown')
        title_short = (title[:30] + '...') if len(title) > 33 else title
        return f"({title_short}, {year})"
    
    style_lower = style.lower()
    
    if 'mla' in style_lower:
        # MLA: (Author Page) - no comma before page
        if len(family_names) >= 3:
            return f"({family_names[0]} et al.)"
        elif len(family_names) == 2:
            return f"({family_names[0]} and {family_names[1]})"
        else:
            return f"({family_names[0]})"
    else:
        # APA/ASA/Chicago Author-Date: (Author, Year)
        if len(family_names) >= 3:
            return f"({family_names[0]} et al., {year})"
        elif len(family_names) == 2:
            return f"({family_names[0]} & {family_names[1]}, {year})"
        else:
            return f"({family_names[0]}, {year})"


def build_sort_key(components: Any) -> str:
    """
    Build sort key for alphabetizing References.
    
    Uses author last name, then year, then title.
    """
    if not components:
        return "zzz"  # Sort unknown at end
    
    authors_parsed = getattr(components, 'authors_parsed', [])
    authors = getattr(components, 'authors', [])
    year = getattr(components, 'year', '') or '9999'
    title = getattr(components, 'title', '') or ''
    
    # Get first author family name
    if authors_parsed and len(authors_parsed) > 0:
        first = authors_parsed[0]
        if isinstance(first, dict):
            family = first.get('family', '')
        else:
            family = str(first).split()[-1] if first else ''
    elif authors and len(authors) > 0:
        family = str(authors[0]).split()[-1] if authors[0] else ''
    else:
        family = title[:20] if title else 'zzz'
    
    return f"{family.lower()}_{year}_{title[:20].lower()}"


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def transform_to_author_date(
    docx_bytes: bytes,
    resolved_notes: Dict[str, 'ResolvedNote'],
    references_heading: str = "References"
) -> bytes:
    """
    Convenience function to transform a document to author-date format.
    
    Args:
        docx_bytes: The input document bytes
        resolved_notes: Dict mapping note_id to ResolvedNote
        references_heading: Title for References section
        
    Returns:
        Transformed document bytes
    """
    transformer = AuthorDateTransformer(docx_bytes)
    return transformer.transform(resolved_notes, references_heading)
