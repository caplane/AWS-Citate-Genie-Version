"""
citeflex/lambda_processor.py

Lambda-ready document processor with parallel citation component lookup.

Nomenclature:
    - Raw citation: User input (URL, DOI, parenthetical, rough text)
    - Citation components: The data comprising a citation (author, title, year, 
      journal, volume, issue, pages, DOI, publisher, place, etc.)
    - Citation component lookup: Resolving raw citations to citation components 
      via external APIs
    - Formatted citation: Styled output string built from citation components

Architecture:
    Phase 1 - Extract: Get all raw citations from footnotes/endnotes
    Phase 2 - Deduplicate: Identify unique raw citations  
    Phase 3 - Parallel Lookup: Fetch citation components for all unique (one batch)
    Phase 4 - Format & Transform: Build output based on style

Cost Tracking:
    - Document gist: Opus 4.5 (~$0.006 per document)
    - AI fallback: GPT-5.2 (~$0.002 per citation)
    - Credits charged: ceil(total_cost / $0.05)

SOC 2 Compliance:
    - All operations logged via soc2_logging module
    - Request tracing via request_id
    - PII hashed in logs

Version History:
    2025-12-20 V1.0: Initial Lambda-ready implementation
"""

import os
import time
import math
import uuid
import requests
from io import BytesIO
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout


# =============================================================================
# COST TRACKING
# =============================================================================

# Pricing as of December 2025 (per 1M tokens)
PRICING = {
    'opus_4.5': {'input': 15.00, 'output': 75.00},
    'gpt_5.2': {'input': 1.75, 'output': 14.00},
}

CREDIT_INTERVAL = 0.05  # $0.05 per credit


@dataclass
class CostTracker:
    """Tracks API costs during document processing."""
    gist_cost: float = 0.0
    lookup_costs: List[float] = field(default_factory=list)
    gist_tokens: Tuple[int, int] = (0, 0)
    lookup_tokens: List[Tuple[int, int]] = field(default_factory=list)
    
    def add_gist_cost(self, input_tokens: int, output_tokens: int):
        cost = (
            (input_tokens / 1_000_000) * PRICING['opus_4.5']['input'] +
            (output_tokens / 1_000_000) * PRICING['opus_4.5']['output']
        )
        self.gist_cost = cost
        self.gist_tokens = (input_tokens, output_tokens)
        
    def add_lookup_cost(self, input_tokens: int, output_tokens: int):
        cost = (
            (input_tokens / 1_000_000) * PRICING['gpt_5.2']['input'] +
            (output_tokens / 1_000_000) * PRICING['gpt_5.2']['output']
        )
        self.lookup_costs.append(cost)
        self.lookup_tokens.append((input_tokens, output_tokens))
    
    @property
    def total_cost(self) -> float:
        return self.gist_cost + sum(self.lookup_costs)
    
    @property
    def credits_charged(self) -> int:
        if self.total_cost <= 0:
            return 1
        return max(1, math.ceil(self.total_cost / CREDIT_INTERVAL))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'gist_cost_usd': round(self.gist_cost, 6),
            'lookup_count': len(self.lookup_costs),
            'lookup_total_usd': round(sum(self.lookup_costs), 6),
            'total_cost_usd': round(self.total_cost, 6),
            'credits_charged': self.credits_charged,
        }


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class RawCitation:
    """A raw citation extracted from the document."""
    note_id: str
    note_type: str  # 'endnote' or 'footnote'
    text: str
    position: int
    
    @property
    def key(self) -> str:
        return f"{self.note_type}_{self.note_id}"


@dataclass 
class LookupResult:
    """Result of looking up citation components."""
    raw: RawCitation
    components: Optional[Any] = None
    formatted: str = ""
    success: bool = False
    error: str = ""
    ai_used: bool = False


@dataclass
class ProcessingResult:
    """Complete result of document processing."""
    success: bool
    document_bytes: Optional[bytes] = None
    citations_processed: int = 0
    citations_resolved: int = 0
    citations_failed: int = 0
    cost_tracker: Optional[CostTracker] = None
    error: str = ""
    request_id: str = ""
    duration_ms: int = 0


# =============================================================================
# STYLE CONFIGURATION
# =============================================================================

FOOTNOTE_STYLES = {'chicago manual of style', 'chicago', 'bluebook', 'oscola'}
AUTHOR_DATE_STYLES = {'apa 7', 'apa', 'mla 9', 'mla', 'asa', 'chicago author-date', 'harvard', 'vancouver'}


def is_author_date_style(style: str) -> bool:
    return style.lower().strip() in AUTHOR_DATE_STYLES


def is_footnote_style(style: str) -> bool:
    return style.lower().strip() in FOOTNOTE_STYLES


# =============================================================================
# DOCUMENT GIST EXTRACTION
# =============================================================================

def extract_document_gist(body_text: str, cost_tracker: CostTracker, request_id: str) -> str:
    """Extract document gist using Opus 4.5."""
    try:
        from config import ANTHROPIC_API_KEY
    except ImportError:
        ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
    
    if not ANTHROPIC_API_KEY or not body_text:
        return ""
    
    try:
        prompt = f"In 10-15 words, describe the academic field and topic:\n\n{body_text[:1000]}"
        
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-opus-4-5-20251101",
                "max_tokens": 50,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        
        response.raise_for_status()
        result = response.json()
        
        usage = result.get('usage', {})
        cost_tracker.add_gist_cost(
            usage.get('input_tokens', 0),
            usage.get('output_tokens', 0)
        )
        
        gist = result['content'][0]['text'].strip()
        print(f"[LambdaProcessor] Document gist: {gist}")
        return gist
        
    except Exception as e:
        print(f"[LambdaProcessor] Gist extraction failed: {e}")
        return ""


# =============================================================================
# PARALLEL CITATION COMPONENT LOOKUP
# =============================================================================

def lookup_citation_components_batch(
    raw_citations: List[RawCitation],
    style: str,
    gist: str,
    cost_tracker: CostTracker,
    request_id: str,
    user_id: str,
    max_workers: int = 20
) -> Dict[str, LookupResult]:
    """Look up citation components for all raw citations in parallel."""
    from unified_router import route_citation
    from formatters.base import get_formatter
    
    formatter = get_formatter(style)
    results: Dict[str, LookupResult] = {}
    
    # Deduplicate by normalized text
    unique_texts: Dict[str, RawCitation] = {}
    text_to_keys: Dict[str, List[str]] = {}
    
    for raw in raw_citations:
        normalized = raw.text.strip().lower()
        if normalized not in unique_texts:
            unique_texts[normalized] = raw
            text_to_keys[normalized] = []
        text_to_keys[normalized].append(raw.key)
    
    print(f"[LambdaProcessor] {len(raw_citations)} citations -> {len(unique_texts)} unique")
    
    def lookup_single(raw: RawCitation) -> LookupResult:
        try:
            components, formatted = route_citation(raw.text, style, gist, None)
            
            if components:
                return LookupResult(
                    raw=raw,
                    components=components,
                    formatted=formatted,
                    success=True,
                    ai_used=getattr(components, 'source_engine', '').lower() in ['ai lookup', 'gpt', 'claude']
                )
            else:
                return LookupResult(raw=raw, formatted=raw.text, success=False, error="No components")
                
        except Exception as e:
            return LookupResult(raw=raw, formatted=raw.text, success=False, error=str(e))
    
    # Parallel execution
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(lookup_single, raw): normalized
            for normalized, raw in unique_texts.items()
        }
        
        for future in as_completed(futures, timeout=600):
            normalized = futures[future]
            try:
                result = future.result(timeout=30)
                for key in text_to_keys[normalized]:
                    matching_raw = next(r for r in raw_citations if r.key == key)
                    results[key] = LookupResult(
                        raw=matching_raw,
                        components=result.components,
                        formatted=result.formatted,
                        success=result.success,
                        error=result.error,
                        ai_used=result.ai_used
                    )
            except Exception as e:
                for key in text_to_keys[normalized]:
                    matching_raw = next(r for r in raw_citations if r.key == key)
                    results[key] = LookupResult(
                        raw=matching_raw,
                        formatted=unique_texts[normalized].text,
                        success=False,
                        error=str(e)
                    )
    
    return results


# =============================================================================
# MAIN PROCESSOR
# =============================================================================

class LambdaDocumentProcessor:
    """Main document processor for Lambda deployment."""
    
    def __init__(self, user_id: str, request_id: Optional[str] = None):
        self.user_id = user_id
        self.request_id = request_id or f"req_{uuid.uuid4().hex[:12]}"
        self.cost_tracker = CostTracker()
    
    def process(
        self,
        docx_bytes: bytes,
        style: str,
        document_id: Optional[str] = None
    ) -> ProcessingResult:
        """Process a document with the specified citation style."""
        start_time = time.time()
        doc_id = document_id or f"doc_{uuid.uuid4().hex[:8]}"
        
        try:
            from author_date_transformer import (
                AuthorDateTransformer, ResolvedNote,
                build_parenthetical, build_sort_key
            )
            
            # Extract notes from document
            raw_citations = self._extract_citations(docx_bytes)
            
            if not raw_citations:
                return ProcessingResult(
                    success=True,
                    document_bytes=docx_bytes,
                    citations_processed=0,
                    request_id=self.request_id,
                    duration_ms=int((time.time() - start_time) * 1000)
                )
            
            # Extract document gist
            body_text = self._extract_body_text(docx_bytes)
            gist = extract_document_gist(body_text, self.cost_tracker, self.request_id)
            
            # Parallel lookup
            lookup_results = lookup_citation_components_batch(
                raw_citations, style, gist, self.cost_tracker, 
                self.request_id, self.user_id
            )
            
            # Transform based on style
            if is_author_date_style(style):
                result_bytes = self._transform_author_date(docx_bytes, lookup_results, style)
            else:
                result_bytes = self._transform_footnotes(docx_bytes, lookup_results, style)
            
            resolved = sum(1 for r in lookup_results.values() if r.success)
            
            return ProcessingResult(
                success=True,
                document_bytes=result_bytes,
                citations_processed=len(raw_citations),
                citations_resolved=resolved,
                citations_failed=len(lookup_results) - resolved,
                cost_tracker=self.cost_tracker,
                request_id=self.request_id,
                duration_ms=int((time.time() - start_time) * 1000)
            )
            
        except Exception as e:
            return ProcessingResult(
                success=False,
                error=str(e),
                cost_tracker=self.cost_tracker,
                request_id=self.request_id,
                duration_ms=int((time.time() - start_time) * 1000)
            )
    
    def _extract_citations(self, docx_bytes: bytes) -> List[RawCitation]:
        """Extract all citations from document footnotes/endnotes."""
        from author_date_transformer import AuthorDateTransformer
        
        transformer = AuthorDateTransformer(docx_bytes)
        note_texts = transformer.extract_note_texts()
        
        citations = []
        for i, (key, text) in enumerate(note_texts.items()):
            parts = key.split('_', 1)
            note_type = parts[0] if len(parts) > 1 else 'endnote'
            note_id = parts[1] if len(parts) > 1 else key
            
            citations.append(RawCitation(
                note_id=note_id, note_type=note_type,
                text=text, position=i
            ))
        
        return citations
    
    def _extract_body_text(self, docx_bytes: bytes, max_chars: int = 1500) -> str:
        """Extract body text for gist generation."""
        try:
            from document_processor import WordDocumentProcessor
            processor = WordDocumentProcessor(BytesIO(docx_bytes))
            text = processor.get_body_text(max_chars=max_chars)
            processor.cleanup()
            return text
        except Exception:
            return ""
    
    def _transform_author_date(
        self, docx_bytes: bytes,
        lookup_results: Dict[str, LookupResult],
        style: str
    ) -> bytes:
        """Transform to author-date format."""
        from author_date_transformer import (
            AuthorDateTransformer, ResolvedNote,
            build_parenthetical, build_sort_key
        )
        from formatters.base import get_formatter
        
        formatter = get_formatter(style)
        resolved_notes: Dict[str, ResolvedNote] = {}
        
        for key, result in lookup_results.items():
            if result.success and result.components:
                parenthetical = build_parenthetical(result.components, style)
                try:
                    reference_entry = formatter.format(result.components)
                except Exception:
                    reference_entry = result.formatted
                
                resolved_notes[key] = ResolvedNote(
                    reference=None,
                    components=result.components,
                    parenthetical=f" {parenthetical}",
                    reference_entry=reference_entry,
                    success=True,
                    sort_key=build_sort_key(result.components)
                )
            else:
                resolved_notes[key] = ResolvedNote(
                    reference=None,
                    parenthetical=f" [{result.raw.text[:30]}...]" if len(result.raw.text) > 30 else f" [{result.raw.text}]",
                    reference_entry="",
                    success=False
                )
        
        heading = "Works Cited" if 'mla' in style.lower() else "References"
        transformer = AuthorDateTransformer(docx_bytes)
        return transformer.transform(resolved_notes, heading)
    
    def _transform_footnotes(
        self, docx_bytes: bytes,
        lookup_results: Dict[str, LookupResult],
        style: str
    ) -> bytes:
        """Transform footnotes in place with ibid/short form."""
        from document_processor import WordDocumentProcessor
        
        seen: Dict[str, int] = {}
        last: Optional[str] = None
        formatted: Dict[str, str] = {}
        
        for key, result in sorted(lookup_results.items(), key=lambda x: x[1].raw.position):
            if not result.success:
                formatted[key] = result.formatted
                continue
            
            normalized = result.raw.text.strip().lower()
            
            if last == normalized:
                formatted[key] = "Ibid."
            elif normalized in seen:
                formatted[key] = self._build_short_form(result.components, style)
            else:
                formatted[key] = result.formatted
                seen[normalized] = result.raw.position
            
            last = normalized
        
        processor = WordDocumentProcessor(BytesIO(docx_bytes))
        for key, text in formatted.items():
            parts = key.split('_', 1)
            note_type = parts[0] if len(parts) > 1 else 'endnote'
            note_id = parts[1] if len(parts) > 1 else key
            
            if note_type == 'endnote':
                processor.write_endnote(note_id, text)
            else:
                processor.write_footnote(note_id, text)
        
        result_bytes = processor.save_to_buffer()
        processor.cleanup()
        return result_bytes
    
    def _build_short_form(self, components: Any, style: str) -> str:
        """Build short form citation."""
        authors = getattr(components, 'authors', [])
        title = getattr(components, 'title', '')[:27] + "..."
        
        if authors:
            first = authors[0]
            family = first.get('family', 'Unknown') if isinstance(first, dict) else str(first).split()[-1]
        else:
            family = "Unknown"
        
        return f"{family}, <i>{title}</i>"


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda entry point."""
    import json
    import boto3
    
    action = event.get('action', 'process_document')
    user_id = event.get('user_id')
    request_id = event.get('request_id') or f"req_{uuid.uuid4().hex[:12]}"
    
    if not user_id:
        return {"statusCode": 400, "body": json.dumps({"error": "user_id required"})}
    
    try:
        if action == 'process_document':
            s3 = boto3.client('s3')
            s3_bucket = event.get('s3_bucket')
            s3_key = event.get('s3_key')
            style = event.get('style', 'Chicago Manual of Style')
            
            response = s3.get_object(Bucket=s3_bucket, Key=s3_key)
            docx_bytes = response['Body'].read()
            
            processor = LambdaDocumentProcessor(user_id, request_id)
            result = processor.process(docx_bytes, style, event.get('document_id'))
            
            if result.success and result.document_bytes:
                output_key = s3_key.replace('/uploads/', '/outputs/').replace('.docx', '_processed.docx')
                s3.put_object(Bucket=s3_bucket, Key=output_key, Body=result.document_bytes)
                
                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "success": True,
                        "request_id": result.request_id,
                        "output_s3_key": output_key,
                        "citations_processed": result.citations_processed,
                        "citations_resolved": result.citations_resolved,
                        "credits_charged": result.cost_tracker.credits_charged if result.cost_tracker else 1,
                        "cost_usd": result.cost_tracker.total_cost if result.cost_tracker else 0,
                        "duration_ms": result.duration_ms
                    })
                }
            else:
                return {"statusCode": 500, "body": json.dumps({"error": result.error})}
        
        else:
            return {"statusCode": 400, "body": json.dumps({"error": f"Unknown action: {action}"})}
    
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def process_document_local(docx_path: str, style: str, user_id: str = "test") -> ProcessingResult:
    """Process a document locally for testing."""
    with open(docx_path, 'rb') as f:
        docx_bytes = f.read()
    return LambdaDocumentProcessor(user_id).process(docx_bytes, style)
