"""Tests for compact summary."""

from reasons_lib import Justification
from reasons_lib.network import Network
from reasons_lib.compact import compact


class TestCompact:

    def test_empty_network(self):
        net = Network()
        result = compact(net)
        assert "Belief State Summary" in result
        assert "0 nodes tracked" in result

    def test_includes_nogoods(self):
        net = Network()
        net.add_node("a", "Premise A")
        net.add_node("b", "Premise B")
        net.add_nogood(["a", "b"])
        result = compact(net)
        assert "## Nogoods" in result
        assert "nogood-001" in result

    def test_includes_out_nodes(self):
        net = Network()
        net.add_node("a", "Premise A")
        net.retract("a")
        result = compact(net)
        assert "## OUT (retracted)" in result
        assert "a: Premise A" in result

    def test_includes_in_nodes(self):
        net = Network()
        net.add_node("a", "Premise A")
        result = compact(net)
        assert "## IN (active)" in result
        assert "a: Premise A" in result

    def test_truncates_long_text(self):
        net = Network()
        long_text = "A" * 200
        net.add_node("a", long_text)
        result = compact(net, truncate=True)
        assert "..." in result
        assert "A" * 200 not in result

    def test_no_truncate(self):
        net = Network()
        long_text = "A" * 200
        net.add_node("a", long_text)
        result = compact(net, truncate=False)
        assert "A" * 200 in result

    def test_budget_limits_in_nodes(self):
        net = Network()
        for i in range(50):
            net.add_node(f"node-{i:03d}", f"This is node number {i} with some text")
        result = compact(net, budget=100)
        assert "more IN nodes omitted" in result

    def test_most_depended_on_first(self):
        net = Network()
        net.add_node("root", "Root premise")
        net.add_node("leaf", "Leaf node")
        net.add_node("dep", "Depends on root", justifications=[
            Justification(type="SL", antecedents=["root"])
        ])
        result = compact(net, budget=5000)
        # root has 1 dependent (dep), leaf has 0
        root_pos = result.index("root:")
        leaf_pos = result.index("leaf:")
        assert root_pos < leaf_pos

    def test_shows_dependencies(self):
        net = Network()
        net.add_node("a", "Premise A")
        net.add_node("b", "Derived B", justifications=[
            Justification(type="SL", antecedents=["a"])
        ])
        result = compact(net, budget=5000)
        assert "<- a" in result

    def test_shows_dependent_count(self):
        net = Network()
        net.add_node("a", "Premise A")
        net.add_node("b", "Derived B", justifications=[
            Justification(type="SL", antecedents=["a"])
        ])
        net.add_node("c", "Derived C", justifications=[
            Justification(type="SL", antecedents=["a"])
        ])
        result = compact(net, budget=5000)
        assert "(2 dependents)" in result

    def test_stale_reason_in_out(self):
        net = Network()
        net.add_node("a", "Old belief", metadata={"stale_reason": "new data"})
        net.retract("a")
        result = compact(net)
        assert "stale: new data" in result

    def test_token_count_line(self):
        net = Network()
        net.add_node("a", "Premise A")
        result = compact(net, budget=500)
        assert "Token count:" in result
        assert "/ 500 budget" in result
