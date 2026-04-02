# tests/unit/test_sample.py
"""
Unit tests for small utility sanity checks.

These tests are lightweight and focus on core utilities used by the orchestrator:
- basic assertion to ensure test runner works
- AST parser: analyze a tiny Python snippet and verify the produced FileAnalysis
- build_index_documents: ensure documents are produced with expected keys
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.utils import ast_parser


def test_smoke():
    """Simple smoke test to verify pytest is running."""
    assert 1 + 1 == 2


def test_analyze_python_file_and_build_index(tmp_path: Path):
    """
    Create a small Python file, run analyze_python_file and build_index_documents,
    then assert the returned structures contain expected fields.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    file_path = repo_dir / "sample.py"
    file_content = """\
def add(a, b):
    \"\"\"Add two numbers\"\"\"
    return a + b

class Greeter:
    def greet(self, name):
        return f"Hello {name}"
"""
    file_path.write_text(file_content, encoding="utf-8")

    # Analyze the single file
    fa = ast_parser.analyze_python_file(file_path)
    assert fa.path.endswith("sample.py")
    # functions and classes should be detected
    func_names = [f.name for f in fa.functions]
    class_names = [c.name for c in fa.classes]
    assert "add" in func_names
    assert "Greeter" in class_names
    assert "Add two numbers" in (fa.snippet or "") or fa.snippet != ""

    # Build index documents for the repo
    analyses = [fa]
    docs = ast_parser.build_index_documents(analyses, repo_root=repo_dir)
    assert isinstance(docs, list)
    assert len(docs) == 1
    doc = docs[0]
    # Document must contain required keys
    assert "id" in doc and "path" in doc and "content" in doc and "metadata" in doc
    meta = doc["metadata"]
    assert meta["functions"] >= 1
    assert meta["classes"] >= 1


def test_analyze_repo_summary_empty(tmp_path: Path):
    """
    When analyzing an empty repo (no .py files), repo_summary should report zeros.
    """
    repo_dir = tmp_path / "empty_repo"
    repo_dir.mkdir()
    analyses = ast_parser.analyze_repo(repo_dir)
    summary = ast_parser.repo_summary(analyses)
    assert summary["total_files"] == 0
    assert summary["total_functions"] == 0
    assert summary["total_classes"] == 0
    assert isinstance(summary["summary"], str)
