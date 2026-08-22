"""Structural checks over `sul/agents/*.py` and `sul/runner/*.py`'s own
import statements and source text -- the mechanisms behind several §M4
carry-forward points, verified at the AST level rather than trusted by
convention:

- No ORM model ever crosses into a persona/analyst-bound module, even
  read-only ("If a builder needs a field `PersonaContext` doesn't carry,
  that is a spec conversation, not a new keyword argument").
- No concrete provider adapter is ever imported by an agent module --
  `ModelClient` is always injected, never constructed there.
- No non-deterministic source (`uuid`, wall-clock time, unseeded `random`,
  `os.environ`) is imported by a module that assembles a prompt --
  byte-stable prompt assembly (§M4 trap list).
- No regex module is imported by an agent -- "never regex an LLM response"
  (CLAUDE.md) made structural, not just a convention for the parsing path.
- No prompt text lives as a string literal in agent source -- "Prompt
  templates live in files, not string literals scattered through agent
  code" (§M4 carry-forward). Templates are `.j2` files; everything else in
  these modules is formatting/plumbing code, not authored instructional
  text, so no single string constant should be long.
- Every agent entry point's `client`/`provider` parameter has no default
  value -- provider injection, not a module-level fallback.

**PROJECT_SPEC.md §M7 extension.** `sul.web` (the dashboard) is read-only by
design (§M7: "Read-only is fine" -- this project takes the stronger
reading). The same AST-level mechanism used above for agent/runner modules
is extended to `src/sul/web/*.py`: no dashboard module may import
`sul.runner.orchestrator` (`run_study`), `sul.providers.client`
(`ModelClient`), or any concrete provider adapter -- there is no code path
from the dashboard to an LLM dispatch, which is what makes an
unauthenticated, published port defensible (no spend endpoint exists behind
it). This is a stronger check than a docstring promise: a future route that
imports `run_study` "just to show something" fails this test before it ever
runs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parents[1] / "src" / "sul" / "agents"
RUNNER_DIR = Path(__file__).resolve().parents[1] / "src" / "sul" / "runner"
WEB_DIR = Path(__file__).resolve().parents[1] / "src" / "sul" / "web"

_AGENT_MODULES = sorted(p for p in AGENTS_DIR.glob("*.py"))
_RUNNER_MODULES = sorted(p for p in RUNNER_DIR.glob("*.py"))
_WEB_MODULES = sorted(p for p in WEB_DIR.rglob("*.py"))

_FORBIDDEN_IN_AGENTS = {
    "sul.models",
    "sul.providers.anthropic",
    "sul.providers.openai",
    "sul.providers.gemini",
    "sul.providers.fake",
}
_FORBIDDEN_IN_WEB = {
    "sul.runner.orchestrator",
    "sul.providers.client",
    "sul.providers.anthropic",
    "sul.providers.openai",
    "sul.providers.gemini",
    "sul.providers.fake",
}
_NONDETERMINISTIC_MODULES = {"uuid", "datetime", "time", "random"}
_MAX_STRING_LITERAL_LEN = 200


def _imported_module_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


@pytest.mark.parametrize("path", _AGENT_MODULES, ids=lambda p: p.name)
def test_agent_modules_do_not_import_orm_or_concrete_adapters(path: Path) -> None:
    imported = _imported_module_names(_parse(path))
    leaked = {
        forbidden
        for forbidden in _FORBIDDEN_IN_AGENTS
        if any(m == forbidden or m.startswith(forbidden + ".") for m in imported)
    }
    assert not leaked, f"{path.name} imports forbidden module(s): {leaked}"


@pytest.mark.parametrize("path", _AGENT_MODULES, ids=lambda p: p.name)
def test_agent_modules_import_no_nondeterministic_sources(path: Path) -> None:
    imported = _imported_module_names(_parse(path))
    leaked = imported & _NONDETERMINISTIC_MODULES
    assert not leaked, f"{path.name} imports non-deterministic module(s): {leaked}"


@pytest.mark.parametrize("path", _AGENT_MODULES, ids=lambda p: p.name)
def test_agent_modules_do_not_import_re(path: Path) -> None:
    imported = _imported_module_names(_parse(path))
    assert "re" not in imported, f"{path.name} imports re (never regex an LLM response)"


@pytest.mark.parametrize("path", _AGENT_MODULES, ids=lambda p: p.name)
def test_agent_modules_do_not_read_os_environ(path: Path) -> None:
    tree = _parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            pytest.fail(f"{path.name} reads os.environ at line {node.lineno}")


@pytest.mark.parametrize("path", _AGENT_MODULES, ids=lambda p: p.name)
def test_no_long_string_literals_in_agent_source(path: Path) -> None:
    """Prompt text lives in `.j2` template files, not as string constants in
    agent code. Module/class/function docstrings are exempt (that's
    documentation, not something sent to a provider); everything else is
    formatting/plumbing and should never need a long literal.
    """
    tree = _parse(path)
    docstring_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                ):
                    docstring_nodes.add(id(body[0].value))

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_nodes
            and len(node.value) > _MAX_STRING_LITERAL_LEN
        ):
            pytest.fail(
                f"{path.name}:{node.lineno} has a {len(node.value)}-char string "
                "literal outside a docstring -- prompt text belongs in a .j2 "
                "template file"
            )


def _entry_point_functions(tree: ast.Module) -> list[ast.AsyncFunctionDef]:
    return [
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and not node.name.startswith("_")
    ]


@pytest.mark.parametrize("path", _AGENT_MODULES, ids=lambda p: p.name)
def test_client_or_provider_params_have_no_default(path: Path) -> None:
    tree = _parse(path)
    for func in _entry_point_functions(tree):
        args = func.args
        all_args = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        defaults_by_name: dict[str, object] = {}
        # Positional/pos-or-keyword defaults align to the *end* of the list.
        pos_args = [*args.posonlyargs, *args.args]
        if args.defaults:
            for name, _default in zip(
                pos_args[len(pos_args) - len(args.defaults) :],
                args.defaults,
                strict=True,
            ):
                defaults_by_name[name.arg] = _default
        for name, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
            if default is not None:
                defaults_by_name[name.arg] = default

        for arg in all_args:
            if arg.arg in ("client", "provider"):
                assert arg.arg not in defaults_by_name, (
                    f"{path.name}::{func.name}'s {arg.arg!r} parameter has a "
                    "default -- provider injection must be required, not "
                    "optional with a fallback"
                )


@pytest.mark.parametrize("path", _RUNNER_MODULES, ids=lambda p: p.name)
def test_runner_modules_import_no_concrete_adapters(path: Path) -> None:
    imported = _imported_module_names(_parse(path))
    leaked = {
        forbidden
        for forbidden in _FORBIDDEN_IN_AGENTS
        if forbidden.startswith("sul.providers.")
        and any(m == forbidden or m.startswith(forbidden + ".") for m in imported)
    }
    assert not leaked, f"{path.name} imports concrete adapter(s): {leaked}"


@pytest.mark.parametrize("path", _WEB_MODULES, ids=lambda p: p.name)
def test_web_modules_cannot_dispatch_an_llm_call(path: Path) -> None:
    """PROJECT_SPEC.md §M7: the dashboard is strictly read-only -- no module
    under `sul.web` may import `run_study`, `ModelClient`, or any concrete
    provider adapter (`sul.web`'s own package docstring states this; this is
    the structural enforcement, not just the promise).
    """
    imported = _imported_module_names(_parse(path))
    leaked = {
        forbidden
        for forbidden in _FORBIDDEN_IN_WEB
        if any(m == forbidden or m.startswith(forbidden + ".") for m in imported)
    }
    assert not leaked, f"{path.name} imports forbidden module(s): {leaked}"
