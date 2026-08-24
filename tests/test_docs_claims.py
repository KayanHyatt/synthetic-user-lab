"""PROJECT_SPEC.md §M8: the README's own governing rule is that every
capability claim traces to something that exists in the tree and, where
possible, to something a test can break. This file is that test.

Four checks, all `[ADDITIVE]` -- §M8 itself carries no numbered acceptance
criteria, unlike M0-M7:

1. **Numbers** -- the validity figures quoted in `README.md` and
   `docs/limitations.md` are asserted against what `run_validity_harness`
   actually produces on the offline, cassette-replay path, not against a
   hand-written constant and not against a snapshot authored in this same
   commit. The provider is pinned explicitly here (the same Config A
   construction `sul.cli._select_validate_provider` builds for its real-
   provider branch) rather than letting that function's own cassette-
   directory sniffing decide -- a directory-state-driven test would be
   comparing docs against whichever numbers happened to be produced, not
   against a fixed, known configuration.
2. **Existence** -- every file path, qualified test name, CLI command, and
   `make.ps1` target named in `README.md` actually exists.
3. **Links** -- every internal Markdown link in `README.md` resolves.
4. **Caveat** -- `SIMULATED_PANEL_CAVEAT` (imported, never retyped) is
   present in `README.md`'s raw bytes, mirroring
   `tests/test_web_caveat.py`'s equivalent assertion for the dashboard's
   `id="standing-caveat"`.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from sul.cli import app
from sul.enums import AgentRole
from sul.providers.anthropic import AnthropicProvider
from sul.providers.cassette import CassetteTransport
from sul.report.model import SIMULATED_PANEL_CAVEAT
from sul.validity.harness import run_validity_harness
from sul.validity.model import ValidityReportModel

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
LIMITATIONS = REPO_ROOT / "docs" / "limitations.md"
CASSETTE_DIR = REPO_ROOT / "tests" / "cassettes"
MAKE_PS1 = REPO_ROOT / "make.ps1"

# The exact Config A construction PROJECT_SPEC.md §M6 Deviation 12/13
# recorded into tests/cassettes/, mirrored from sul.cli's own
# `_CASSETTE_CONFIG_MODEL` / `_CASSETTE_CONFIG_ANALYST_MODEL` -- pinned here
# rather than imported, so this test's provider choice does not move if
# sul.cli's constants ever do (a docs-numbers test silently following a CLI
# default around is exactly the directory-state coupling PROJECT_SPEC.md
# §M8 warned against).
_MODEL = "claude-haiku-4-5"
_ANALYST_MODEL = "claude-sonnet-5"


@pytest.fixture
async def pinned_report(
    session_factory: sessionmaker[Session],
) -> ValidityReportModel:
    """The same cassette-backed, replay-only `AnthropicProvider` construction
    `sul.cli._select_validate_provider` builds for its real-provider branch,
    built directly here instead of going through that function -- so this
    test's provider is a fixed, explicit choice, never a fact discovered
    from `tests/cassettes/`'s directory contents at test-run time.
    """
    transport = CassetteTransport(
        httpx.AsyncHTTPTransport(), CASSETTE_DIR, record=False
    )
    provider = AnthropicProvider(
        "sul-docs-test-replay-only-sentinel-key", transport=transport
    )
    return await run_validity_harness(
        session_factory,
        provider=provider,
        provider_name="anthropic",
        model=_MODEL,
        model_by_agent={AgentRole.ANALYST: _ANALYST_MODEL},
        base_path=REPO_ROOT,
    )


# --------------------------------------------------------------------------
# 1. Numbers
# --------------------------------------------------------------------------


async def test_readme_acquiescence_numbers_match_the_harness(
    pinned_report: ValidityReportModel,
) -> None:
    text = README.read_text(encoding="utf-8")
    acq = pinned_report.acquiescence_bias
    # Bold-anchored: the claim-trace table also says "gap 1.0" in plain
    # prose (a different row, a different sentence) -- an unanchored
    # substring check would still pass with the summary table's own number
    # corrupted, as long as the claim-trace table's copy survived untouched.
    assert f"**gap {acq.agreement_gap}**" in text
    assert f"positive-framing agree rate {acq.positive_agree_rate}" in text
    assert f"negative-framing agree rate {acq.negative_agree_rate}" in text
    assert f"{acq.subjects_measured}/{acq.subjects_attempted} subjects" in text


async def test_readme_calibration_numbers_match_the_harness(
    pinned_report: ValidityReportModel,
) -> None:
    text = README.read_text(encoding="utf-8")
    cal = pinned_report.known_answer_calibration
    assert f"**{cal.detected_count}/{cal.total_defects}** defects detected" in text


async def test_readme_discriminative_numbers_match_the_harness(
    pinned_report: ValidityReportModel,
) -> None:
    text = README.read_text(encoding="utf-8")
    disc = pinned_report.discriminative_validity
    assert (
        f"**{disc.bad_blocker_confusion_count}** blocker/confusion findings "
        f"(bad artefact) vs **{disc.good_blocker_confusion_count}** (good artefact)"
        in text
    )


async def test_readme_position_bias_numbers_match_the_harness(
    pinned_report: ValidityReportModel,
) -> None:
    text = README.read_text(encoding="utf-8")
    pos = pinned_report.position_bias
    # Bold-anchored for the same reason as the acquiescence gap above: the
    # claim-trace table's plain-prose "shift 0.0" would otherwise let this
    # pass even if the summary table's own bolded number were wrong.
    assert f"**shift {pos.preference_shift}**" in text
    assert f"{pos.subjects_measured}/{pos.subjects_attempted} subjects" in text


async def test_readme_reproducibility_numbers_match_the_harness(
    pinned_report: ValidityReportModel,
) -> None:
    text = README.read_text(encoding="utf-8")
    repro = pinned_report.reproducibility
    assert (
        f"variance {repro.finding_count_variance}, mean top-5 Jaccard "
        f"{repro.mean_top5_cluster_jaccard}" in text
    )


async def test_limitations_md_carries_the_same_gated_check_numbers(
    pinned_report: ValidityReportModel,
) -> None:
    """The burial fix: `docs/limitations.md` must carry the four
    provider-gated checks' numbers too, not just `docs/validity_report.md`.
    """
    text = LIMITATIONS.read_text(encoding="utf-8")
    acq = pinned_report.acquiescence_bias
    assert f"Agreement gap: {acq.agreement_gap}" in text
    cal = pinned_report.known_answer_calibration
    assert f"Detected: {cal.detected_count} / {cal.total_defects}" in text
    disc = pinned_report.discriminative_validity
    assert (
        f"Bad artefact blocker/confusion count: {disc.bad_blocker_confusion_count}"
        in text
    )


# --------------------------------------------------------------------------
# 2. Existence
# --------------------------------------------------------------------------

_PATH_SPAN = re.compile(r"`([^`\n]+)`")
_KNOWN_EXTENSIONS = (".py", ".md", ".yaml", ".yml", ".j2", ".ps1", ".db", ".toml")
_KNOWN_BARE_FILES = {"README.md", "PROJECT_SPEC.md", "CLAUDE.md", "sul.db"}


def _looks_like_a_path_or_qualified_test(span: str) -> bool:
    head = span.split("::", 1)[0]
    if head in _KNOWN_BARE_FILES:
        return True
    return "/" in head and head.endswith(_KNOWN_EXTENSIONS)


def test_every_backtick_path_named_in_the_readme_exists() -> None:
    text = README.read_text(encoding="utf-8")
    checked = 0
    for span in _PATH_SPAN.findall(text):
        if not _looks_like_a_path_or_qualified_test(span):
            continue
        path_part, _, test_part = span.partition("::")
        resolved = REPO_ROOT / path_part
        assert resolved.exists(), (
            f"README.md references {path_part!r}, which does not exist"
        )
        checked += 1
        if test_part:
            source = resolved.read_text(encoding="utf-8")
            assert re.search(rf"\bdef {re.escape(test_part)}\b", source), (
                f"README.md references {span!r}, but {test_part!r} is not "
                f"defined in {path_part}"
            )
    # A negative control on this test itself: fail loudly if the README's
    # prose ever stops carrying any checkable path at all, rather than this
    # test silently degrading into a no-op that always passes.
    assert checked >= 5


def test_every_make_ps1_target_named_in_the_readme_is_real() -> None:
    make_text = MAKE_PS1.read_text(encoding="utf-8")
    match = re.search(r"ValidateSet\(([^)]+)\)", make_text)
    assert match is not None, "make.ps1's ValidateSet moved or was removed"
    real_targets = {t.strip().strip('"') for t in match.group(1).split(",")}
    assert real_targets  # sanity: the regex actually found something

    readme_text = README.read_text(encoding="utf-8")
    named_targets = set(re.findall(r"\.\\make\.ps1 (\w+)", readme_text))
    assert named_targets  # the README does name at least one target
    assert named_targets <= real_targets, (
        f"README.md names make.ps1 target(s) {named_targets - real_targets} "
        f"that make.ps1 does not actually define ({real_targets})"
    )


def test_every_cli_command_named_in_the_readme_exists() -> None:
    readme_text = README.read_text(encoding="utf-8")
    named_commands = set(re.findall(r"(?:uv run )?sul (\w+)", readme_text))
    # "sul.pricing", "sul.cli", etc. are dotted module references, not CLI
    # invocations -- filtered out because the regex above only matches a
    # space, never a dot, after "sul".
    runner = CliRunner()
    for command in named_commands:
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, (
            f"README.md names `sul {command}`, which is not a real CLI "
            f"command (--help exited {result.exit_code}: {result.output})"
        )
    assert named_commands  # sanity: the README does name CLI commands


# --------------------------------------------------------------------------
# 3. Links
# --------------------------------------------------------------------------

_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def test_every_internal_markdown_link_in_the_readme_resolves() -> None:
    text = README.read_text(encoding="utf-8")
    targets = _MD_LINK.findall(text)
    internal = [
        t for t in targets if not t.startswith(("http://", "https://", "mailto:"))
    ]
    assert internal  # sanity: the README does link somewhere internally
    for target in internal:
        path_part = target.split("#", 1)[0]
        resolved = README.parent / path_part
        assert resolved.exists(), (
            f"README.md links to {target!r}, which does not resolve"
        )


def test_docs_limitations_no_longer_points_at_a_missing_readme() -> None:
    """`docs/limitations.md` names `README.md` in its own opening paragraph
    -- before this milestone, that pointed at a file that did not exist.
    Regression guard, not just a general link check.
    """
    assert README.exists()
    text = LIMITATIONS.read_text(encoding="utf-8")
    assert "README.md" in text


# --------------------------------------------------------------------------
# 4. Caveat
# --------------------------------------------------------------------------


def test_readme_carries_the_standing_caveat_verbatim() -> None:
    text = README.read_bytes().decode("utf-8")
    assert SIMULATED_PANEL_CAVEAT in text


# --------------------------------------------------------------------------
# 5. Docker packaging claim (PROJECT_SPEC.md §M7 packaging, closed this
#    session) -- the exact failure class this whole file exists for: a
#    claim true when written, false later, with no existence or link check
#    able to catch the drift on its own. `Dockerfile`/`docker-compose.yml`
#    either exist or don't; the README's prose about them must agree with
#    whichever is true *right now*, in both directions -- this cannot
#    prevent every future case of this class (see the module docstring's
#    own limits), but it collapses this one specific claim onto a
#    filesystem fact a test can actually check.
# --------------------------------------------------------------------------

DOCKERFILE = REPO_ROOT / "Dockerfile"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


def test_readme_docker_claim_agrees_with_whether_the_files_exist() -> None:
    text = README.read_text(encoding="utf-8")
    packaging_files_exist = DOCKERFILE.exists() and COMPOSE_FILE.exists()
    no_docker_claim_present = "no Docker workflow in this tree" in text

    if packaging_files_exist:
        assert not no_docker_claim_present, (
            "Dockerfile and docker-compose.yml both exist, but README.md "
            "still claims there is no Docker workflow in this tree"
        )
    else:
        assert no_docker_claim_present, (
            "Dockerfile/docker-compose.yml are missing, but README.md no "
            "longer says so -- the packaging criterion would be silently "
            "unstated rather than recorded as unmet"
        )
