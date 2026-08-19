"""`sul.report.markdown`/`sul.report.html` (PROJECT_SPEC.md §M5 acceptance
criterion: "every finding links to at least one transcript turn"), tested by
parsing the actual rendered files -- not the `ReportModel`, and not by
substring-matching -- against a populated fixture. Two separate injected
defects per format (evidence loss, finding/cluster loss), an escaping-hazard
fixture built to break naive Markdown escaping, and long-quote handling.
"""

from __future__ import annotations

import jinja2
from sqlalchemy.orm import Session

from sul import models
from sul.analysis.config import ClusteringConfig
from sul.enums import ArtefactKind, RunStatus
from sul.report.build import build_report
from sul.report.html import render_html
from sul.report.markdown import render_markdown
from sul.report.model import SIMULATED_PANEL_CAVEAT
from tests.support.html_parse import parse_report_html
from tests.support.markdown_parse import parse_report_markdown
from tests.support.report_factory import (
    ESCAPING_HAZARD_QUOTE,
    build_report_fixture,
    build_single_finding_fixture,
)


def test_every_rendered_finding_links_to_a_real_transcript_quote(
    session: Session,
) -> None:
    """The acceptance criterion, done against the rendered files: total
    quote count and cluster count in each parsed file match counts derived
    independently from the fixture (3 findings, 1 cluster), and every parsed
    quote is real `Turn.content` text -- not a substring check, an exact
    membership check against the fixture's own known evidence content.
    """
    fixture = build_report_fixture(session)
    report = build_report(session, study_id=fixture.study_id)
    assert report.total_findings == 3
    assert len(report.clusters) == 1

    known_quotes = {
        "I could not find the submit button anywhere.",
        "The submit button was nowhere to be found on the signup form.",
        "I struggled to find the submit button after filling in the form.",
    }

    md_clusters = parse_report_markdown(render_markdown(report))
    assert len(md_clusters) == 1
    assert len(md_clusters[0].quotes) == 3
    assert set(md_clusters[0].quotes) == known_quotes

    html_clusters, external_refs = parse_report_html(render_html(report))
    assert external_refs == []
    assert len(html_clusters) == 1
    assert len(html_clusters[0].quotes) == 3
    assert set(html_clusters[0].quotes) == known_quotes
    assert sorted(html_clusters[0].finding_ids) == sorted(
        f.finding_id for f in report.clusters[0].evidence
    )


def test_markdown_defect_removed_quote_block_goes_red(session: Session) -> None:
    """Injected defect: a broken Markdown template that drops the evidence
    loop entirely. Proves the parser-based acceptance test above would
    actually go red on evidence loss, rather than passing regardless.
    """
    fixture = build_report_fixture(session)
    report = build_report(session, study_id=fixture.study_id)

    broken_template_source = """\
{% for cluster in report.clusters %}
## Cluster {{ cluster.cluster_id }}: {{ cluster.title }}
{% for item in cluster.evidence %}
(evidence omitted)
{% endfor %}
{% endfor %}
"""
    env = jinja2.Environment(autoescape=False)
    template = env.from_string(broken_template_source)
    broken_output = template.render(report=report, caveat=SIMULATED_PANEL_CAVEAT)

    md_clusters = parse_report_markdown(broken_output)
    assert len(md_clusters) == 1
    assert md_clusters[0].quotes == []  # evidence loss is now visible to the parser


def test_html_defect_removed_quote_block_goes_red(session: Session) -> None:
    fixture = build_report_fixture(session)
    report = build_report(session, study_id=fixture.study_id)

    broken_template_source = """\
{% for cluster in report.clusters %}
<section class="cluster" data-cluster-id="{{ cluster.cluster_id }}">
<h2>Cluster {{ cluster.cluster_id }}: {{ cluster.title }}</h2>
{% for item in cluster.evidence %}
<div class="evidence" data-finding-id="{{ item.finding_id }}">(evidence omitted)</div>
{% endfor %}
</section>
{% endfor %}
"""
    env = jinja2.Environment(autoescape=True)
    template = env.from_string(broken_template_source)
    broken_output = template.render(report=report, caveat=SIMULATED_PANEL_CAVEAT)

    html_clusters, _ = parse_report_html(broken_output)
    assert len(html_clusters) == 1
    assert html_clusters[0].quotes == []  # evidence loss is now visible to the parser


def test_markdown_defect_dropped_cluster_goes_red(session: Session) -> None:
    fixture = build_report_fixture(session)
    report = build_report(session, study_id=fixture.study_id)
    assert len(report.clusters) == 1  # sanity: fixture has exactly one cluster

    broken_template_source = """\
{% for cluster in report.clusters[1:] %}
## Cluster {{ cluster.cluster_id }}: {{ cluster.title }}
{% endfor %}
"""
    env = jinja2.Environment(autoescape=False)
    template = env.from_string(broken_template_source)
    broken_output = template.render(report=report, caveat=SIMULATED_PANEL_CAVEAT)

    md_clusters = parse_report_markdown(broken_output)
    assert len(md_clusters) == 0  # the one cluster this study has was dropped


def test_html_defect_dropped_cluster_goes_red(session: Session) -> None:
    fixture = build_report_fixture(session)
    report = build_report(session, study_id=fixture.study_id)
    assert len(report.clusters) == 1

    broken_template_source = """\
{% for cluster in report.clusters[1:] %}
<section class="cluster" data-cluster-id="{{ cluster.cluster_id }}"></section>
{% endfor %}
"""
    env = jinja2.Environment(autoescape=True)
    template = env.from_string(broken_template_source)
    broken_output = template.render(report=report, caveat=SIMULATED_PANEL_CAVEAT)

    html_clusters, _ = parse_report_html(broken_output)
    assert len(html_clusters) == 0


def test_escaping_hazard_round_trips_faithfully_in_both_formats(
    session: Session,
) -> None:
    """`Turn.content` containing `<`, `&`, `|`, `#`, backticks and an
    embedded newline must survive rendering byte-for-byte, in both formats,
    when parsed (not substring-matched) back out. This is also where format
    parity gets checked, on the fixture most likely to break one renderer
    and not the other.
    """
    fixture = build_report_fixture(session, hazard_quote_on_second_ana_finding=True)
    report = build_report(session, study_id=fixture.study_id)

    md_clusters = parse_report_markdown(render_markdown(report))
    html_clusters, external_refs = parse_report_html(render_html(report))

    assert external_refs == []
    assert ESCAPING_HAZARD_QUOTE in md_clusters[0].quotes
    assert ESCAPING_HAZARD_QUOTE in html_clusters[0].quotes

    assert len(md_clusters) == len(html_clusters) == 1
    assert len(md_clusters[0].quotes) == len(html_clusters[0].quotes) == 3


def test_long_quote_is_kept_whole_in_markdown_and_collapsed_in_html(
    session: Session,
) -> None:
    long_quote = "The persona described the problem at length. " * 20  # > 400 chars
    assert len(long_quote) > 400
    study_id = build_single_finding_fixture(session, quote=long_quote)
    report = build_report(
        session, study_id=study_id, clustering_config=ClusteringConfig()
    )

    md_clusters = parse_report_markdown(render_markdown(report))
    assert md_clusters[0].quotes == [long_quote]  # whole, no truncation

    raw_html = render_html(report)
    assert "<details>" in raw_html
    html_clusters, _ = parse_report_html(raw_html)
    assert html_clusters[0].quotes == [long_quote]  # whole, no truncation


def test_summary_never_appears_as_a_quote(session: Session) -> None:
    summary = "SENTINEL-ANALYST-PARAPHRASE-do-not-quote-this"
    quote = "SENTINEL-VERBATIM-PERSONA-UTTERANCE"
    study_id = build_single_finding_fixture(session, quote=quote, summary=summary)
    report = build_report(session, study_id=study_id)

    md_clusters = parse_report_markdown(render_markdown(report))
    html_clusters, _ = parse_report_html(render_html(report))

    assert summary not in md_clusters[0].quotes
    assert summary not in html_clusters[0].quotes
    assert quote in md_clusters[0].quotes
    assert quote in html_clusters[0].quotes


def test_standing_caveat_present_in_both_formats(session: Session) -> None:
    fixture = build_report_fixture(session)
    report = build_report(session, study_id=fixture.study_id)
    assert SIMULATED_PANEL_CAVEAT in render_markdown(report)
    assert SIMULATED_PANEL_CAVEAT in render_html(report)


def test_no_findings_report_renders_without_crashing(session: Session) -> None:
    """The vacuous-pass trap: an empty report must not be what the
    acceptance test above runs against (it uses a populated fixture), but
    rendering a genuinely empty report must still succeed and say so.
    """
    artefact = models.Artefact(
        name="a.html", kind=ArtefactKind.HTML, content_hash="h1", body="<html/>"
    )
    session.add(artefact)
    session.flush()
    study = models.Study(
        name="empty",
        research_goal="g",
        artefact_id=artefact.id,
        config_hash="c",
        git_sha="f" * 40,
    )
    session.add(study)
    session.flush()
    scenario = models.Scenario(study_id=study.id, task="t", questions=[])
    panel = models.Panel(study_id=study.id, seed=1, size=1, config_yaml="")
    session.add_all([scenario, panel])
    session.flush()
    persona = models.Persona(
        panel_id=panel.id, name="P", segment="s", attributes={}, card_text="c"
    )
    session.add(persona)
    session.flush()
    run = models.Run(
        study_id=study.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        status=RunStatus.COMPLETED,
    )
    session.add(run)
    session.commit()

    report = build_report(session, study_id=study.id)
    md = render_markdown(report)
    html = render_html(report)
    assert "No findings" in md
    assert "No findings" in html
