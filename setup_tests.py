import os

# 1. Create the tests directory
if not os.path.exists('tests'):
    os.makedirs('tests')
    print("Created 'tests' directory.")

# 2. Define the content for conftest.py
conftest_content = """
import pytest
from unittest.mock import MagicMock, patch
import os
import sys

# MOCK ENVIRONMENT
os.environ['OPENAI_API_KEY'] = 'sk-mock-key'
os.environ['ANTHROPIC_API_KEY'] = 'sk-mock-key'
os.environ['GEMINI_API_KEY'] = 'mock-key'
os.environ['SESSIONS_DIR'] = '/tmp/citeflex_sessions'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:' 

# MOCK MODULES
sys.modules['engines.google_scholar'] = MagicMock()
sys.modules['engines.superlegal'] = MagicMock()

@pytest.fixture
def mock_engines(mocker):
    mocks = {
        'crossref': mocker.patch('engines.academic.CrossrefEngine.search'),
        'openalex': mocker.patch('engines.academic.OpenAlexEngine.search'),
        'pubmed': mocker.patch('engines.academic.PubMedEngine.search'),
        'books': mocker.patch('engines.books.search_all_engines'),
        'ai_lookup': mocker.patch('engines.ai_lookup._call_ai'),
        'cl_search': mocker.patch('engines.superlegal.CourtListenerEngine.search')
    }
    for m in mocks.values():
        m.return_value = None
    return mocks
"""

# 3. Define the content for stress_test.py
stress_test_content = """
import pytest
import time
import pickle
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from pathlib import Path
from unified_router import get_multiple_citations
from models import SourceComponents, CitationType
from formatters.base import get_formatter

def test_nested_thread_pool_starvation(mock_engines):
    # Test Case 1: The 'Thread Explosion' Risk
    def slow_search(*args, **kwargs):
        time.sleep(2)
        return []

    mock_engines['books'].side_effect = slow_search
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=20) as router_pool:
        futures = [
            router_pool.submit(get_multiple_citations, "Smith 2020", limit=5)
            for _ in range(20)
        ]
        [f.result() for f in futures]

    duration = time.time() - start_time
    print(f"Duration: {duration:.2f}s")
    
    # If duration > 5s, the system is locking up
    assert duration < 5.0, "Thread Starvation Detected!"

def test_formatter_fragility():
    # Test Case 2: The 'Bibliography from Hell'
    styles = ["APA 7", "Chicago", "MLA 9", "Bluebook", "Vancouver", "ASA"]
    garbage_data = [
        SourceComponents(citation_type=CitationType.JOURNAL, authors=None),
        SourceComponents(citation_type=CitationType.BOOK, authors=[None]),
        SourceComponents(citation_type=CitationType.LEGAL, year="Not a year"),
        SourceComponents(citation_type=CitationType.UNKNOWN)
    ]
    
    for style in styles:
        formatter = get_formatter(style)
        for meta in garbage_data:
            try:
                res = formatter.format(meta)
                assert isinstance(res, str)
            except Exception as e:
                pytest.fail(f"CRASH: {style} formatter died: {e}")
"""

# 4. Write the files
with open('tests/conftest.py', 'w') as f:
    f.write(conftest_content)
    print("Created 'tests/conftest.py'")

with open('tests/stress_test.py', 'w') as f:
    f.write(stress_test_content)
    print("Created 'tests/stress_test.py'")

print("\\n✅ Setup complete! You can now run the tests.")
