"""Tests for CLI command handlers via main()."""

import json
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from reasons_lib.cli import main


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def run_cli(*args, db_path=None):
    argv = ["reasons"]
    if db_path:
        argv += ["--db", db_path]
    argv += list(args)
    stdout, stderr = StringIO(), StringIO()
    with patch.object(sys, "argv", argv), \
         patch.object(sys, "stdout", stdout), \
         patch.object(sys, "stderr", stderr):
        try:
            main()
        except SystemExit as e:
            return stdout.getvalue(), stderr.getvalue(), e.code
    return stdout.getvalue(), stderr.getvalue(), 0


class TestInit:

    def test_init_creates_db(self, db_path):
        out, err, code = run_cli("init", db_path=db_path)
        assert code == 0
        assert "Initialized" in out

    def test_init_refuses_existing(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("init", db_path=db_path)
        assert code == 1
        assert "--force" in err

    def test_init_force(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("init", "--force", db_path=db_path)
        assert code == 0
        assert "Initialized" in out


class TestAdd:

    def test_add_premise(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("add", "a", "Premise A", db_path=db_path)
        assert code == 0
        assert "Added a [IN]" in out
        assert "premise" in out.lower()

    def test_add_derived(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "Premise A", db_path=db_path)
        out, err, code = run_cli("add", "b", "Derived B", "--sl", "a", db_path=db_path)
        assert code == 0
        assert "Added b [IN]" in out

    def test_add_duplicate_fails(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        out, err, code = run_cli("add", "a", "A again", db_path=db_path)
        assert code == 1
        assert "Error" in err

    def test_add_with_access_tags(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("add", "a", "Tagged", "--access-tags", "finance,hr", db_path=db_path)
        assert code == 0
        assert "Added a [IN]" in out

    def test_add_multi_premise_tip(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", db_path=db_path)
        run_cli("add", "c", "C", db_path=db_path)
        out, err, code = run_cli("add", "d", "D", "--sl", "a,b,c", db_path=db_path)
        assert code == 0
        assert "Tip" in out
        assert "--any" in out


class TestAddJustification:

    def test_add_justification(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", db_path=db_path)
        out, err, code = run_cli("add-justification", "b", "--sl", "a", db_path=db_path)
        assert code == 0
        assert "Added justification to b" in out

    def test_add_justification_missing_node(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("add-justification", "missing", "--sl", "a", db_path=db_path)
        assert code == 1
        assert "Error" in err


class TestRetractAssert:

    def test_retract(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        out, err, code = run_cli("retract", "a", db_path=db_path)
        assert code == 0
        assert "Retracted a" in out

    def test_retract_already_out(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("retract", "a", db_path=db_path)
        out, err, code = run_cli("retract", "a", db_path=db_path)
        assert code == 0
        assert "already OUT" in out

    def test_retract_cascade(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)
        out, err, code = run_cli("retract", "a", db_path=db_path)
        assert code == 0
        assert "Went OUT" in out
        assert "b" in out

    def test_retract_with_reason(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        out, err, code = run_cli("retract", "a", "--reason", "Fixed in PR", db_path=db_path)
        assert code == 0

    def test_retract_missing(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("retract", "missing", db_path=db_path)
        assert code == 1

    def test_assert(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("retract", "a", db_path=db_path)
        out, err, code = run_cli("assert", "a", db_path=db_path)
        assert code == 0
        assert "Asserted a" in out

    def test_assert_already_in(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        out, err, code = run_cli("assert", "a", db_path=db_path)
        assert code == 0
        assert "already IN" in out

    def test_assert_cascade(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)
        run_cli("retract", "a", db_path=db_path)
        out, err, code = run_cli("assert", "a", db_path=db_path)
        assert code == 0
        assert "Went IN" in out
        assert "b" in out


class TestStatus:

    def test_status_empty(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("status", db_path=db_path)
        assert code == 0
        assert "No nodes" in out

    def test_status_with_nodes(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "Premise A", db_path=db_path)
        run_cli("add", "b", "Derived B", "--sl", "a", db_path=db_path)
        out, err, code = run_cli("status", db_path=db_path)
        assert code == 0
        assert "[+] a" in out
        assert "[+] b" in out
        assert "2/2 IN" in out

    def test_status_visible_to(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "pub", "Public", db_path=db_path)
        run_cli("add", "fin", "Finance", "--access-tags", "finance", db_path=db_path)
        out, err, code = run_cli("status", "--visible-to", "public", db_path=db_path)
        assert code == 0
        assert "pub" in out
        assert "fin" not in out


class TestShow:

    def test_show_premise(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "Premise A", db_path=db_path)
        out, err, code = run_cli("show", "a", db_path=db_path)
        assert code == 0
        assert "ID:     a" in out
        assert "Text:   Premise A" in out
        assert "Status: IN" in out
        assert "Premise (no justifications)" in out

    def test_show_derived(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)
        out, err, code = run_cli("show", "b", db_path=db_path)
        assert code == 0
        assert "SL(a)" in out

    def test_show_missing(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("show", "missing", db_path=db_path)
        assert code == 1
        assert "Error" in err

    def test_show_access_denied(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "fin", "Finance", "--access-tags", "finance", db_path=db_path)
        out, err, code = run_cli("show", "fin", "--visible-to", "hr", db_path=db_path)
        assert code == 1
        assert "Access denied" in err

    def test_show_dependents(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)
        out, err, code = run_cli("show", "a", db_path=db_path)
        assert code == 0
        assert "Dependents: b" in out

    def test_show_retract_reason(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("retract", "a", "--reason", "Fixed in PR #1", db_path=db_path)
        out, err, code = run_cli("show", "a", db_path=db_path)
        assert code == 0
        assert "Retract reason: Fixed in PR #1" in out


class TestExplain:

    def test_explain_premise(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        out, err, code = run_cli("explain", "a", db_path=db_path)
        assert code == 0
        assert "[+] a" in out

    def test_explain_derived(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)
        out, err, code = run_cli("explain", "b", db_path=db_path)
        assert code == 0
        assert "[+] b" in out
        assert "antecedents: a" in out

    def test_explain_missing(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("explain", "missing", db_path=db_path)
        assert code == 1

    def test_explain_access_denied(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "fin", "Finance", "--access-tags", "finance", db_path=db_path)
        out, err, code = run_cli("explain", "fin", "--visible-to", "hr", db_path=db_path)
        assert code == 1
        assert "Access denied" in err


class TestTrace:

    def test_trace_premise(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        out, err, code = run_cli("trace", "a", db_path=db_path)
        assert code == 0
        assert "premise" in out.lower()

    def test_trace_derived(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)
        out, err, code = run_cli("trace", "b", db_path=db_path)
        assert code == 0
        assert "1 premise" in out
        assert "[+] a" in out

    def test_trace_access_denied(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "fin", "Finance", "--access-tags", "finance", db_path=db_path)
        out, err, code = run_cli("trace", "fin", "--visible-to", "hr", db_path=db_path)
        assert code == 1
        assert "Access denied" in err


class TestTraceAccessTags:

    def test_trace_access_tags(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", "--access-tags", "finance", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)
        out, err, code = run_cli("trace-access-tags", "b", db_path=db_path)
        assert code == 0
        assert "finance" in out

    def test_trace_access_tags_unrestricted(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        out, err, code = run_cli("trace-access-tags", "a", db_path=db_path)
        assert code == 0
        assert "unrestricted" in out

    def test_trace_access_tags_missing(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("trace-access-tags", "missing", db_path=db_path)
        assert code == 1


class TestList:

    def test_list_all(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)
        out, err, code = run_cli("list", db_path=db_path)
        assert code == 0
        assert "2 nodes" in out

    def test_list_premises(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)
        out, err, code = run_cli("list", "--premises", db_path=db_path)
        assert code == 0
        assert "1 node" in out
        assert "a" in out

    def test_list_status_filter(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", db_path=db_path)
        run_cli("retract", "b", db_path=db_path)
        out, err, code = run_cli("list", "--status", "OUT", db_path=db_path)
        assert code == 0
        assert "b" in out
        assert "1 node" in out

    def test_list_empty(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("list", db_path=db_path)
        assert code == 0
        assert "No matching" in out


class TestSearchLookup:

    def test_search(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "The quick brown fox", db_path=db_path)
        out, err, code = run_cli("search", "fox", db_path=db_path)
        assert code == 0
        assert "a" in out

    def test_lookup(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "my-belief", "Something important", db_path=db_path)
        out, err, code = run_cli("lookup", "important", db_path=db_path)
        assert code == 0
        assert "my-belief" in out


class TestExport:

    def test_export_json(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        out, err, code = run_cli("export", db_path=db_path)
        assert code == 0
        data = json.loads(out)
        assert "a" in data["nodes"]

    def test_export_markdown(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "Premise A", db_path=db_path)
        out, err, code = run_cli("export-markdown", db_path=db_path)
        assert code == 0
        assert "a" in out

    def test_export_markdown_to_file(self, db_path, tmp_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        out_file = str(tmp_path / "out.md")
        out, err, code = run_cli("export-markdown", "-o", out_file, db_path=db_path)
        assert code == 0
        assert "Written to" in out
        from pathlib import Path
        assert "a" in Path(out_file).read_text()


class TestCompact:

    def test_compact(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "Premise A", db_path=db_path)
        out, err, code = run_cli("compact", db_path=db_path)
        assert code == 0
        assert "a" in out


class TestChallenge:

    def test_challenge_and_defend(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "claim", "A bold claim", db_path=db_path)
        out, err, code = run_cli("challenge", "claim", "I disagree", db_path=db_path)
        assert code == 0
        assert "Challenged claim" in out
        assert "challenge-claim" in out

        out, err, code = run_cli("defend", "claim", "challenge-claim", "New evidence", db_path=db_path)
        assert code == 0
        assert "Defended claim" in out


class TestNogood:

    def test_nogood(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", db_path=db_path)
        out, err, code = run_cli("nogood", "a", "b", db_path=db_path)
        assert code == 0
        assert "Recorded" in out
        assert "a" in out and "b" in out

    def test_nogood_missing_node(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("nogood", "x", "y", db_path=db_path)
        assert code == 1


class TestWhatIf:

    def test_what_if_retract(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)
        out, err, code = run_cli("what-if", "retract", "a", db_path=db_path)
        assert code == 0
        assert "What if" in out
        assert "[-] b" in out
        assert "NOT modified" in out

    def test_what_if_retract_already_out(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("retract", "a", db_path=db_path)
        out, err, code = run_cli("what-if", "retract", "a", db_path=db_path)
        assert code == 0
        assert "already OUT" in out

    def test_what_if_assert(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)
        run_cli("retract", "a", db_path=db_path)
        out, err, code = run_cli("what-if", "assert", "a", db_path=db_path)
        assert code == 0
        assert "What if" in out
        assert "[+] b" in out

    def test_what_if_no_effect(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        out, err, code = run_cli("what-if", "retract", "a", db_path=db_path)
        assert code == 0
        assert "no other nodes" in out


class TestSupersede:

    def test_supersede(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "old", "Old belief", db_path=db_path)
        run_cli("add", "new", "New belief", db_path=db_path)
        out, err, code = run_cli("supersede", "old", "new", db_path=db_path)
        assert code == 0
        assert "Superseded old by new" in out


class TestConvertToPremise:

    def test_convert_to_premise(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)
        out, err, code = run_cli("convert-to-premise", "b", db_path=db_path)
        assert code == 0
        assert "Converted b to premise" in out
        assert "stripped 1 justification" in out


class TestPropagate:

    def test_propagate_current(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        out, err, code = run_cli("propagate", db_path=db_path)
        assert code == 0
        assert "current" in out


class TestLog:

    def test_log_empty(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("log", db_path=db_path)
        assert code == 0
        assert "No propagation events" in out


class TestRepos:

    def test_add_repo_and_list(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("add-repo", "myrepo", "/tmp/myrepo", db_path=db_path)
        assert code == 0
        assert "Added repo myrepo" in out

        out, err, code = run_cli("repos", db_path=db_path)
        assert code == 0
        assert "myrepo" in out
        assert "1 repo" in out

    def test_repos_empty(self, db_path):
        run_cli("init", db_path=db_path)
        out, err, code = run_cli("repos", db_path=db_path)
        assert code == 0
        assert "No repos" in out


class TestImportExportJson:

    def test_import_json_roundtrip(self, db_path, tmp_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", "--sl", "a", db_path=db_path)

        out, _, _ = run_cli("export", db_path=db_path)
        json_file = str(tmp_path / "export.json")
        from pathlib import Path
        Path(json_file).write_text(out)

        db2 = str(tmp_path / "test2.db")
        run_cli("init", db_path=db2)
        out, err, code = run_cli("import-json", json_file, db_path=db2)
        assert code == 0
        assert "Imported 2 nodes" in out


class TestSummarize:

    def test_summarize(self, db_path):
        run_cli("init", db_path=db_path)
        run_cli("add", "a", "A", db_path=db_path)
        run_cli("add", "b", "B", db_path=db_path)
        out, err, code = run_cli("summarize", "s", "Summary of A and B", "--over", "a,b", db_path=db_path)
        assert code == 0
        assert "Created summary s" in out
        assert "2 nodes" in out


class TestNoCommand:

    def test_no_command_prints_help(self):
        out, err, code = run_cli()
        assert code == 1
