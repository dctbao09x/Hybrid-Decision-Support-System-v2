# backend/ops/tests/conftest.py
"""
Pytest configuration and shared fixtures for ops tests.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def sample_crawl_records():
    """Sample crawl output records."""
    return [
        {
            "job_id": f"fix_{i:03d}",
            "job_title": f"Software Engineer {i}",
            "company": f"Company{chr(65 + i % 5)}",
            "url": f"https://topcv.vn/job/fix_{i:03d}",
            "salary": f"{10 + i * 2} - {15 + i * 2} Triệu",
            "location": ["Hồ Chí Minh", "Hà Nội", "Đà Nẵng"][i % 3],
            "skills": ", ".join(["Python", "Java", "SQL"][: (i % 3 + 1)]),
        }
        for i in range(10)
    ]


@pytest.fixture
def sample_score_components():
    """Sample SIMGR component scores."""
    return {
        "study": 0.8,
        "interest": 0.7,
        "market": 0.6,
        "growth": 0.5,
        "risk": 0.3,
    }


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Use pytest-asyncio auto mode for modern compatibility
def pytest_configure(config):
    """Register asyncio markers."""
    config.addinivalue_line("markers", "asyncio: mark test as async")
