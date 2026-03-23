"""Tests for export-markdown."""

from reasons_lib import Justification
from reasons_lib.network import Network
from reasons_lib.export_markdown import export_markdown


class TestExportMarkdown:

    def test_empty_network(self):
        net = Network()
        md = export_markdown(net)
        assert "# Belief Registry" in md
        assert "## Claims" in md

    def test_premise(self):
        net = Network()
        net.add_node("a", "Premise A", source="repo/file.md", source_hash="abc123", date="2026-03-17")
        md = export_markdown(net)
        assert "### a [IN] OBSERVATION" in md
        assert "Premise A" in md
        assert "- Source: repo/file.md" in md
        assert "- Source hash: abc123" in md
        assert "- Date: 2026-03-17" in md

    def test_derived_node(self):
        net = Network()
        net.add_node("a", "Premise A")
        net.add_node("b", "Derived B", justifications=[Justification(type="SL", antecedents=["a"])])
        md = export_markdown(net)
        assert "### b [IN] DERIVED" in md
        assert "- Depends on: a" in md

    def test_retracted_node(self):
        net = Network()
        net.add_node("a", "Premise A")
        net.retract("a")
        md = export_markdown(net)
        assert "### a [OUT] OBSERVATION" in md

    def test_stale_metadata(self):
        net = Network()
        net.add_node("a", "Old belief", metadata={"stale_reason": "superseded", "superseded_by": "b"})
        net.retract("a")
        md = export_markdown(net)
        assert "### a [STALE]" in md
        assert "- Stale reason: superseded" in md
        assert "- Superseded by: b" in md

    def test_in_before_out(self):
        net = Network()
        net.add_node("a", "Premise A")
        net.add_node("b", "Premise B")
        net.retract("b")
        md = export_markdown(net)
        a_pos = md.index("### a")
        b_pos = md.index("### b")
        assert a_pos < b_pos

    def test_nogoods_section(self):
        net = Network()
        net.add_node("a", "Premise A")
        net.add_node("b", "Premise B")
        net.add_nogood(["a", "b"])
        md = export_markdown(net)
        assert "## Nogoods" in md
        assert "nogood-001" in md

    def test_beliefs_type_preserved(self):
        net = Network()
        net.add_node("a", "A warning", metadata={"beliefs_type": "WARNING"})
        md = export_markdown(net)
        assert "### a [IN] WARNING" in md

    def test_multiple_antecedents(self):
        net = Network()
        net.add_node("a", "Premise A")
        net.add_node("b", "Premise B")
        net.add_node("c", "Derived C", justifications=[
            Justification(type="SL", antecedents=["a", "b"])
        ])
        md = export_markdown(net)
        assert "- Depends on: a, b" in md
