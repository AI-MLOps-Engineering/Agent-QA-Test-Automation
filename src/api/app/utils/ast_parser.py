# src/api/app/utils/ast_parser.py
"""
AST-based parser utilities for extracting structural information from Python code.

Responsibilities:
- Parse Python files safely (no execution)
- Extract top-level classes, functions, imports, and FastAPI/Flask-like route definitions
- Produce small textual "documents" suitable for indexing (path + snippet + metadata)
- Provide repo-level summary helpers (counts, top modules, simple README-like summary)

Design notes:
- Purely static analysis using the `ast` module and file I/O.
- Defensive: ignores files that fail to parse and logs exceptions.
- Synchronous API (safe to call from threadpool). Higher-level async wrappers can call these via run_in_executor.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("agent_qa.ast_parser")


@dataclass
class FunctionInfo:
    name: str
    lineno: int
    end_lineno: Optional[int]
    args: List[str]
    returns: Optional[str]
    docstring: Optional[str]


@dataclass
class ClassInfo:
    name: str
    lineno: int
    end_lineno: Optional[int]
    bases: List[str]
    methods: List[FunctionInfo]
    docstring: Optional[str]


@dataclass
class ImportInfo:
    module: Optional[str]
    name: str
    alias: Optional[str]


@dataclass
class RouteInfo:
    http_methods: List[str]
    path: str
    handler: str
    lineno: int
    docstring: Optional[str]


@dataclass
class FileAnalysis:
    path: str
    functions: List[FunctionInfo]
    classes: List[ClassInfo]
    imports: List[ImportInfo]
    routes: List[RouteInfo]
    snippet: str  # first N lines or representative snippet
    errors: Optional[str] = None


# -------------------------
# Low-level helpers
# -------------------------
def _safe_read_text(path: Path, max_chars: int = 20_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if len(text) > max_chars:
            return text[:max_chars]
        return text
    except Exception as e:
        logger.exception("Failed to read file %s: %s", path, e)
        return ""


def _get_node_end_lineno(node: ast.AST) -> Optional[int]:
    # ast nodes in Python 3.8+ have end_lineno; fallback to lineno
    return getattr(node, "end_lineno", getattr(node, "lineno", None))


# -------------------------
# AST visitors
# -------------------------
class _RouteVisitor(ast.NodeVisitor):
    """
    Visitor to detect FastAPI/Flask-like route decorators.

    Detects patterns like:
      @app.get("/path")
      @router.post("/path")
      @bp.route("/path", methods=["GET","POST"])
    """

    def __init__(self):
        self.routes: List[RouteInfo] = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        methods = []
        path = None
        for dec in node.decorator_list:
            # decorator could be Call or Attribute or Name
            try:
                if isinstance(dec, ast.Call):
                    # e.g., app.get("/path") or bp.route("/path", methods=["GET"])
                    func = dec.func
                    # get decorator name like app.get or bp.route
                    dec_name = ""
                    if isinstance(func, ast.Attribute):
                        dec_name = func.attr.lower()
                    elif isinstance(func, ast.Name):
                        dec_name = func.id.lower()

                    # extract path arg if present
                    if dec.args:
                        first = dec.args[0]
                        if isinstance(first, ast.Constant) and isinstance(first.value, str):
                            path = first.value

                    # extract methods kwarg for Flask-style
                    for kw in dec.keywords:
                        if kw.arg and kw.arg.lower() == "methods":
                            # methods could be list of constants
                            if isinstance(kw.value, (ast.List, ast.Tuple)):
                                for elt in kw.value.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                        methods.append(elt.value.upper())
                    # heuristics: common decorator names
                    if dec_name in ("get", "post", "put", "delete", "patch", "options", "head"):
                        methods = [dec_name.upper()]
                    elif dec_name in ("route",):
                        # route without explicit methods -> assume GET
                        if not methods:
                            methods = ["GET"]
                elif isinstance(dec, ast.Attribute):
                    # e.g., @router.get
                    name = dec.attr.lower()
                    if name in ("get", "post", "put", "delete", "patch", "options", "head"):
                        methods = [name.upper()]
                elif isinstance(dec, ast.Name):
                    # plain decorator name
                    pass
            except Exception:
                logger.debug("Error while parsing decorator for function %s", node.name, exc_info=True)

        if methods or path:
            doc = ast.get_docstring(node)
            route = RouteInfo(http_methods=methods or ["GET"], path=path or "", handler=node.name, lineno=node.lineno, docstring=doc)
            self.routes.append(route)

        # continue visiting nested defs
        self.generic_visit(node)


class _StructureVisitor(ast.NodeVisitor):
    """
    Visitor to extract functions, classes, and imports.
    """

    def __init__(self):
        self.functions: List[FunctionInfo] = []
        self.classes: List[ClassInfo] = []
        self.imports: List[ImportInfo] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append(ImportInfo(module=None, name=alias.name, alias=alias.asname))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = node.module
        for alias in node.names:
            self.imports.append(ImportInfo(module=module, name=alias.name, alias=alias.asname))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        args = []
        for a in node.args.args:
            args.append(a.arg)
        returns = None
        if node.returns:
            try:
                returns = ast.unparse(node.returns) if hasattr(ast, "unparse") else None
            except Exception:
                returns = None
        fi = FunctionInfo(
            name=node.name,
            lineno=node.lineno,
            end_lineno=_get_node_end_lineno(node),
            args=args,
            returns=returns,
            docstring=ast.get_docstring(node),
        )
        self.functions.append(fi)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        bases = []
        for b in node.bases:
            try:
                bases.append(ast.unparse(b) if hasattr(ast, "unparse") else getattr(b, "id", str(b)))
            except Exception:
                bases.append(getattr(b, "id", str(b)))
        methods: List[FunctionInfo] = []
        for n in node.body:
            if isinstance(n, ast.FunctionDef):
                args = [a.arg for a in n.args.args]
                returns = None
                if n.returns:
                    try:
                        returns = ast.unparse(n.returns) if hasattr(ast, "unparse") else None
                    except Exception:
                        returns = None
                methods.append(
                    FunctionInfo(
                        name=n.name,
                        lineno=n.lineno,
                        end_lineno=_get_node_end_lineno(n),
                        args=args,
                        returns=returns,
                        docstring=ast.get_docstring(n),
                    )
                )
        ci = ClassInfo(
            name=node.name,
            lineno=node.lineno,
            end_lineno=_get_node_end_lineno(node),
            bases=bases,
            methods=methods,
            docstring=ast.get_docstring(node),
        )
        self.classes.append(ci)
        self.generic_visit(node)


# -------------------------
# Public API
# -------------------------
def analyze_python_file(path: Path, snippet_lines: int = 20) -> FileAnalysis:
    """
    Analyze a single Python file and return a FileAnalysis dataclass.

    - path: Path to the .py file
    - snippet_lines: number of lines to include in the snippet field
    """
    text = _safe_read_text(path)
    if not text:
        return FileAnalysis(path=str(path), functions=[], classes=[], imports=[], routes=[], snippet="", errors="empty or unreadable")

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as e:
        logger.exception("SyntaxError parsing %s: %s", path, e)
        snippet = "\n".join(text.splitlines()[:snippet_lines])
        return FileAnalysis(path=str(path), functions=[], classes=[], imports=[], routes=[], snippet=snippet, errors=f"SyntaxError: {e}")

    # extract structure
    struct_visitor = _StructureVisitor()
    struct_visitor.visit(tree)

    # extract routes
    route_visitor = _RouteVisitor()
    route_visitor.visit(tree)

    snippet = "\n".join(text.splitlines()[:snippet_lines])

    return FileAnalysis(
        path=str(path),
        functions=struct_visitor.functions,
        classes=struct_visitor.classes,
        imports=struct_visitor.imports,
        routes=route_visitor.routes,
        snippet=snippet,
        errors=None,
    )


def analyze_repo(repo_path: Path, include_patterns: Optional[List[str]] = None) -> List[FileAnalysis]:
    """
    Walk a repository directory and analyze all Python files.

    - repo_path: root path of the repository
    - include_patterns: optional list of glob patterns to include (e.g., ["src/**/*.py"])
    """
    repo_path = Path(repo_path)
    analyses: List[FileAnalysis] = []
    if include_patterns:
        # use glob patterns relative to repo_path
        for pat in include_patterns:
            for p in repo_path.glob(pat):
                if p.is_file() and p.suffix == ".py":
                    analyses.append(analyze_python_file(p))
    else:
        for p in repo_path.rglob("*.py"):
            if p.is_file():
                analyses.append(analyze_python_file(p))
    return analyses


def repo_summary(analyses: List[FileAnalysis]) -> Dict[str, object]:
    """
    Produce a lightweight summary of the repository based on file analyses.
    Returns a dict with counts and top-level highlights.
    """
    total_files = len(analyses)
    total_functions = sum(len(f.functions) for f in analyses)
    total_classes = sum(len(f.classes) for f in analyses)
    total_routes = sum(len(f.routes) for f in analyses)

    # top modules by function count
    by_funcs = sorted(analyses, key=lambda a: len(a.functions), reverse=True)
    top_modules = [Path(a.path).as_posix() for a in by_funcs[:10]]

    summary_text = (
        f"Indexed {total_files} Python files; {total_functions} functions; {total_classes} classes; {total_routes} detected routes. "
        f"Top modules: {', '.join(top_modules[:5])}."
    )

    return {
        "total_files": total_files,
        "total_functions": total_functions,
        "total_classes": total_classes,
        "total_routes": total_routes,
        "top_modules": top_modules,
        "summary": summary_text,
    }


def build_index_documents(analyses: List[FileAnalysis], repo_root: Path) -> List[Dict[str, object]]:
    """
    Convert FileAnalysis objects into small documents suitable for vector indexing.

    Each document contains:
    - id: path relative to repo_root
    - path: relative path
    - content: snippet + extracted signatures
    - metadata: dict with counts and flags (has_routes, has_tests, etc.)
    """
    docs = []
    repo_root = Path(repo_root)
    for a in analyses:
        # Compute a safe relative path. Use try/except to support older Python versions and avoid complex inline conditionals.
        try:
            rel_path = Path(a.path).relative_to(repo_root).as_posix()
        except Exception:
            # Fallback: if relative_to fails, try to compute a best-effort relative path or use absolute as posix
            try:
                # If a.path is already relative, Path(a.path).as_posix() is fine
                p = Path(a.path)
                if p.is_absolute():
                    # attempt to make it relative by string manipulation if repo_root is a prefix
                    repo_root_str = str(repo_root.resolve())
                    p_str = str(p.resolve())
                    if p_str.startswith(repo_root_str):
                        rel_path = p_str[len(repo_root_str) :].lstrip("/\\")
                    else:
                        rel_path = p.as_posix()
                else:
                    rel_path = p.as_posix()
            except Exception:
                rel_path = Path(a.path).as_posix()

        # Build a compact content string
        lines = []
        lines.append(f"File: {rel_path}")
        if a.classes:
            lines.append("Classes:")
            for c in a.classes[:10]:
                lines.append(f"- {c.name}({', '.join(c.bases)})")
        if a.functions:
            lines.append("Functions:")
            for f in a.functions[:20]:
                args = ", ".join(f.args)
                lines.append(f"- {f.name}({args})")
        if a.routes:
            lines.append("Routes:")
            for r in a.routes:
                methods = ",".join(r.http_methods)
                lines.append(f"- {methods} {r.path} -> {r.handler}")
        # include snippet
        lines.append("Snippet:")
        lines.append(a.snippet or "")
        content = "\n".join(lines)
        metadata = {
            "path": rel_path,
            "functions": len(a.functions),
            "classes": len(a.classes),
            "routes": len(a.routes),
            "has_routes": len(a.routes) > 0,
        }
        docs.append({"id": rel_path, "path": rel_path, "content": content, "metadata": metadata})
    return docs


# -------------------------
# Utility: safe relative check for older Python versions
# -------------------------
# Provide a fallback for Path.is_relative_to for Python < 3.9
if not hasattr(Path, "is_relative_to"):

    def _is_relative_to(path: Path, other: Path) -> bool:
        try:
            path.relative_to(other)
            return True
        except Exception:
            return False

    Path.is_relative_to = _is_relative_to  # type: ignore


# -------------------------
# CLI-like helper (for debugging)
# -------------------------
def analyze_and_print(repo_path: str, max_files: int = 50) -> None:
    """
    Simple helper to run analysis and print a short report to stdout.
    Useful during development and debugging.
    """
    repo = Path(repo_path)
    analyses = analyze_repo(repo)
    summary = repo_summary(analyses)
    logger.info("Repo summary: %s", summary["summary"])
    for a in analyses[:max_files]:
        logger.info("File: %s functions=%d classes=%d routes=%d", a.path, len(a.functions), len(a.classes), len(a.routes))


# Expose module API
__all__ = [
    "analyze_python_file",
    "analyze_repo",
    "repo_summary",
    "build_index_documents",
    "FileAnalysis",
    "FunctionInfo",
    "ClassInfo",
    "ImportInfo",
    "RouteInfo",
]
