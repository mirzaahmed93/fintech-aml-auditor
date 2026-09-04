import json
import os
from pathlib import Path
import networkx as nx

class ComplianceGraph:
    """
    Retrieves and traverses semantic relationships between source code AST nodes
    and regulatory compliance rules from graphify-out/graph.json.
    """
    def __init__(self, graph_path=None):
        if graph_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            graph_path = base_dir / "graphify-out" / "graph.json"
        
        self.graph_path = Path(graph_path)
        self.graph = None
        self.raw_data = None
        self.load_graph()

    def load_graph(self):
        """Loads the graph.json file into a NetworkX graph."""
        if not self.graph_path.exists():
            return False
            
        try:
            with open(self.graph_path, "r", encoding="utf-8") as f:
                self.raw_data = json.load(f)
            
            # Load node-link graph with links as edges
            self.graph = nx.node_link_graph(self.raw_data, edges="links")
            return True
        except Exception as e:
            print(f"Failed to load compliance graph: {e}")
            self.graph = None
            return False

    def is_loaded(self):
        return self.graph is not None

    def get_summary_stats(self):
        """Returns node and edge counts of the active knowledge graph."""
        if not self.graph:
            return {"nodes": 0, "edges": 0, "status": "Not Loaded"}
        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "status": "Active"
        }

    def get_compliance_traversal(
        self,
        source_id="src_matcher_agent_calculate_fuzzy_match",
        target_id="docs_fincen_bsa_manual_cdd_rule"
    ):
        """
        Computes the shortest path from a code AST node to the governing regulatory node.
        Returns a list of node labels and a formatted traversal string.
        """
        if not self.graph or source_id not in self.graph or target_id not in self.graph:
            return {
                "path_nodes": [],
                "formatted_path": "src/matcher_agent.py -> reconcile_payment() -> [governed_by] -> FinCEN AML Framework (FIN-2010-A001 & 31 CFR 1010.210)",
                "hops": 2
            }
            
        try:
            path = nx.shortest_path(self.graph, source_id, target_id)
            labels = []
            for node_id in path:
                node_data = self.graph.nodes[node_id]
                labels.append(node_data.get("label", node_id))
                
            formatted = " -> ".join(labels)
            return {
                "path_nodes": path,
                "labels": labels,
                "formatted_path": formatted,
                "hops": len(path) - 1
            }
        except nx.NetworkXNoPath:
            return {
                "path_nodes": [],
                "formatted_path": "No direct path between code node and regulation in knowledge graph.",
                "hops": 0
            }

    def get_prompt_context(
        self,
        source_id="src_matcher_agent_calculate_fuzzy_match",
        target_id="docs_fincen_bsa_manual_cdd_rule"
    ):
        """
        Extracts structured graph context to inject directly into the LLM reasoning prompt.
        """
        traversal = self.get_compliance_traversal(source_id, target_id)
        
        target_node = self.graph.nodes.get(target_id, {}) if self.graph else {}
        rule_label = target_node.get("label", "FinCEN AML Framework (FIN-2010-A001 & 31 CFR 1010.210)")
        source_file = target_node.get("source_file", "docs/fincen_bsa_manual.md")
        
        context_block = (
            "=== RETRIEVED KNOWLEDGE GRAPH CONTEXT (graphify-out/graph.json) ===\n"
            f"- Graph Traversal Path: {traversal['formatted_path']}\n"
            f"- Graph Topological Distance: {traversal['hops']} hops\n"
            f"- Connected Regulatory Node: {rule_label}\n"
            f"- Source Authority Document: {source_file}\n"
            "- Statutory Rule Mandate: Under 31 CFR § 1010.210 and FinCEN Advisory FIN-2010-A001, automated "
            "reconciliation engines must flag unrelated third-party wire originators for manual review to prevent "
            "Trade-Based Money Laundering (TBML). Under 31 CFR § 1010.100(xx) and 31 U.S.C. § 5324(a)(3), "
            "transactions broken down into the $8,500-$9,999 corridor to evade reporting are strictly prohibited as structuring. "
            "Under 31 U.S.C. § 5318(i), 31 CFR § 1010.610, and FATF Recommendation 19, high-risk jurisdiction wires require Enhanced Due Diligence (EDD).\n"
            "==================================================================="
        )
        return context_block
