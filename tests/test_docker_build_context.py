"""PROJECT_SPEC.md §M7 packaging: the `.dockerignore` build-context check.

This is the one check in §M7's recorded verification plan that "needs no
Docker and can be written and run *before* Docker exists" -- a pure-Python
re-implementation of Docker's own `.dockerignore` matching rules (last
matching pattern wins; excluding or re-including a directory also affects
everything below it), applied to `.dockerignore`'s real, committed text.

This model was cross-checked once, manually, against a real
`docker build`'s own reported build-context file list (`COPY . /ctx` into a
throwaway image, then diffed against this module's `resolve_build_context`
output) rather than trusted on the strength of reading Docker's docs --
see PROJECT_SPEC.md §M7's Deviation for that session's output. This test
suite itself never invokes Docker: it only re-runs the same pure-Python
matcher, offline, against both a synthetic fixture tree (covering the
specific paths the packaging criterion cares about: `.env`, `sul.db`,
`.venv/`, `*.pem`, `tests/cassettes/`, and the one vendored asset,
`src/sul/web/static/htmx.min.js`) and the real repo's own top-level
listing (a shallow check only -- never recurses into `.venv/`/`.git/`,
which are large and irrelevant to what this test is asserting).
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERIGNORE = REPO_ROOT / ".dockerignore"


def _parse_dockerignore(text: str) -> list[tuple[bool, tuple[str, ...]]]:
    """Each non-blank, non-comment line becomes `(negated, components)` --
    `!`-prefixed lines are negated (re-include), everything else excludes.
    Leading/trailing `/` is stripped: Docker's patterns are always relative
    to the build-context root regardless of a leading slash, and a trailing
    slash marks a directory but doesn't change what it matches.
    """
    patterns: list[tuple[bool, tuple[str, ...]]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        line = line.strip("/")
        if not line:
            continue
        patterns.append((negated, tuple(line.split("/"))))
    return patterns


def _match_exact(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
    """True if `pattern` matches `path` component-for-component, where a
    literal `**` component matches zero or more path components (ordinary
    components use `fnmatch`) -- e.g. `**/__pycache__/` needs `**` to match
    at the start, not just trail off the end the way `src/**` does.
    """
    if not pattern:
        return not path
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        return _match_exact(rest, path) or (
            bool(path) and _match_exact(pattern, path[1:])
        )
    if not path:
        return False
    return fnmatch.fnmatchcase(path[0], head) and _match_exact(rest, path[1:])


def _pattern_matches_path(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
    """True if `pattern` matches `path` itself, or `path` is nested under a
    directory `pattern` matches -- Docker's "matching a directory also
    matches everything below it" rule. Implemented by trying `pattern`
    against every prefix of `path`'s components: a pattern with no `**`
    (e.g. plain `src`) still matches every path nested under it this way,
    and a pattern that itself contains `**` (e.g. `**/__pycache__/`) is
    handled by `_match_exact`'s own zero-or-more-components semantics.
    """
    return any(_match_exact(pattern, path[:k]) for k in range(len(path) + 1))


def resolve_build_context(root: Path, dockerignore_text: str) -> set[str]:
    """The repo-relative POSIX paths of every *file* under `root` that
    `dockerignore_text` would leave in the Docker build context --
    last-matching-pattern-wins, same as Docker's own documented semantics.
    """
    patterns = _parse_dockerignore(dockerignore_text)
    included: set[str] = set()
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        components = tuple(rel.split("/"))
        excluded = False
        for negated, pattern in patterns:
            if _pattern_matches_path(pattern, components):
                excluded = not negated
        if not excluded:
            included.add(rel)
    return included


# ---------------------------------------------------------------------------
# Synthetic fixture tree: mirrors the real repo's interesting cases without
# walking the real `.venv/` (392MB) or reading the real `.env` (a real
# secret).
# ---------------------------------------------------------------------------


def _build_fixture_tree(base: Path) -> None:
    entries = [
        ".env",
        ".git/HEAD",
        "sul.db",
        "windows-roots.pem",
        ".venv/pyvenv.cfg",
        ".venv/Lib/site-packages/foo.py",
        "tests/cassettes/deadbeef.json",
        "tests/test_something.py",
        "src/sul/__init__.py",
        "src/sul/cli.py",
        "src/sul/web/static/htmx.min.js",
        "src/sul/__pycache__/cli.cpython-312.pyc",
        "src/sul/agents/__pycache__/analyst.cpython-312.pyc",
        "configs/study.demo.yaml",
        "artefacts/bad_onboarding.html",
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "PROJECT_SPEC.md",
        "CLAUDE.md",
    ]
    for rel in entries:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("placeholder\n", encoding="utf-8")


def test_dockerignore_file_exists() -> None:
    assert DOCKERIGNORE.exists()


def test_secrets_and_local_state_are_excluded_from_the_build_context(
    tmp_path: Path,
) -> None:
    _build_fixture_tree(tmp_path)
    included = resolve_build_context(tmp_path, DOCKERIGNORE.read_text(encoding="utf-8"))

    for must_be_excluded in (
        ".env",
        ".git/HEAD",
        "sul.db",
        "windows-roots.pem",
        ".venv/pyvenv.cfg",
        ".venv/Lib/site-packages/foo.py",
        "tests/cassettes/deadbeef.json",
        "tests/test_something.py",
        "src/sul/__pycache__/cli.cpython-312.pyc",
        "src/sul/agents/__pycache__/analyst.cpython-312.pyc",
        "README.md",
        "PROJECT_SPEC.md",
        "CLAUDE.md",
    ):
        assert must_be_excluded not in included, (
            f"{must_be_excluded!r} would reach the Docker build context -- "
            ".dockerignore is not excluding it"
        )


def test_source_configs_and_artefacts_reach_the_build_context(tmp_path: Path) -> None:
    _build_fixture_tree(tmp_path)
    included = resolve_build_context(tmp_path, DOCKERIGNORE.read_text(encoding="utf-8"))

    for must_be_included in (
        "src/sul/__init__.py",
        "src/sul/cli.py",
        "src/sul/web/static/htmx.min.js",
        "configs/study.demo.yaml",
        "artefacts/bad_onboarding.html",
        "pyproject.toml",
        "uv.lock",
    ):
        assert must_be_included in included, (
            f"{must_be_included!r} is needed for the image build but "
            ".dockerignore is excluding it"
        )


def test_real_repo_top_level_secrets_are_excluded() -> None:
    """A shallow check against the real repo's own top-level listing --
    never recurses into `.venv/`/`.git/`, which are large and beside the
    point of this assertion, but proves the real, committed `.dockerignore`
    (not a copy or a paraphrase of it) excludes the real top-level entries
    that matter: `.env` (which really holds an `ANTHROPIC_API_KEY=` line,
    see `tests/test_docs_claims.py`'s neighboring concerns), `sul.db`, and
    `.venv/`.
    """
    dockerignore_text = DOCKERIGNORE.read_text(encoding="utf-8")
    patterns = _parse_dockerignore(dockerignore_text)

    for name in (".env", "sul.db", ".venv", ".git", "sul.db-journal"):
        components = (name,)
        excluded = False
        for negated, pattern in patterns:
            if _pattern_matches_path(pattern, components):
                excluded = not negated
        assert excluded, f"real top-level entry {name!r} is not excluded"


def test_dockerignore_pattern_matcher_handles_star_wildcard() -> None:
    """`_pattern_matches_path` delegates single-component glob matching to
    `fnmatch`, not a literal string comparison -- a regression guard using
    `*.pem` (one of §M7's own named secrets-in-image checklist patterns,
    even though the real `.dockerignore` excludes such files via the
    deny-by-default `*` catch-all rather than a dedicated `*.pem` rule).
    """
    assert _pattern_matches_path(("*.pem",), ("windows-roots.pem",))
    assert not _pattern_matches_path(("*.pem",), ("windows-roots.txt",))
