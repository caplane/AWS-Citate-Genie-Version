#!/usr/bin/env python3
"""
Stress Test Runner for Citate Genie
Evaluates accuracy of first recommendation and alternatives against answer key.
"""

import csv
import sys
import os
from typing import List, Tuple, Optional
import re

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unified_router import get_multiple_citations
from models import SourceComponents


def normalize_citation(text: str) -> str:
    """Normalize citation for comparison - remove extra whitespace, standardize punctuation."""
    if not text:
        return ""
    # Remove markdown italics
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    # Normalize whitespace
    text = ' '.join(text.split())
    # Normalize quotes
    text = text.replace('"', '"').replace('"', '"').replace("'", "'")
    # Remove trailing periods
    text = text.rstrip('.')
    return text.lower().strip()


def extract_key_components(citation: str) -> dict:
    """Extract key identifiable components from a citation for matching."""
    components = {}
    
    # Extract author (first word before comma or quoted title)
    author_match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-z]+)?)', citation)
    if author_match:
        components['author'] = author_match.group(1).lower()
    
    # Extract title (in quotes)
    title_match = re.search(r'"([^"]+)"', citation)
    if title_match:
        components['title'] = title_match.group(1).lower()
    
    # Extract year
    year_match = re.search(r'\b(19|20)\d{2}\b', citation)
    if year_match:
        components['year'] = year_match.group(0)
    
    # Extract publication name (in italics)
    pub_match = re.search(r'\*([^*]+)\*', citation)
    if pub_match:
        components['publication'] = pub_match.group(1).lower()
    
    return components


def citations_match(actual: str, expected: str, strict: bool = False) -> Tuple[bool, float]:
    """
    Check if citations match. Returns (match, confidence_score).
    
    For first recommendation: use stricter matching
    For alternatives: use looser matching
    """
    if not actual or not expected:
        return False, 0.0
    
    actual_norm = normalize_citation(actual)
    expected_norm = normalize_citation(expected)
    
    # Exact match
    if actual_norm == expected_norm:
        return True, 1.0
    
    # Extract key components
    actual_comp = extract_key_components(actual)
    expected_comp = extract_key_components(expected)
    
    # Component matching
    matches = 0
    total = 0
    
    # Check title (most important)
    if 'title' in expected_comp:
        total += 2  # Title weighted double
        if 'title' in actual_comp:
            expected_title = expected_comp['title']
            actual_title = actual_comp['title']
            # Check if titles have significant overlap
            expected_words = set(expected_title.split())
            actual_words = set(actual_title.split())
            overlap = len(expected_words & actual_words) / max(len(expected_words), 1)
            if overlap > 0.6:
                matches += 2
            elif overlap > 0.3:
                matches += 1
    
    # Check author
    if 'author' in expected_comp:
        total += 1
        if 'author' in actual_comp:
            if expected_comp['author'] in actual_comp['author'] or actual_comp['author'] in expected_comp['author']:
                matches += 1
    
    # Check year
    if 'year' in expected_comp:
        total += 1
        if 'year' in actual_comp and expected_comp['year'] == actual_comp['year']:
            matches += 1
    
    # Check publication
    if 'publication' in expected_comp:
        total += 1
        if 'publication' in actual_comp:
            if expected_comp['publication'] in actual_comp['publication'] or actual_comp['publication'] in expected_comp['publication']:
                matches += 1
    
    if total == 0:
        return False, 0.0
    
    score = matches / total
    
    # For strict matching (first recommendation), require higher threshold
    threshold = 0.7 if strict else 0.5
    
    return score >= threshold, score


def run_single_test(test_id: int, input_type: str, input_text: str, expected: str, source_type: str) -> dict:
    """Run a single test case and return results."""
    result = {
        'test_id': test_id,
        'input_type': input_type,
        'input': input_text,
        'expected': expected,
        'source_type': source_type,
        'first_match': False,
        'first_recommendation': '',
        'alt_match': False,
        'alt_recommendation': '',
        'all_recommendations': [],
        'notes': ''
    }
    
    try:
        # Get multiple citation recommendations (style = chicago for CMS)
        recommendations = get_multiple_citations(input_text, style="chicago", limit=5)
        
        if not recommendations:
            result['notes'] = "No recommendations returned"
            return result
        
        # Store all recommendations
        result['all_recommendations'] = [(r[1], r[2]) for r in recommendations]  # (formatted, source)
        
        # Check first recommendation
        first_formatted = recommendations[0][1] if recommendations else ""
        result['first_recommendation'] = first_formatted
        
        first_match, first_score = citations_match(first_formatted, expected, strict=True)
        result['first_match'] = first_match
        
        if first_match:
            result['notes'] = f"First match (score: {first_score:.2f})"
            return result
        
        # Check alternatives
        for i, (meta, formatted, source) in enumerate(recommendations[1:], start=2):
            alt_match, alt_score = citations_match(formatted, expected, strict=False)
            if alt_match:
                result['alt_match'] = True
                result['alt_recommendation'] = formatted
                result['notes'] = f"Alt match at position {i} (score: {alt_score:.2f})"
                return result
        
        result['notes'] = f"No match in {len(recommendations)} recommendations"
        
    except Exception as e:
        result['notes'] = f"Error: {str(e)}"
    
    return result


def run_stress_test(csv_path: str) -> List[dict]:
    """Run stress test on all items in CSV."""
    results = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            test_id = int(row['Test_ID'])
            print(f"\n{'='*60}")
            print(f"Test {test_id}: {row['Input_Type']} - {row['Source_Type']}")
            print(f"Input: {row['Input'][:60]}...")
            
            result = run_single_test(
                test_id=test_id,
                input_type=row['Input_Type'],
                input_text=row['Input'],
                expected=row['Expected_CMS_Citation'],
                source_type=row['Source_Type']
            )
            
            results.append(result)
            
            status = "✓ FIRST" if result['first_match'] else ("✓ ALT" if result['alt_match'] else "✗ MISS")
            print(f"Result: {status}")
            print(f"Notes: {result['notes']}")
    
    return results


def print_summary(results: List[dict]):
    """Print summary statistics."""
    total = len(results)
    first_matches = sum(1 for r in results if r['first_match'])
    alt_matches = sum(1 for r in results if r['alt_match'])
    total_matches = first_matches + alt_matches
    misses = total - total_matches
    
    print("\n" + "="*70)
    print("STRESS TEST RESULTS SUMMARY")
    print("="*70)
    
    print(f"\nTotal test cases: {total}")
    print(f"\nFirst recommendation matches: {first_matches}/{total} ({100*first_matches/total:.1f}%)")
    print(f"Alternative matches: {alt_matches}/{total} ({100*alt_matches/total:.1f}%)")
    print(f"Total matches: {total_matches}/{total} ({100*total_matches/total:.1f}%)")
    print(f"Misses: {misses}/{total} ({100*misses/total:.1f}%)")
    
    # Breakdown by input type
    print("\n--- BY INPUT TYPE ---")
    for input_type in ['clean_url', 'messy_citation', 'messy_citation_misspelled']:
        subset = [r for r in results if r['input_type'] == input_type]
        if subset:
            first = sum(1 for r in subset if r['first_match'])
            alt = sum(1 for r in subset if r['alt_match'])
            n = len(subset)
            print(f"{input_type}: {first+alt}/{n} total ({100*(first+alt)/n:.1f}%), {first}/{n} first ({100*first/n:.1f}%)")
    
    # Breakdown by source type
    print("\n--- BY SOURCE TYPE ---")
    for source_type in ['newspaper', 'video', 'government', 'journal', 'book']:
        subset = [r for r in results if r['source_type'] == source_type]
        if subset:
            first = sum(1 for r in subset if r['first_match'])
            alt = sum(1 for r in subset if r['alt_match'])
            n = len(subset)
            print(f"{source_type}: {first+alt}/{n} total ({100*(first+alt)/n:.1f}%), {first}/{n} first ({100*first/n:.1f}%)")
    
    # List failures
    failures = [r for r in results if not r['first_match'] and not r['alt_match']]
    if failures:
        print("\n--- FAILURES ---")
        for f in failures:
            print(f"  Test {f['test_id']} ({f['input_type']}, {f['source_type']}): {f['input'][:40]}...")
            print(f"    Expected: {f['expected'][:60]}...")
            print(f"    Got: {f['first_recommendation'][:60] if f['first_recommendation'] else 'None'}...")


def save_results(results: List[dict], output_path: str):
    """Save results to CSV."""
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['test_id', 'input_type', 'source_type', 'input', 'expected', 
                      'first_match', 'first_recommendation', 'alt_match', 'alt_recommendation', 'notes']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row = {k: r.get(k, '') for k in fieldnames}
            writer.writerow(row)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    # Default paths
    input_csv = "/mnt/user-data/outputs/stress_test_pilot_40.csv"
    output_csv = "/mnt/user-data/outputs/stress_test_results.csv"
    
    if len(sys.argv) > 1:
        input_csv = sys.argv[1]
    if len(sys.argv) > 2:
        output_csv = sys.argv[2]
    
    print(f"Running stress test on: {input_csv}")
    print("="*70)
    
    results = run_stress_test(input_csv)
    print_summary(results)
    save_results(results, output_csv)
