"""Tests for nogood ID uniqueness after deletion (issue #26).

Validates that _next_nogood_id counter stays correct across:
- Direct network operations (add/delete nogoods)
- SQLite round-trips (storage.py)
- JSON import (api.py import_json)
- Markdown import (import_beliefs.py)
"""

import json
import tempfile
from pathlib import Path

import pytest

from reasons_lib import Justification, Nogood
from reasons_lib.network import Network
from reasons_lib.storage import Storage
from reasons_lib.import_beliefs import import_into_network
from reasons_lib import api


# ---------------------------------------------------------------------------
# Core counter behavior
# ---------------------------------------------------------------------------

class TestNogoodIdCounter:
    """_compute_next_nogood_id derives the correct counter from existing data."""

    def test_empty_nogoods_yields_one(self):
        net = Network()
        net._compute_next_nogood_id()
        assert net._next_nogood_id == 1

    def test_single_nogood(self):
        net = Network()
        net.nogoods.append(Nogood(id="nogood-001", nodes=["a", "b"], discovered=""))
        net._compute_next_nogood_id()
        assert net._next_nogood_id == 2

    def test_gap_in_ids(self):
        """IDs nogood-001 and nogood-005 — counter should be 6, not 3."""
        net = Network()
        net.nogoods.append(Nogood(id="nogood-001", nodes=["a", "b"], discovered=""))
        net.nogoods.append(Nogood(id="nogood-005", nodes=["c", "d"], discovered=""))
        net._compute_next_nogood_id()
        assert net._next_nogood_id == 6

    def test_prefixed_ids_ignored(self):
        """Prefixed IDs like 'agent:nogood-099' use fullmatch, so they don't count."""
        net = Network()
        net.nogoods.append(Nogood(id="agent:nogood-099", nodes=["x", "y"], discovered=""))
        net._compute_next_nogood_id()
        assert net._next_nogood_id == 1

    def test_mixed_prefixed_and_unprefixed(self):
        """Only unprefixed IDs contribute to counter."""
        net = Network()
        net.nogoods.append(Nogood(id="nogood-003", nodes=["a", "b"], discovered=""))
        net.nogoods.append(Nogood(id="agent:nogood-099", nodes=["x", "y"], discovered=""))
        net._compute_next_nogood_id()
        assert net._next_nogood_id == 4

    def test_large_nogood_number(self):
        """Numbers >999 work fine — regex matches any digit count."""
        net = Network()
        net.nogoods.append(Nogood(id="nogood-1500", nodes=["a", "b"], discovered=""))
        net._compute_next_nogood_id()
        assert net._next_nogood_id == 1501

    def test_init_sets_counter_to_one(self):
        """Fresh Network starts with _next_nogood_id = 1."""
        net = Network()
        assert net._next_nogood_id == 1


# ---------------------------------------------------------------------------
# Deletion + re-add scenario (the core bug)
# ---------------------------------------------------------------------------

class TestNogoodIdAfterDeletion:
    """The original bug: deleting a nogood then adding a new one must not collide."""

    def test_delete_middle_then_add(self):
        """Create 3 nogoods, delete middle, recompute, add — get nogood-004."""
        net = Network()
        net.add_node("a", "A")
        net.add_node("b", "B")
        net.add_node("c", "C")
        net.add_node("d", "D")
        net.add_node("e", "E")
        net.add_node("f", "F")
        net.add_node("g", "G")
        net.add_node("h", "H")

        net.add_nogood(["a", "b"])  # nogood-001
        net.add_nogood(["c", "d"])  # nogood-002
        net.add_nogood(["e", "f"])  # nogood-003

        del net.nogoods[1]  # remove nogood-002
        net._compute_next_nogood_id()

        net.add_nogood(["g", "h"])
        assert net.nogoods[-1].id == "nogood-004"

    def test_delete_last_then_add(self):
        """Delete the last nogood, recompute, add — derive from remaining max."""
        net = Network()
        net.add_node("a", "A")
        net.add_node("b", "B")
        net.add_node("c", "C")
        net.add_node("d", "D")

        net.add_nogood(["a", "b"])  # nogood-001
        net.add_nogood(["c", "d"])  # nogood-002

        del net.nogoods[-1]  # remove nogood-002
        net._compute_next_nogood_id()
        assert net._next_nogood_id == 2

        net.add_node("e", "E")
        net.add_node("f", "F")
        net.add_nogood(["e", "f"])
        assert net.nogoods[-1].id == "nogood-002"

    def test_delete_all_then_add(self):
        """When all nogoods are deleted, counter resets to 1 (derive on load, not persist)."""
        net = Network()
        net.add_node("a", "A")
        net.add_node("b", "B")

        net.add_nogood(["a", "b"])  # nogood-001
        net.nogoods.clear()
        net._compute_next_nogood_id()

        net.add_node("c", "C")
        net.add_node("d", "D")
        net.add_nogood(["c", "d"])
        assert net.nogoods[-1].id == "nogood-001"

    def test_sequential_adds_without_deletion(self):
        """Normal append-only usage still produces sequential IDs."""
        net = Network()
        net.add_node("a", "A")
        net.add_node("b", "B")
        net.add_node("c", "C")
        net.add_node("d", "D")

        net.add_nogood(["a", "b"])
        net.add_nogood(["c", "d"])

        assert net.nogoods[0].id == "nogood-001"
        assert net.nogoods[1].id == "nogood-002"


# ---------------------------------------------------------------------------
# SQLite round-trip (storage.py)
# ---------------------------------------------------------------------------

class TestNogoodIdStorageRoundTrip:
    """Counter continuity across save/load cycle."""

    def test_save_load_then_add(self, tmp_path):
        """Save a network with nogoods, reload, add new — no collision."""
        db_path = tmp_path / "test.db"
        net = Network()
        net.add_node("a", "A")
        net.add_node("b", "B")
        net.add_node("c", "C")
        net.add_node("d", "D")

        net.add_nogood(["a", "b"])  # nogood-001
        net.add_nogood(["c", "d"])  # nogood-002

        store = Storage(db_path)
        store.save(net)
        loaded = store.load()

        assert loaded._next_nogood_id == 3

        loaded.add_node("e", "E")
        loaded.add_node("f", "F")
        loaded.add_nogood(["e", "f"])
        assert loaded.nogoods[-1].id == "nogood-003"
        store.close()

    def test_save_load_with_gaps(self, tmp_path):
        """Save with a gap, load — counter picks up from max."""
        db_path = tmp_path / "test.db"
        net = Network()
        net.add_node("a", "A")
        net.add_node("b", "B")

        net.nogoods.append(Nogood(id="nogood-001", nodes=["a", "b"], discovered=""))
        net.nogoods.append(Nogood(id="nogood-005", nodes=["a", "b"], discovered=""))
        net._compute_next_nogood_id()

        store = Storage(db_path)
        store.save(net)
        loaded = store.load()

        assert loaded._next_nogood_id == 6
        store.close()


# ---------------------------------------------------------------------------
# JSON import (api.py import_json)
# ---------------------------------------------------------------------------

class TestNogoodIdJsonImport:
    """Counter set correctly after import_json."""

    def test_import_json_then_add_nogood(self, tmp_path):
        """Import a JSON with nogoods, then add_nogood — no collision."""
        db_src = str(tmp_path / "src.db")
        db_dst = str(tmp_path / "dst.db")
        json_file = str(tmp_path / "export.json")

        api.init_db(db_path=db_src)
        api.add_node("a", "A", db_path=db_src)
        api.add_node("b", "B", db_path=db_src)
        api.add_node("c", "C", db_path=db_src)
        api.add_node("d", "D", db_path=db_src)
        api.add_nogood(["a", "b"], db_path=db_src)
        api.add_nogood(["c", "d"], db_path=db_src)

        data = api.export_network(db_path=db_src)
        Path(json_file).write_text(json.dumps(data))

        api.init_db(db_path=db_dst)
        api.import_json(json_file, db_path=db_dst)

        api.add_node("e", "E", db_path=db_dst)
        api.add_node("f", "F", db_path=db_dst)
        result = api.add_nogood(["e", "f"], db_path=db_dst)

        assert result["nogood_id"] == "nogood-003"

    def test_import_json_counter_on_network(self, tmp_path):
        """Directly verify the counter on the Network after import_json flow."""
        db_path = str(tmp_path / "test.db")
        json_file = str(tmp_path / "data.json")

        data = {
            "nodes": {
                "x": {"text": "X", "truth_value": "IN", "justifications": [], "source": "", "source_hash": "", "date": "", "metadata": {}},
                "y": {"text": "Y", "truth_value": "IN", "justifications": [], "source": "", "source_hash": "", "date": "", "metadata": {}},
            },
            "nogoods": [
                {"id": "nogood-003", "nodes": ["x", "y"], "discovered": "", "resolution": ""},
            ],
            "repos": {},
        }
        Path(json_file).write_text(json.dumps(data))

        api.init_db(db_path=db_path)
        api.import_json(json_file, db_path=db_path)

        store = Storage(db_path)
        loaded = store.load()
        assert loaded._next_nogood_id == 4
        store.close()


# ---------------------------------------------------------------------------
# Markdown import (import_beliefs.py)
# ---------------------------------------------------------------------------

BELIEFS_WITH_NOGOODS = """\
# Belief Registry

## Claims

### alpha [IN] OBSERVATION
Alpha premise
- Source: test/alpha.md

### beta [IN] OBSERVATION
Beta premise
- Source: test/beta.md

### gamma [IN] OBSERVATION
Gamma premise
- Source: test/gamma.md

### delta [IN] OBSERVATION
Delta premise
- Source: test/delta.md
"""

NOGOODS_MD = """\
# Nogoods

### nogood-005: Alpha vs Beta
- Discovered: 2026-04-23
- Resolution: Unresolved
- Affects: alpha, beta
"""


class TestNogoodIdBeliefImport:
    """Counter set correctly after import_beliefs."""

    def test_import_beliefs_then_add_nogood(self):
        """Import beliefs.md with nogood-005, then add_nogood — next is nogood-006."""
        net = Network()
        import_into_network(net, BELIEFS_WITH_NOGOODS, NOGOODS_MD)

        assert len(net.nogoods) == 1
        assert net.nogoods[0].id == "nogood-005"
        assert net._next_nogood_id == 6

        net.add_nogood(["gamma", "delta"])
        assert net.nogoods[-1].id == "nogood-006"

    def test_import_beliefs_no_nogoods(self):
        """Import with no nogoods section — counter stays at 1."""
        net = Network()
        import_into_network(net, BELIEFS_WITH_NOGOODS)

        assert net._next_nogood_id == 1

    def test_import_beliefs_then_add_multiple(self):
        """Import with nogood-005, add two more — nogood-006, nogood-007."""
        net = Network()
        import_into_network(net, BELIEFS_WITH_NOGOODS, NOGOODS_MD)

        net.add_nogood(["gamma", "delta"])
        assert net.nogoods[-1].id == "nogood-006"

        net.add_node("e", "E")
        net.add_node("f", "F")
        net.add_nogood(["e", "f"])
        assert net.nogoods[-1].id == "nogood-007"


# ---------------------------------------------------------------------------
# Formatting edge cases
# ---------------------------------------------------------------------------

class TestNogoodIdFormatting:
    """Verify ID formatting with various numeric widths."""

    def test_three_digit_padding(self):
        net = Network()
        net.add_node("a", "A")
        net.add_node("b", "B")
        net.add_nogood(["a", "b"])
        assert net.nogoods[0].id == "nogood-001"

    def test_four_digit_number(self):
        """Counter at 1000 produces nogood-1000 (no truncation)."""
        net = Network()
        net._next_nogood_id = 1000
        net.add_node("a", "A")
        net.add_node("b", "B")
        net.add_nogood(["a", "b"])
        assert net.nogoods[0].id == "nogood-1000"

    def test_counter_increment_is_monotonic(self):
        """Each call to add_nogood increments the counter."""
        net = Network()
        for i in range(5):
            net.add_node(f"n{i*2}", f"N{i*2}")
            net.add_node(f"n{i*2+1}", f"N{i*2+1}")
            net.add_nogood([f"n{i*2}", f"n{i*2+1}"])

        ids = [ng.id for ng in net.nogoods]
        assert ids == [f"nogood-{i:03d}" for i in range(1, 6)]
