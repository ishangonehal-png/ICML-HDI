#!/usr/bin/env python3
"""CI guardrails for architecture coherence between docs and implementation."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_INDEX_PATH = REPO_ROOT / "docs" / "README.md"
PLAN_DOC_PATH = REPO_ROOT / "docs" / "architecture" / "plan.md"
UI_ARCH_DOC_PATH = REPO_ROOT / "docs" / "architecture" / "ui-architecture.md"
TASK_BACKLOG_PATH = REPO_ROOT / "docs" / "execution" / "task-backlog.md"
API_ROUTERS_DIR = REPO_ROOT / "apps" / "api" / "routers"
WEB_APP_DIR = REPO_ROOT / "apps" / "web" / "app"

CORE_DOC_PATHS = [
    "docs/README.md",
    "docs/architecture/plan.md",
    "docs/architecture/ui-architecture.md",
    "docs/execution/task-backlog.md",
]

REQUIRED_DOCS_HEADING = "## Required docs (CI enforced)"
PLAN_REQUIRED_API_HEADING = "## 4. Required API surface"
UI_API_DEPENDENCIES_HEADING = "## API dependencies"

DOC_LIST_ITEM_PATTERN = re.compile(r"^\s*-\s+`([^`]+)`", re.MULTILINE)
API_GROUP_PATTERN = re.compile(r"/v1/([a-z0-9-]+)")
PLAN_API_ENDPOINT_PATTERN = re.compile(
    r"`(GET|POST|PUT|PATCH|DELETE)\s+(/v1/[^\s`]+)`",
    re.IGNORECASE,
)
UI_CORE_PAGE_ROUTE_PATTERN = re.compile(r"^##\s+\d+\)\s+`(/[^`]+)`\s*$", re.MULTILINE)
ROUTE_DECORATOR_METHODS = {"get", "post", "put", "patch", "delete"}


class GuardrailError(RuntimeError):
    """Raised when an architecture coherence guard fails."""


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise GuardrailError(f"Expected file is missing: {path.relative_to(REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def _extract_markdown_section(text: str, heading: str, *, source: Path) -> str:
    lines = text.splitlines()

    start_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.strip() == heading:
            start_idx = idx + 1
            break

    if start_idx is None:
        raise GuardrailError(
            f"Missing expected heading '{heading}' in {source.relative_to(REPO_ROOT)}"
        )

    section_lines: list[str] = []
    for line in lines[start_idx:]:
        if line.startswith("## "):
            break
        section_lines.append(line)

    section = "\n".join(section_lines).strip()
    if not section:
        raise GuardrailError(
            f"Section '{heading}' in {source.relative_to(REPO_ROOT)} is empty"
        )
    return section


def _normalize_route(route: str) -> str:
    normalized = route.strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"

    normalized = normalized.rstrip("/")
    if normalized == "":
        normalized = "/"

    # Convert Next.js dynamic segment syntax ([param]) to docs syntax ({param}).
    normalized = re.sub(r"\[([^\]/]+)\]", r"{\1}", normalized)
    return normalized


def _join_routes(*parts: str) -> str:
    cleaned_parts: list[str] = []
    for part in parts:
        stripped = part.strip()
        if not stripped:
            continue
        cleaned = stripped.strip("/")
        if cleaned:
            cleaned_parts.append(cleaned)

    if not cleaned_parts:
        return "/"

    return "/" + "/".join(cleaned_parts)


def _assert_core_docs_exist() -> None:
    missing = [path for path in CORE_DOC_PATHS if not (REPO_ROOT / path).is_file()]
    if missing:
        raise GuardrailError(
            "Missing required core docs for docs-first architecture contract:\n- "
            + "\n- ".join(sorted(missing))
        )


def _check_docs_index_required_files() -> list[str]:
    text = _read_text(DOCS_INDEX_PATH)
    section = _extract_markdown_section(
        text,
        REQUIRED_DOCS_HEADING,
        source=DOCS_INDEX_PATH,
    )

    listed_paths = [match.group(1).strip() for match in DOC_LIST_ITEM_PATTERN.finditer(section)]
    if not listed_paths:
        raise GuardrailError(
            "docs/README.md required-docs section does not list any file paths"
        )

    missing_listed_docs = [path for path in listed_paths if not (REPO_ROOT / path).is_file()]
    if missing_listed_docs:
        raise GuardrailError(
            "docs/README.md lists required docs that do not exist:\n- "
            + "\n- ".join(sorted(missing_listed_docs))
        )

    missing_core_index_entries = [
        path for path in CORE_DOC_PATHS if path not in set(listed_paths)
    ]
    if missing_core_index_entries:
        raise GuardrailError(
            "docs/README.md required-docs section must include all core docs:\n- "
            + "\n- ".join(sorted(missing_core_index_entries))
        )

    return sorted(set(listed_paths))


def _extract_api_groups_from_doc(doc_path: Path, heading: str) -> list[str]:
    text = _read_text(doc_path)
    section = _extract_markdown_section(text, heading, source=doc_path)
    groups = sorted(set(API_GROUP_PATTERN.findall(section)))
    if not groups:
        raise GuardrailError(
            f"No /v1/<group> API routes found in {doc_path.relative_to(REPO_ROOT)} "
            f"section '{heading}'"
        )
    return groups


def _extract_plan_required_api_endpoints() -> list[tuple[str, str]]:
    text = _read_text(PLAN_DOC_PATH)
    section = _extract_markdown_section(text, PLAN_REQUIRED_API_HEADING, source=PLAN_DOC_PATH)

    endpoints = {
        (method.upper(), _normalize_route(path))
        for method, path in PLAN_API_ENDPOINT_PATTERN.findall(section)
    }
    if not endpoints:
        raise GuardrailError(
            "No explicit `METHOD /v1/...` API endpoints found in "
            "docs/architecture/plan.md required API section"
        )

    return sorted(endpoints)


def _extract_str_literal(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_api_router_call(node: ast.AST | None) -> bool:
    if not isinstance(node, ast.Call):
        return False

    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "APIRouter"
    if isinstance(func, ast.Attribute):
        return func.attr == "APIRouter"
    return False


def _extract_router_prefixes(path: Path) -> dict[str, str]:
    text = _read_text(path)
    try:
        module = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        raise GuardrailError(
            f"Failed to parse router module {path.relative_to(REPO_ROOT)}: {exc}"
        ) from exc

    prefixes: dict[str, str] = {}
    for node in module.body:
        targets: list[ast.expr] = []
        value: ast.AST | None = None

        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue

        if not _is_api_router_call(value):
            continue
        assert isinstance(value, ast.Call)  # narrows type for keyword iteration

        prefix = None
        for keyword in value.keywords:
            if keyword.arg == "prefix":
                prefix = _extract_str_literal(keyword.value)
                break
        if not prefix:
            continue

        for target in targets:
            if isinstance(target, ast.Name):
                prefixes[target.id] = prefix

    return prefixes


def _extract_route_path(decorator: ast.Call) -> str | None:
    if decorator.args:
        path = _extract_str_literal(decorator.args[0])
        if path is not None:
            return path

    for keyword in decorator.keywords:
        if keyword.arg in {"path", "route"}:
            path = _extract_str_literal(keyword.value)
            if path is not None:
                return path

    return None


def _extract_router_endpoints(path: Path, router_prefixes: dict[str, str]) -> set[tuple[str, str]]:
    text = _read_text(path)
    try:
        module = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        raise GuardrailError(
            f"Failed to parse router module {path.relative_to(REPO_ROOT)}: {exc}"
        ) from exc

    endpoints: set[tuple[str, str]] = set()
    for node in ast.walk(module):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr.lower() not in ROUTE_DECORATOR_METHODS:
                continue
            if not isinstance(decorator.func.value, ast.Name):
                continue

            router_name = decorator.func.value.id
            router_prefix = router_prefixes.get(router_name)
            if not router_prefix:
                continue

            route_path = _extract_route_path(decorator)
            if route_path is None:
                continue

            full_path = _normalize_route(_join_routes("/v1", router_prefix, route_path))
            endpoints.add((decorator.func.attr.upper(), full_path))

    return endpoints


def _extract_backend_router_groups() -> list[str]:
    if not API_ROUTERS_DIR.exists():
        raise GuardrailError("apps/api/routers is missing; cannot validate API route groups")

    groups: set[str] = set()
    for path in sorted(API_ROUTERS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue

        for prefix in _extract_router_prefixes(path).values():
            cleaned = prefix.strip().strip("/")
            if not cleaned:
                continue

            # Router prefixes should be single-group (e.g., /analysis, /fusion).
            group = cleaned.split("/")[0]
            groups.add(group)

    if not groups:
        raise GuardrailError("No APIRouter prefixes were discovered under apps/api/routers")

    return sorted(groups)


def _extract_backend_route_endpoints() -> list[tuple[str, str]]:
    if not API_ROUTERS_DIR.exists():
        raise GuardrailError("apps/api/routers is missing; cannot validate API endpoints")

    endpoints: set[tuple[str, str]] = set()
    for path in sorted(API_ROUTERS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue

        router_prefixes = _extract_router_prefixes(path)
        if not router_prefixes:
            # e.g. health router is mounted outside /v1 and intentionally excluded.
            continue

        endpoints.update(_extract_router_endpoints(path, router_prefixes))

    if not endpoints:
        raise GuardrailError("No backend API endpoints were discovered under apps/api/routers")

    return sorted(endpoints)


def _extract_documented_ui_core_routes() -> list[str]:
    text = _read_text(UI_ARCH_DOC_PATH)
    routes = {
        _normalize_route(match.group(1))
        for match in UI_CORE_PAGE_ROUTE_PATTERN.finditer(text)
    }

    if not routes:
        raise GuardrailError(
            "Could not parse core page routes from docs/architecture/ui-architecture.md"
        )

    return sorted(routes)


def _extract_frontend_routes() -> list[str]:
    if not WEB_APP_DIR.exists():
        return []

    page_files: list[Path] = []
    for pattern in ("page.tsx", "page.ts", "page.jsx", "page.js"):
        page_files.extend(sorted(WEB_APP_DIR.rglob(pattern)))

    routes: set[str] = set()
    for page_file in page_files:
        rel_parent = page_file.parent.relative_to(WEB_APP_DIR)
        if not rel_parent.parts:
            routes.add("/")
            continue

        path_parts: list[str] = []
        for part in rel_parent.parts:
            # Ignore Next.js route groups/parallel segments for URL matching.
            if (part.startswith("(") and part.endswith(")")) or part.startswith("@"):
                continue
            path_parts.append(part)

        route = "/" + "/".join(path_parts)
        routes.add(_normalize_route(route))

    return sorted(routes)


def main() -> int:
    _assert_core_docs_exist()
    print("✅ Core docs-first files exist")

    indexed_docs = _check_docs_index_required_files()
    print(f"✅ docs/README required-docs index resolves ({len(indexed_docs)} files)")

    plan_api_groups = _extract_api_groups_from_doc(PLAN_DOC_PATH, PLAN_REQUIRED_API_HEADING)
    ui_api_groups = _extract_api_groups_from_doc(UI_ARCH_DOC_PATH, UI_API_DEPENDENCIES_HEADING)

    missing_in_ui = sorted(set(plan_api_groups) - set(ui_api_groups))
    missing_in_plan = sorted(set(ui_api_groups) - set(plan_api_groups))
    if missing_in_ui or missing_in_plan:
        parts: list[str] = []
        if missing_in_ui:
            parts.append("documented in plan.md only:\n- " + "\n- ".join(missing_in_ui))
        if missing_in_plan:
            parts.append("documented in ui-architecture.md only:\n- " + "\n- ".join(missing_in_plan))
        raise GuardrailError(
            "API route-group docs drift detected between architecture docs:\n"
            + "\n".join(parts)
        )

    backend_groups = _extract_backend_router_groups()
    missing_backend_groups = sorted(set(plan_api_groups) - set(backend_groups))
    if missing_backend_groups:
        raise GuardrailError(
            "Documented required API route groups are missing from backend router prefixes:\n- "
            + "\n- ".join(missing_backend_groups)
            + "\nAvailable backend groups:\n- "
            + "\n- ".join(backend_groups)
        )

    plan_endpoints = _extract_plan_required_api_endpoints()
    backend_endpoints = _extract_backend_route_endpoints()
    missing_backend_endpoints = sorted(set(plan_endpoints) - set(backend_endpoints))
    if missing_backend_endpoints:
        formatted_missing = [f"{method} {path}" for method, path in missing_backend_endpoints]
        formatted_available = [f"{method} {path}" for method, path in backend_endpoints]
        raise GuardrailError(
            "Documented required API endpoints are missing from backend routers:\n- "
            + "\n- ".join(formatted_missing)
            + "\nDiscovered backend endpoints:\n- "
            + "\n- ".join(formatted_available)
        )

    print("✅ Documented API route groups are coherent across docs and backend routers")
    print("✅ Documented required API endpoints are represented in backend routers")

    documented_ui_routes = _extract_documented_ui_core_routes()
    if WEB_APP_DIR.exists():
        frontend_routes = _extract_frontend_routes()
        missing_frontend_routes = sorted(
            set(documented_ui_routes) - set(frontend_routes)
        )
        if missing_frontend_routes:
            raise GuardrailError(
                "UI workflow routes from ui-architecture.md are missing in apps/web/app route tree:\n- "
                + "\n- ".join(missing_frontend_routes)
                + "\nDiscovered frontend routes:\n- "
                + "\n- ".join(frontend_routes)
            )

        print("✅ UI core workflow routes are represented in apps/web route tree")
    else:
        print("ℹ️ apps/web not present; skipping UI route-tree coherence check")

    # Touch task backlog file through read path so core docs contract remains explicit.
    _read_text(TASK_BACKLOG_PATH)

    print("✅ Architecture coherence guardrails passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - explicit user-facing failure
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
