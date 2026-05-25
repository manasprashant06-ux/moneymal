"""
Hybrid Sentinel — Financial Forensics Engine v5.0
Recall-Optimized Detection Architecture

Pipeline stages:
  Stage 0  — Data Loading + Adaptive Statistics
  Stage 1  — Candidate Detection  (cycles, shells, smurfing, structuring, velocity)
  Stage 2  — Business Immunity    (payroll + merchant identification)
  Stage 3  — Ring Consolidation   (Jaccard merge, micro-ring filter)
  Stage 4  — Composite Risk Scoring (weighted multi-pattern score)
  Stage 5  — Suppression          (immunity filter AFTER scoring, cannot override strong fraud)

Design principles:
  • Detection and suppression are FULLY separated
  • Soft scoring — candidates contribute partial scores (no hard gate rejection)
  • Adaptive thresholds — scaled relative to dataset statistics
  • Ring consolidation — overlapping rings merged via Jaccard similarity
  • Suppression only applies when immunity is strong AND no fraud signal exceeds threshold
  • Stability — deterministic ring_id, no nulls, no duplicates

Performance: optimised for <30s on 15K+ transactions.
"""

import time
from collections import defaultdict
from datetime import timedelta
from itertools import count
from statistics import median

import numpy as np
import pandas as pd
import networkx as nx
from sklearn.ensemble import IsolationForest
import yaml
from pathlib import Path


# ====================================================================== #
#  UNION-FIND (Disjoint Set) for merging overlapping cycles              #
# ====================================================================== #
class UnionFind:
    """Weighted Quick-Union with path compression."""

    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def groups(self) -> dict[str, list[str]]:
        clusters: dict[str, list[str]] = defaultdict(list)
        for node in self.parent:
            clusters[self.find(node)].append(node)
        return dict(clusters)


# ====================================================================== #
#  HELPER FUNCTIONS                                                       #
# ====================================================================== #

def _get_edges_between(G, u, v):
    """Return all edge data dicts for edges u → v in a MultiDiGraph."""
    edges = []
    if G.has_edge(u, v):
        for _, data in G[u][v].items():
            edges.append(data)
    return edges


def _external_degree_in_window(G, node, cycle_nodes_set, ts_min, ts_max, limit):
    """Count transactions with non-cycle nodes inside the time window."""
    ext_count = 0
    for pred in G.predecessors(node):
        if pred in cycle_nodes_set:
            continue
        for _, d in G[pred][node].items():
            if ts_min <= d["timestamp"] <= ts_max:
                ext_count += 1
                if ext_count > limit:
                    return ext_count
    for succ in G.successors(node):
        if succ in cycle_nodes_set:
            continue
        for _, d in G[node][succ].items():
            if ts_min <= d["timestamp"] <= ts_max:
                ext_count += 1
                if ext_count > limit:
                    return ext_count
    return ext_count


def _canonicalize_cycle(path):
    """Minimal rotation for deduplication."""
    min_idx = path.index(min(path))
    return tuple(path[min_idx:] + path[:min_idx])


def _coefficient_of_variation(values):
    if len(values) < 2:
        return 0.0
    mean_val = sum(values) / len(values)
    if mean_val == 0:
        return 0.0
    variance = sum((v - mean_val) ** 2 for v in values) / len(values)
    return (variance ** 0.5) / mean_val


def _jaccard_similarity(set_a, set_b):
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


# ====================================================================== #
#  FORENSICS ENGINE                                                       #
# ====================================================================== #
class ForensicsEngine:

    REQUIRED_COLUMNS = [
        "transaction_id", "sender_id", "receiver_id", "amount", "timestamp"
    ]

    MAX_RING_SIZE = 30      # Union-Find cap: prevents mega-rings
    MAX_SCC_SIZE = 200      # Skip SCCs larger than this for cycle search
    MAX_CYCLES = 2000       # Global cycle cap
    MAX_DEPTH = 5           # Max cycle length
    MAX_OPS_PER_NODE = 500  # Per-node DFS budget (reduced from 5000 for speed)
    MAX_SHELL_RINGS = 50    # Cap on shell network rings
    MAX_SMURF_RING_SIZE = 15  # Max members per smurfing ring

    CYCLE_TIME_BUDGET = 80.0  # Max seconds allowed for full cycle detection stage

    FLAG_THRESHOLD = 25     # Minimum score to be flagged

    def __init__(self):
        self.df: pd.DataFrame | None = None
        self.G: nx.MultiDiGraph | None = None

        self.account_patterns: dict[str, set[str]] = defaultdict(set)
        self.fraud_rings: list[dict] = []
        self.suspicion_scores: dict[str, float] = {}

        self._velocity_accounts: set[str] = set()
        self._velocity_24h_accounts: set[str] = set()
        self._low_variance_accounts: set[str] = set()
        self._high_degree_hubs: set[str] = set()
        self._immune_accounts: set[str] = set()
        self._immune_types: dict[str, str] = {}  # account -> 'payroll' or 'merchant'

        self._ring_counter = count(1)
        self._explanations: dict[str, str] = {}

        self._candidate_rings: list[dict] = []  # Candidate rings before arbitration
        self._smurf_candidates: list[dict] = []

        self._start_time: float = 0.0
        self._processing_time: float = 0.0

        # Adaptive dataset statistics (Phase 3)
        self._median_degree: float = 2.0
        self._degree_std: float = 1.0
        self._median_tx_amount: float = 1000.0
        self._amount_std: float = 500.0

        self.account_thresholds = {}
        try:
            yaml_path = Path(__file__).parent / "account_thresholds.yaml"
            if yaml_path.exists():
                with open(yaml_path, 'r') as f:
                    self.account_thresholds = yaml.safe_load(f)
        except Exception:
            pass
        self._dataset_time_span: float = 0.0
        self._adaptive_ext_degree_limit: int = 2

    # ================================================================== #
    #  1. DATA LOADING                                                    #
    # ================================================================== #

    COLUMN_ALIASES = {
        'transaction_id': ['txn_id', 'id', 'ref_no', 'trx_id'],
        'sender_id': ['from_account', 'payer_id', 'originator', 'sender'],
        'receiver_id': ['to_account', 'payee_id', 'beneficiary', 'destination'],
        'amount': ['txn_amount', 'transaction_amount', 'amt', 'value'],
        'timestamp': ['date', 'txn_date', 'created_at', 'datetime'],
        'account_type': ['acc_type', 'type'],
        'credit_limit': ['limit']
    }

    def load_data(self, df: pd.DataFrame) -> None:
        df = df.copy()
        
        # Fuzzy / alias column matching
        df_cols_lower = {c.lower(): c for c in df.columns}
        rename_map = {}
        for canonical, aliases in self.COLUMN_ALIASES.items():
            if canonical in df_cols_lower:
                rename_map[df_cols_lower[canonical]] = canonical
            else:
                for alias in aliases:
                    if alias in df_cols_lower:
                        rename_map[df_cols_lower[alias]] = canonical
                        break
        df.rename(columns=rename_map, inplace=True)

        missing = [c for c in self.REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f'Missing required columns: {missing}')

        df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df.dropna(subset=['amount', 'timestamp'], inplace=True)
        df['transaction_id'] = df['transaction_id'].astype(str)
        df['sender_id'] = df['sender_id'].astype(str)
        df['receiver_id'] = df['receiver_id'].astype(str)
        df.sort_values('timestamp', inplace=True)
        df.reset_index(drop=True, inplace=True)
        self.df = df

        # MultiDiGraph preserves parallel edges between the same pair
        # Vectorized construction — avoids slow iterrows()
        self.G = nx.MultiDiGraph()
        senders = df['sender_id'].values
        receivers = df['receiver_id'].values
        tx_ids = df['transaction_id'].values
        amounts = df['amount'].values
        timestamps = df['timestamp'].values
        for i in range(len(df)):
            self.G.add_edge(
                senders[i],
                receivers[i],
                transaction_id=tx_ids[i],
                amount=float(amounts[i]),
                timestamp=pd.Timestamp(timestamps[i]),
            )

        # Phase 3: Compute adaptive dataset statistics
        self._compute_dataset_stats()
    # ================================================================== #
    #  PHASE 3: ADAPTIVE THRESHOLD COMPUTATION                            #
    # ================================================================== #
    def _compute_dataset_stats(self) -> None:
        """
        Compute dataset-level statistics for adaptive threshold scaling.
        Runs once after data loading.
        """
        if self.G is None or self.df is None:
            return

        # Degree statistics
        degrees = [self.G.in_degree(n) + self.G.out_degree(n) for n in self.G.nodes()]
        if degrees:
            self._median_degree = float(np.median(degrees))
            self._degree_std = float(np.std(degrees))
        else:
            self._median_degree = 2.0
            self._degree_std = 1.0

        # Amount statistics
        amounts = self.df["amount"].values
        if len(amounts) > 0:
            self._median_tx_amount = float(np.median(amounts))
            self._amount_std = float(np.std(amounts))
        else:
            self._median_tx_amount = 1000.0
            self._amount_std = 500.0

        # Time span
        ts_min = self.df["timestamp"].min()
        ts_max = self.df["timestamp"].max()
        self._dataset_time_span = (ts_max - ts_min).total_seconds()

        # Adaptive external degree limit for cycles
        self._adaptive_ext_degree_limit = max(
            2, int(self._median_degree + 1.5 * self._degree_std)
        )

    # ================================================================== #
    #  2. CYCLE DETECTION — Multi-Constraint Validated + Union-Find       #
    # ================================================================== #
    def detect_cycles(self) -> None:
        """
        Bounded DFS cycle detection (length 3–5) with multi-constraint
        validation, merged via Union-Find into rings.
        Phase 2: relaxed external degree constraint using adaptive limit.
        """
        if self.G is None:
            return

        # ---- Build degree-filtered adjacency -------------------------
        # Adaptive upper limit: scale with dataset density
        max_cycle_degree = max(20, int(self._median_degree + 2.0 * self._degree_std))
        eligible = set()
        for n in self.G.nodes():
            total_deg = self.G.in_degree(n) + self.G.out_degree(n)
            if 2 <= total_deg <= max_cycle_degree:
                eligible.add(n)

        adjacency = defaultdict(set)
        for u, v, _ in self.G.edges(keys=True):
            if u in eligible and v in eligible and u != v:
                adjacency[u].add(v)
        adjacency = {k: sorted(v) for k, v in adjacency.items()}

        # ---- DFS with per-node budget + global time budget -------------
        found_cycles = []
        seen_canonical = set()
        cycle_start_time = time.time()  # Global time budget for the cycle stage

        # Adaptive ops per node: scale DOWN for large datasets to stay under time budget
        n_nodes = len(eligible)
        adaptive_ops = max(100, min(self.MAX_OPS_PER_NODE, 50_000 // max(n_nodes, 1)))

        for start in sorted(eligible):
            if start not in adjacency:
                continue
            if len(found_cycles) >= self.MAX_CYCLES:
                break
            # Global time budget check — stop DFS if we've used 80 seconds
            if (time.time() - cycle_start_time) > self.CYCLE_TIME_BUDGET:
                print(f"[Engine] Cycle time budget reached after {len(found_cycles)} cycles. Stopping early.")
                break

            stack = [(start, [start], {start})]
            ops = 0

            while stack:
                ops += 1
                if ops > adaptive_ops:
                    break

                current, path, visited = stack.pop()

                if len(path) > self.MAX_DEPTH:
                    continue

                for neighbor in adjacency.get(current, []):
                    if neighbor == start and len(path) >= 3:
                        cycle_path = list(path)
                        canonical = _canonicalize_cycle(cycle_path)
                        if canonical not in seen_canonical:
                            result = self._validate_cycle_edges(cycle_path)
                            if result is not None:
                                seen_canonical.add(canonical)
                                found_cycles.append(result)
                        continue

                    if neighbor in visited:
                        continue
                    if len(path) >= self.MAX_DEPTH:
                        continue

                    new_visited = visited | {neighbor}
                    stack.append((neighbor, path + [neighbor], new_visited))

        if not found_cycles:
            return

        # ---- Union-Find with size-bounded merging --------------------
        uf = UnionFind()
        group_sizes: dict[str, int] = {}

        for cyc in found_cycles:
            nodes = cyc["nodes"]
            roots = set()
            for node in nodes:
                root = uf.find(node)
                roots.add(root)

            merged_size = sum(group_sizes.get(r, 1) for r in roots)
            if merged_size > self.MAX_RING_SIZE:
                continue

            anchor = nodes[0]
            for node in nodes[1:]:
                uf.union(anchor, node)

            new_root = uf.find(anchor)
            group_sizes[new_root] = merged_size

        # ---- Build merged rings → candidate_rings ----------------------
        merged_groups = uf.groups()

        account_cycle_lengths: dict[str, set[int]] = defaultdict(set)
        for cyc in found_cycles:
            for node in cyc["nodes"]:
                account_cycle_lengths[node].add(len(cyc["nodes"]))

        for _root, members in sorted(merged_groups.items()):
            # Exclude immune accounts from cycle ring membership
            non_immune_members = [m for m in members if m not in self._immune_accounts]
            # Still tag all accounts (including immune) with cycle patterns
            for m in members:
                for length in account_cycle_lengths.get(m, set()):
                    self.account_patterns[m].add(f"cycle_length_{length}")

            if len(non_immune_members) < 3:
                continue

            all_lengths = set()
            for m in non_immune_members:
                all_lengths |= account_cycle_lengths.get(m, set())

            # Confidence scoring (base 0.9)
            confidence = 0.9
            # Bonus: short cycles are more suspicious
            if all_lengths and min(all_lengths) == 3:
                confidence += 0.05
            # Bonus: low external edges → tight cycle
            cycle_set = set(non_immune_members)
            total_ext = 0
            for m in non_immune_members:
                for succ in self.G.successors(m):
                    if succ not in cycle_set:
                        total_ext += 1
                for pred in self.G.predecessors(m):
                    if pred not in cycle_set:
                        total_ext += 1
            avg_ext = total_ext / max(len(non_immune_members), 1)
            if avg_ext <= 2:
                confidence += 0.05

            base_risk = 50.0
            base_risk += (5 - min(all_lengths)) * 10 if all_lengths else 0
            base_risk += min(30.0, len(non_immune_members) * 2)
            risk_score = min(100.0, base_risk)

            self._candidate_rings.append({
                "members": sorted(non_immune_members),
                "pattern_type": "cycle",
                "risk_score": round(risk_score, 1),
                "confidence_score": min(1.0, confidence),
            })

    def _validate_cycle_edges(self, cycle_path):
        """
        Multi-constraint validation: find a valid edge combination
        satisfying time, variance, flow, and external-connection rules.
        """
        n = len(cycle_path)
        edge_lists = []
        for i in range(n):
            u = cycle_path[i]
            v = cycle_path[(i + 1) % n]
            edges = _get_edges_between(self.G, u, v)
            if not edges:
                return None
            # Sort by timestamp to prefer temporally close edges
            edges.sort(key=lambda e: e["timestamp"])
            edge_lists.append(edges)

        budget = [1000]  # Prevent exponential explosion on highly parallel edges

        def _recurse(idx, chosen):
            if budget[0] <= 0:
                return None
            if idx == n:
                budget[0] -= 1
                return self._check_cycle_constraints(cycle_path, chosen)
            for edge in edge_lists[idx]:
                result = _recurse(idx + 1, chosen + [edge])
                if result is not None:
                    return result
            return None

        return _recurse(0, [])

    def _check_cycle_constraints(self, cycle_path, edges):
        """
        4-layer constraint check: temporal, amount CV, flow, ext-degree.
        Phase 2: Relaxed external degree using adaptive limit.
        """
        timestamps = [e["timestamp"] for e in edges]
        amounts = [e["amount"] for e in edges]

        ts_min = min(timestamps)
        ts_max = max(timestamps)

        # 1. All transactions within 72h window
        if (ts_max - ts_min) > timedelta(hours=72):
            return None

        mean_amount = sum(amounts) / len(amounts)
        if mean_amount == 0:
            return None

        # 2. Amount variance within 30% of mean (relaxed from 15% — real-world muling varies more)
        if not all(abs(a - mean_amount) / mean_amount <= 0.30 for a in amounts):
            return None

        # 3. Flow conservation: min/max ratio >= 0.50 (relaxed from 0.70)
        flow_ratio = min(amounts) / max(amounts) if max(amounts) > 0 else 0
        if flow_ratio < 0.50:
            return None

        ext_limit = self._adaptive_ext_degree_limit
        cycle_set = set(cycle_path)
        for node in cycle_path:
            ext = _external_degree_in_window(self.G, node, cycle_set, ts_min, ts_max, ext_limit)
            if ext > ext_limit:
                return None

        return {
            "nodes": list(cycle_path),
            "edges": list(edges),
            "total_amount": sum(amounts),
        }

    # ================================================================== #
    #  3. SHELL NETWORK DETECTION — Relaxed (Phase 2)                     #
    # ================================================================== #
    def detect_shells(self) -> None:
        """
        Combined shell detection with relaxed thresholds (Phase 2):
          - Candidate filtering: degree ≤ 4 (was 2-3)
          - Passthrough ratio >= 70% within 24h (was 80%)
          - Short lifetime <= 40% of dataset span (was 30%)
          - Chain walking: BFS depth limit = 5 (was 7)
        """
        if self.G is None or self.df is None:
            return

        dataset_min = self.df["timestamp"].min()
        dataset_max = self.df["timestamp"].max()
        dataset_span = (dataset_max - dataset_min).total_seconds()

        # Optimized: Build per-account first/last seen using vectorized ops
        all_ts = pd.concat([
            self.df.rename(columns={"sender_id": "acc"})[["acc", "timestamp"]],
            self.df.rename(columns={"receiver_id": "acc"})[["acc", "timestamp"]]
        ])
        account_first_seen = all_ts.groupby("acc")["timestamp"].min().to_dict()
        account_last_seen = all_ts.groupby("acc")["timestamp"].max().to_dict()

        # Adaptive shell degree limit: scale with dataset density
        adaptive_shell_degree = max(4, int(self._median_degree + 0.5 * self._degree_std))

        # Identify shell candidates with passthrough + lifetime validation
        shell_candidates = set()
        for node in self.G.nodes():
            total_degree = self.G.in_degree(node) + self.G.out_degree(node)
            # Phase 2+3: adaptive degree constraint
            if total_degree < 2 or total_degree > adaptive_shell_degree:
                continue

            # Lifetime check: shell accounts are short-lived (<= 40% of dataset span)
            # FIX: account_first/last_seen WAS computed but never used — now enforced
            if dataset_span > 0 and node in account_first_seen and node in account_last_seen:
                node_lifetime = (account_last_seen[node] - account_first_seen[node]).total_seconds()
                if node_lifetime > 0.40 * dataset_span:
                    continue  # Long-lived account — not a shell

            in_edges = []
            for pred in self.G.predecessors(node):
                for _, data in self.G[pred][node].items():
                    in_edges.append(data)

            out_edges = []
            for succ in self.G.successors(node):
                for _, data in self.G[node][succ].items():
                    out_edges.append(data)

            if not in_edges or not out_edges:
                continue

            # Optimized Two-Pointer Passthrough Calculation
            # in_edges and out_edges are pre-sorted in the candidate logic
            in_edges.sort(key=lambda x: x["timestamp"])
            out_edges.sort(key=lambda x: x["timestamp"])
            
            total_in = sum(e["amount"] for e in in_edges)
            passed = 0
            out_ptr = 0
            for ie in in_edges:
                in_ts = ie["timestamp"]
                # Move out_ptr to first txn >= incoming
                while out_ptr < len(out_edges) and out_edges[out_ptr]["timestamp"] < in_ts:
                    out_ptr += 1
                
                # Match within 48h window
                scan_idx = out_ptr
                while scan_idx < len(out_edges) and (out_edges[scan_idx]["timestamp"] - in_ts) <= timedelta(hours=48):
                    passed += min(ie["amount"], out_edges[scan_idx]["amount"])
                    scan_idx += 1
                    break # Single matching pass for shell passthrough logic

            # Hybrid filter: stricter for sparse, tighter for dense
            ratio_threshold = 0.70
            simple_ratio_threshold = 0.50
            
            passes_temporal = (total_in > 0 and (passed / total_in) >= ratio_threshold)
            
            # Simple ratio check (total out / total in)
            total_out = sum(e["amount"] for e in out_edges)
            passes_simple = (total_in > 0 and (total_out / total_in) >= simple_ratio_threshold)

            # Use simple ratio in dense graphs (median > 8) as fallback
            if not passes_temporal:
                if self._median_degree > 8 and passes_simple:
                    pass  # Accepted by fallback
                else:
                    continue

            # Must have distinct predecessor and successor
            predecessors = set(self.G.predecessors(node))
            successors = set(self.G.successors(node))
            is_shell = False
            for pred in predecessors:
                for succ in successors:
                    if pred != succ and pred != node and succ != node:
                        is_shell = True
                        break
                if is_shell:
                    break

            if is_shell:
                shell_candidates.add(node)

        if not shell_candidates:
            return

        # Chain walking: find paths through shell intermediaries
        visited_chains: list[list[str]] = []
        # In dense graphs, we need strict chain length (>= 2 intermediaries)
        # to distinguish shells from random high-degree noise.
        min_intermediaries = 2 if self._median_degree > 8 else 1
        
        for node in self.G.nodes():
            if node in shell_candidates:
                continue
            self._find_shell_chains(node, shell_candidates, visited_chains, min_intermediaries)

        # Collect shell chains, deduplicate, apply hardening, cap output
        seen: set[frozenset[str]] = set()
        shell_ring_count = 0
        for chain in visited_chains:
            if shell_ring_count >= self.MAX_SHELL_RINGS:
                break
            # Exclude immune accounts from shell ring membership
            non_immune_chain = [a for a in chain if a not in self._immune_accounts]
            if len(non_immune_chain) < 3:
                continue
            key = frozenset(non_immune_chain)
            if key in seen:
                continue

            # ---- SHELL HARDENING RULES (§3) ----
            member_set = set(non_immune_chain)
            # Rule 1: component_size > 12 → reject
            if len(member_set) > 12:
                continue
            # Rule 2: average_degree > 4 → reject
            total_deg = sum(self.G.in_degree(m) + self.G.out_degree(m) for m in member_set)
            avg_deg = total_deg / len(member_set)
            if avg_deg > 8:  # Relaxed from 4 — real shells can have higher degree due to noise
                continue
            # Rule 3: max_node_degree > 8 → reject
            max_deg = max((self.G.in_degree(m) + self.G.out_degree(m)) for m in member_set)
            if max_deg > 8:
                continue
            # Rule 4: external_edges > internal_edges * 0.5 → reject
            internal_edges = 0
            external_edges = 0
            for m in member_set:
                for succ in self.G.successors(m):
                    if succ in member_set:
                        internal_edges += 1
                    else:
                        external_edges += 1
            if internal_edges > 0 and external_edges > internal_edges * 0.5:
                continue
            # Rule 5: pass-through ratio: abs(in - out) / total <= 0.1
            total_in_amt = 0.0
            total_out_amt = 0.0
            for m in member_set:
                for pred in self.G.predecessors(m):
                    for _, d in self.G[pred][m].items():
                        total_in_amt += d["amount"]
                for succ in self.G.successors(m):
                    for _, d in self.G[m][succ].items():
                        total_out_amt += d["amount"]
            total_amt = total_in_amt + total_out_amt
            if total_amt > 0:
                passthrough_ratio = abs(total_in_amt - total_out_amt) / total_amt
                # Relaxed for real data: allow up to 0.3 (0.1 is too strict)
                if passthrough_ratio > 0.3:
                    continue

            seen.add(key)

            # Confidence scoring (base 0.5)
            confidence = 0.5
            # Bonus: low external edges → tight shell
            if internal_edges > 0 and external_edges <= internal_edges * 0.2:
                confidence += 0.1
            # Bonus: high internal density
            max_possible = len(member_set) * (len(member_set) - 1)
            if max_possible > 0:
                density = internal_edges / max_possible
                if density >= 0.3:
                    confidence += 0.1
            # Size penalty (§5)
            confidence -= len(member_set) * 0.02

            self._candidate_rings.append({
                "members": sorted(non_immune_chain),
                "pattern_type": "shell_network",
                "risk_score": round(min(100.0, 55.0 + len(chain) * 5), 1),
                "confidence_score": max(0.1, min(1.0, confidence)),
            })
            shell_ring_count += 1
            for acc in chain:
                self.account_patterns[acc].add("shell_account")

    def _find_shell_chains(self, start, shell_candidates, results, min_intermediaries=1):
        """Phase 2: BFS depth limit = 4 (optimized for perf)."""
        # (current_node, current_path)
        stack = [(start, [start])]
        visited_in_path: set[str] = set()
        
        # Limit paths per node to avoid explosion
        paths_found = 0
        
        while stack:
            if paths_found >= 50:
                break
                
            current, path = stack.pop()
            
            # Depth limit 3 hops (4 nodes) - sufficient for min_int=2
            # Path: [S, C1, C2, E] -> 2 intermediaries
            if len(path) >= 4:
                continue
                
            for neighbor in self.G.successors(current):
                if neighbor in path:
                    continue
                
                new_path = path + [neighbor]
                
                if neighbor in shell_candidates:
                    stack.append((neighbor, new_path))
                else:
                    # Check if valid chain end
                    intermediaries = [n for n in new_path[1:-1] if n in shell_candidates]
                    if len(intermediaries) >= min_intermediaries:
                        results.append(new_path)
                        paths_found += 1

    # ================================================================== #
    #  4. VELOCITY DETECTION — Vectorized (in→out < 1h) + 24h Window     #
    # ================================================================== #
    def detect_velocity(self) -> None:
        """
        Two-tier velocity detection:
          Tier 1: Receive AND re-transmit in < 1 hour (original)
          Tier 2: 5+ transactions in any 24h window (adapted from old code)
        Also detects low amount variance (CV < 0.2) as standalone signal.
        """
        if self.df is None or self.df.empty:
            return

        one_hour_ns = np.timedelta64(1, "h")

        senders = self.df[["sender_id", "timestamp"]].rename(columns={"sender_id": "account"})
        senders["direction"] = "out"
        receivers = self.df[["receiver_id", "timestamp"]].rename(columns={"receiver_id": "account"})
        receivers["direction"] = "in"

        events = pd.concat([senders, receivers], ignore_index=True)
        events.sort_values(["account", "timestamp"], inplace=True)

        for acc, grp in events.groupby("account"):
            dirs = grp["direction"].values
            ts = grp["timestamp"].values

            in_indices = np.where(dirs == "in")[0]
            out_indices = np.where(dirs == "out")[0]

            # Tier 1: in→out < 1h
            if len(in_indices) > 0 and len(out_indices) > 0:
                out_ptr = 0
                for in_idx in in_indices:
                    in_ts = ts[in_idx]
                    while out_ptr < len(out_indices) and out_indices[out_ptr] <= in_idx:
                        out_ptr += 1
                    if out_ptr >= len(out_indices):
                        break
                    out_ts = ts[out_indices[out_ptr]]
                    if (out_ts - in_ts) <= one_hour_ns:
                        self._velocity_accounts.add(acc)
                        self.account_patterns[acc].add("high_velocity")
                        break

            # Tier 2: 5+ transactions in any 24h window (from old code)
            if len(ts) >= 5:
                twenty_four_h = np.timedelta64(24, "h")
                for i in range(len(ts)):
                    window_end = ts[i] + twenty_four_h
                    count_in_window = np.searchsorted(ts, window_end, side='right') - i
                    if count_in_window >= 5:
                        self._velocity_24h_accounts.add(acc)
                        self.account_patterns[acc].add("high_velocity_24h")
                        break

        # ---- Low Amount Variance Detection (from old code) ----
        account_amounts: dict[str, list[float]] = defaultdict(list)
        for _, row in self.df.iterrows():
            account_amounts[row["sender_id"]].append(float(row["amount"]))
            account_amounts[row["receiver_id"]].append(float(row["amount"]))

        for account, amounts in account_amounts.items():
            if len(amounts) < 2:
                continue
            cv = _coefficient_of_variation(amounts)
            if cv < 0.2:
                self._low_variance_accounts.add(account)
                self.account_patterns[account].add("low_variance")

        # ---- High-Degree Hub Suppression Detection (from old code) ----
        # Accounts with degree > 50, long activity span, and high variance
        # are likely commercial hubs, not fraud participants.
        dataset_span = self._dataset_time_span
        if dataset_span > 0:
            account_timestamps: dict[str, list] = defaultdict(list)
            for _, row in self.df.iterrows():
                for acc in [row["sender_id"], row["receiver_id"]]:
                    account_timestamps[acc].append(row["timestamp"])

            for node in self.G.nodes():
                total_degree = self.G.in_degree(node) + self.G.out_degree(node)
                if total_degree <= 50:
                    continue

                ts_list = account_timestamps.get(node, [])
                if not ts_list:
                    continue

                activity_span = (max(ts_list) - min(ts_list)).total_seconds()
                if activity_span < 0.70 * dataset_span:
                    continue

                node_amounts = account_amounts.get(node, [])
                if len(node_amounts) < 2:
                    continue
                cv = _coefficient_of_variation(node_amounts)
                if cv < 0.5:
                    continue

                # Check for regular gaps (no large dormancy)
                ts_sorted = sorted(ts_list)
                gaps = [(ts_sorted[i + 1] - ts_sorted[i]).total_seconds()
                        for i in range(len(ts_sorted) - 1)]
                if gaps:
                    max_gap = max(gaps)
                    if max_gap > 0.25 * dataset_span:
                        continue

                self._high_degree_hubs.add(node)

    # ================================================================== #
    #  BUSINESS IMMUNITY LAYER                                             #
    # ================================================================== #
    def _detect_business_immunity(self) -> None:
        """
        Detect payroll and merchant accounts.
        Phase 1: Immunity is identified here but suppression is applied
        AFTER scoring in the suppression stage.

        Payroll: dominant_sender_ratio > 0.7, no outbound redistribution.
        Merchant: many unique inbound senders (≥10), negligible outbound.
        """
        if self.G is None or self.df is None:
            return

        for node in self.G.nodes():
            # Gather inbound with peer info
            in_txns = []
            for pred in self.G.predecessors(node):
                for _, data in self.G[pred][node].items():
                    in_txns.append({"amt": data["amount"], "peer": pred})

            # Gather outbound with peer info
            out_txns = []
            for succ in self.G.successors(node):
                for _, data in self.G[node][succ].items():
                    out_txns.append({"amt": data["amount"], "peer": succ})

            in_sum = sum(e["amt"] for e in in_txns) if in_txns else 0
            out_sum = sum(e["amt"] for e in out_txns) if out_txns else 0
            in_count = len(in_txns)
            out_count = len(out_txns)

            # --- Payroll detection ---
            if in_count >= 4 and in_sum > 0:
                sender_volumes: dict[str, float] = defaultdict(float)
                for e in in_txns:
                    sender_volumes[e["peer"]] += e["amt"]
                max_sender_vol = max(sender_volumes.values())
                dominant_ratio = max_sender_vol / in_sum

                no_redistribution = (
                    out_count <= 3 or
                    (in_sum > 0 and out_sum / in_sum < 0.1)
                )

                if dominant_ratio > 0.7 and no_redistribution:
                    self._immune_accounts.add(node)
                    self._immune_types[node] = "payroll"
                    self.account_patterns[node].add("payroll")
                    continue

            # --- Merchant detection ---
            unique_senders = set(e["peer"] for e in in_txns)
            if len(unique_senders) >= 10:
                negligible_out = (
                    out_count <= 2 or
                    (in_sum > 0 and out_sum / in_sum < 0.05)
                )
                if negligible_out:
                    self._immune_accounts.add(node)
                    self._immune_types[node] = "merchant"
                    self.account_patterns[node].add("merchant")

    # ================================================================== #
    #  SMURFING — Candidate Extraction + Soft Scoring (Phase 1+2)         #
    # ================================================================== #
    def _extract_smurf_candidates(self) -> None:
        """
        Extract smurf candidates using sliding 72h window.
        A candidate is a node with unique_in >= 5 in any 72h window.
        Phase 1: Immune accounts are still extracted but scored lower.
        """
        if self.G is None:
            return

        WINDOW_72H = timedelta(hours=72)
        UNIQUE_IN_THRESHOLD = 5

        for node in self.G.nodes():
            # Phase 1: Do NOT skip immune accounts at extraction stage
            # Immunity is applied during suppression

            # Build inbound / outbound transaction lists
            in_txns = []
            for pred in self.G.predecessors(node):
                for _, data in self.G[pred][node].items():
                    in_txns.append({
                        "ts": data["timestamp"],
                        "amt": data["amount"],
                        "peer": pred,
                    })
            in_txns.sort(key=lambda e: e["ts"])

            out_txns = []
            for succ in self.G.successors(node):
                for _, data in self.G[node][succ].items():
                    out_txns.append({
                        "ts": data["timestamp"],
                        "amt": data["amount"],
                        "peer": succ,
                    })
            out_txns.sort(key=lambda e: e["ts"])

            if len(in_txns) < UNIQUE_IN_THRESHOLD:
                continue

            # Sliding window: find best window with unique_in >= threshold
            n = len(in_txns)
            right = 0
            for left in range(n):
                w_start = in_txns[left]["ts"]
                w_end = w_start + WINDOW_72H
                while right < n and in_txns[right]["ts"] <= w_end:
                    right += 1

                window_in_txns = in_txns[left:right]
                unique_in = len(set(e["peer"] for e in window_in_txns))

                if unique_in >= UNIQUE_IN_THRESHOLD:
                    # Find outbound within the same window (+ 24h buffer)
                    window_out_txns = [
                        e for e in out_txns
                        if w_start <= e["ts"] <= w_end + timedelta(hours=24)
                    ]
                    self._smurf_candidates.append({
                        "hub": node,
                        "in_txns": window_in_txns,
                        "out_txns": window_out_txns,
                        "w_start": w_start,
                        "w_end": w_end,
                    })
                    break  # One candidate per node

    def _score_smurf_candidates(self) -> None:
        """
        Phase 1+2: Soft scoring instead of hard gating.
        Each condition contributes to a confidence score.
        Candidates with sufficient combined score become rings.
        
        Scoring factors (each 0.0 to 1.0):
          1. Flow-through ratio (retention >= 0.6)
          2. Outbound concentration (unique_out <= 3 ideal)
          3. Hold time (median < 24h)
          4. CV of inbound amounts (<= 0.35)
          5. Ring size (>= 4 members preferred)
        
        Candidate passes if combined_score >= 3.0 out of 5.0
        """
        seen_ring_keys: set[tuple[str, ...]] = set()

        for cand in self._smurf_candidates:
            hub = cand["hub"]
            in_txns = cand["in_txns"]
            out_txns = cand["out_txns"]

            if not in_txns:
                continue

            incoming_sum = sum(e["amt"] for e in in_txns)
            outgoing_sum = sum(e["amt"] for e in out_txns) if out_txns else 0

            # Factor 1: Flow-through ratio (retention ratio >= 0.6)
            if incoming_sum <= 0:
                continue
            retention = outgoing_sum / incoming_sum if incoming_sum > 0 else 0
            if retention >= 0.6:
                flow_score = 1.0
            elif retention >= 0.4:
                flow_score = 0.5
            else:
                flow_score = 0.0

            # Factor 2: Outbound concentration
            unique_out = len(set(e["peer"] for e in out_txns)) if out_txns else 0
            if unique_out <= 3:
                conc_score = 1.0
            elif unique_out <= 5:
                conc_score = 0.5
            else:
                conc_score = 0.0

            # Factor 3: Median hold time (Optimized Two-Pointer Scan)
            hold_times = []
            out_ptr = 0
            for ie in in_txns:
                in_ts = ie["ts"]
                # Move out_ptr to the first transaction occurring after in_ts
                while out_ptr < len(out_txns) and out_txns[out_ptr]["ts"] < in_ts:
                    out_ptr += 1
                
                if out_ptr < len(out_txns):
                    # Found the closest outbound transaction
                    hold_secs = (out_txns[out_ptr]["ts"] - in_ts).total_seconds()
                    hold_times.append(hold_secs)

            if hold_times:
                median_hold = median(hold_times)
                if median_hold < 24 * 3600:
                    hold_score = 1.0
                elif median_hold < 48 * 3600:
                    hold_score = 0.5
                else:
                    hold_score = 0.0
            else:
                # No outbound — still allow if other factors strong
                hold_score = 0.3

            # Factor 4: CV of inbound amounts (Phase 2: <= 0.35)
            in_amounts = [e["amt"] for e in in_txns]
            cv = _coefficient_of_variation(in_amounts)
            if cv <= 0.35:
                cv_score = 1.0
            elif cv <= 0.5:
                cv_score = 0.5
            else:
                cv_score = 0.0

            # Build ring members — exclude immune accounts from membership
            inbound_accounts = set(e["peer"] for e in in_txns) - self._immune_accounts
            outbound_accounts = (set(e["peer"] for e in out_txns) if out_txns else set()) - self._immune_accounts
            # Hub itself excluded if immune
            hub_set = set() if hub in self._immune_accounts else {hub}
            all_members_set = hub_set | inbound_accounts | outbound_accounts

            # Cap smurfing ring size to prevent mega-rings
            if len(all_members_set) > self.MAX_SMURF_RING_SIZE:
                # Keep hub + closest inbound/outbound by recency
                # Prioritize inbound (the smurf sources)
                keep = hub_set.copy()
                remaining_budget = self.MAX_SMURF_RING_SIZE - len(keep)
                # Add inbound accounts first, then outbound
                for acc in sorted(inbound_accounts)[:remaining_budget]:
                    keep.add(acc)
                remaining_budget = self.MAX_SMURF_RING_SIZE - len(keep)
                for acc in sorted(outbound_accounts)[:remaining_budget]:
                    keep.add(acc)
                all_members_set = keep

            all_members = sorted(all_members_set)

            # Factor 5: Ring size
            ring_size = len(all_members)
            if ring_size >= 5:
                size_score = 1.0
            elif ring_size >= 4:
                size_score = 0.8
            elif ring_size >= 3:
                size_score = 0.4
            else:
                size_score = 0.0

            # Combined score — threshold is 2.5 / 5.0 (relaxed from 4.0 to allow partial pattern matches)
            combined_score = flow_score + conc_score + hold_score + cv_score + size_score
            if combined_score < 2.5:
                continue

            # Minimum ring size of 3 (relaxed from 4 to catch small smurfing rings)
            if ring_size < 3:
                continue

            # Dedup
            ring_key = tuple(all_members)
            if ring_key in seen_ring_keys:
                continue
            seen_ring_keys.add(ring_key)

            # Confidence scoring (§1: smurf base = 0.7)
            confidence = 0.7
            # Scale by soft-scoring result
            confidence += (combined_score - 4.0) / 5.0 * 0.2  # Up to +0.06
            # Bonus: low external edges → high internal density
            member_set = set(all_members)
            ext_count = 0
            int_count = 0
            for m in member_set:
                for succ in self.G.successors(m):
                    if succ in member_set:
                        int_count += 1
                    else:
                        ext_count += 1
            if int_count > 0 and ext_count <= int_count:
                confidence += 0.05
            # Size penalty (§5)
            if ring_size > 15:
                confidence -= 0.1
            confidence -= ring_size * 0.005  # mild per-member penalty

            # Create candidate ring with dynamic risk score
            confidence_pct = combined_score / 5.0
            ring_risk = min(100.0, 40.0 + confidence_pct * 40.0 + ring_size * 2)

            self._candidate_rings.append({
                "members": all_members,
                "pattern_type": "smurfing",
                "risk_score": round(ring_risk, 1),
                "confidence_score": max(0.1, min(1.0, confidence)),
                "core_account": hub,  # Used for smurf consolidation
            })

            # Label accounts
            for acc in all_members:
                if acc == hub:
                    self.account_patterns[acc].add("smurfing")
                    self.account_patterns[acc].add("fan_in")
                elif acc in inbound_accounts:
                    self.account_patterns[acc].add("fan_in")
                else:
                    self.account_patterns[acc].add("fan_out")

    # ================================================================== #
    #  STRUCTURING — Strict Multi-Window Detection                        #
    # ================================================================== #
    def detect_structuring(self) -> None:
        """
        Strict structuring detection:
          - ≥5 transactions in near-threshold band ($8K–$9,999 or $4K–$4,999)
          - Within a 48h window
          - Pattern repeated across ≥2 separate windows (≥48h apart)
        """
        if self.df is None or self.df.empty:
            return

        BANDS = [(8000, 9999), (4000, 4999)]
        MIN_HITS_PER_WINDOW = 5
        WINDOW_48H = timedelta(hours=48)
        MIN_WINDOWS = 2

        # Optimized: Pre-filter transactions to only hit bands
        band_masks = [((self.df["amount"] >= lo) & (self.df["amount"] <= hi)) for lo, hi in BANDS]
        combined_mask = band_masks[0]
        for m in band_masks[1:]:
            combined_mask |= m
        
        filtered_df = self.df[combined_mask].copy()
        if filtered_df.empty:
            return

        # Explode transactions so each row represents one account hit
        sender_hits = filtered_df[["sender_id", "timestamp"]].rename(columns={"sender_id": "acc"})
        receiver_hits = filtered_df[["receiver_id", "timestamp"]].rename(columns={"receiver_id": "acc"})
        all_hits = pd.concat([sender_hits, receiver_hits]).sort_values(["acc", "timestamp"])

        for acc, grp in all_hits.groupby("acc"):
            band_txns = grp["timestamp"].tolist()
            if len(band_txns) < MIN_HITS_PER_WINDOW:
                continue

            qualifying_windows = []
            n = len(band_txns)
            right = 0
            for left in range(n):
                w_start = band_txns[left]
                w_end = w_start + WINDOW_48H
                while right < n and band_txns[right] <= w_end:
                    right += 1
                
                if (right - left) >= MIN_HITS_PER_WINDOW:
                    if not qualifying_windows or (w_start - qualifying_windows[-1]) >= timedelta(hours=48):
                        qualifying_windows.append(w_start)

            if len(qualifying_windows) >= MIN_WINDOWS:
                self.account_patterns[acc].add("structuring")

    def _consolidate_rings(self) -> None:
        """
        2-stage ring consolidation pipeline (§2 + §4):
          1. Smurf Consolidation — merge overlapping smurf candidates per core
          2. Global Ring Arbitration — confidence-sorted exclusive node assignment
        """
        if len(self._candidate_rings) == 0:
            return

        # ---- Stage 1: SMURF CONSOLIDATION (§2) ----
        # Group smurf candidates by core_account.
        # Merge overlapping windows if Jaccard > 0.6.
        # Emit ONE consolidated smurf ring per core.
        self._candidate_rings = self._smurf_consolidation(self._candidate_rings)

        # ---- Stage 2: GLOBAL RING ARBITRATION (§4) ----
        self.fraud_rings = self._arbitrate_rings(self._candidate_rings)

    # ------------------------------------------------------------------ #
    #  Stage 1: Smurf Consolidation Per Core (§2)                        #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _smurf_consolidation(candidates: list[dict]) -> list[dict]:
        """
        Group smurf candidates by core_account.
        Within each core group, merge overlapping rings (Jaccard > 0.6).
        Emit ONE consolidated ring per core.
        Non-smurf candidates pass through unchanged.
        """
        non_smurf = [c for c in candidates if c["pattern_type"] != "smurfing"]
        smurf = [c for c in candidates if c["pattern_type"] == "smurfing"]

        if not smurf:
            return candidates

        # Group by core_account
        core_groups: dict[str, list[dict]] = defaultdict(list)
        for s in smurf:
            core = s.get("core_account", "unknown")
            core_groups[core].append(s)

        consolidated_smurfs = []
        for core, group in core_groups.items():
            if len(group) == 1:
                consolidated_smurfs.append(group[0])
                continue

            # Merge overlapping within this core group using Jaccard > 0.6
            n = len(group)
            parent = list(range(n))

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def union(a, b):
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra

            sets = [set(g["members"]) for g in group]
            for i in range(n):
                for j in range(i + 1, n):
                    if _jaccard_similarity(sets[i], sets[j]) > 0.6:
                        union(i, j)

            uf_groups: dict[int, list[int]] = defaultdict(list)
            for i in range(n):
                uf_groups[find(i)].append(i)

            # Emit ONE ring per merged group
            for indices in uf_groups.values():
                merged_members = set()
                best_confidence = 0.0
                best_risk = 0.0
                for idx in indices:
                    merged_members.update(group[idx]["members"])
                    best_confidence = max(best_confidence, group[idx]["confidence_score"])
                    best_risk = max(best_risk, group[idx]["risk_score"])

                consolidated_smurfs.append({
                    "members": sorted(merged_members),
                    "pattern_type": "smurfing",
                    "risk_score": round(best_risk, 1),
                    "confidence_score": best_confidence,
                    "core_account": core,
                })

        return non_smurf + consolidated_smurfs

    # ------------------------------------------------------------------ #
    #  Stage 2: Global Ring Arbitration (§4)                              #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _arbitrate_rings(candidates: list[dict]) -> list[dict]:
        """
        Global ring arbitration with exclusive node assignment.
        
        Sort by: confidence_score descending, then pattern priority
        (cycle > smurf > shell).
        
        For each candidate:
          - If overlap_ratio > 0.6 with existing rings → merge into strongest
          - Otherwise → accept ring, claim all its nodes
        
        Output stability:
          - Each account in at most one ring
          - No ring > 15 members unless cycle-based
          - Deterministic ring IDs
        """
        if not candidates:
            return []

        TYPE_PRIORITY = {"cycle": 0, "smurfing": 1, "shell_network": 2}

        # Sort: confidence desc, then priority asc (cycle first)
        sorted_cands = sorted(
            candidates,
            key=lambda c: (
                -c["confidence_score"],
                TYPE_PRIORITY.get(c["pattern_type"], 99),
            )
        )

        final_rings: list[dict] = []
        used_nodes: set[str] = set()
        # node → index in final_rings for O(N) lookup
        node_to_ring_idx: dict[str, int] = {}

        for cand in sorted_cands:
            members = set(cand["members"])
            overlap = members & used_nodes
            overlap_ratio = len(overlap) / len(members) if members else 0

            if overlap_ratio > 0.6:
                # Merge into the strongest overlapping ring
                # Find which ring has the most overlap
                ring_overlap_counts: dict[int, int] = defaultdict(int)
                for node in overlap:
                    if node in node_to_ring_idx:
                        ring_overlap_counts[node_to_ring_idx[node]] += 1

                if ring_overlap_counts:
                    best_ring_idx = max(ring_overlap_counts,
                                        key=ring_overlap_counts.get)
                    target_ring = final_rings[best_ring_idx]
                    # Only merge new nodes, cap at 15 for non-cycle
                    current_members = set(target_ring["member_accounts"])
                    new_nodes = members - current_members
                    if target_ring["pattern_type"] != "cycle":
                        budget = 15 - len(current_members)
                        new_nodes = set(sorted(new_nodes)[:max(0, budget)])
                    current_members.update(new_nodes)
                    target_ring["member_accounts"] = sorted(current_members)
                    target_ring["risk_score"] = max(
                        target_ring["risk_score"], cand["risk_score"])
                    # Update node index
                    for node in new_nodes:
                        used_nodes.add(node)
                        node_to_ring_idx[node] = best_ring_idx
                continue

            # Accept this ring
            accepted_members = sorted(members - used_nodes | (members & used_nodes))
            # Actually: allow all members but only claim unclaimed ones
            ring_members = sorted(members)

            # Size cap: non-cycle rings max 15
            if cand["pattern_type"] != "cycle" and len(ring_members) > 15:
                ring_members = ring_members[:15]

            if len(ring_members) < 3:
                continue

            ring_idx = len(final_rings)
            final_rings.append({
                "ring_id": "",  # assigned below
                "member_accounts": ring_members,
                "pattern_type": cand["pattern_type"],
                "risk_score": round(cand["risk_score"], 1),
            })

            for node in ring_members:
                used_nodes.add(node)
                node_to_ring_idx[node] = ring_idx

        # Sort by risk descending for deterministic output
        final_rings.sort(key=lambda r: (-r["risk_score"], r["pattern_type"]))

        # Assign ring IDs
        for idx, ring in enumerate(final_rings):
            ring["ring_id"] = f"RING_{idx + 1:03d}"

        return final_rings

    # ================================================================== #
    #  PATTERN HIERARCHY ENFORCEMENT                                       #
    # ================================================================== #
    def _apply_rule_thresholds(self) -> None:
        """Apply account-type specific thresholds from YAML (Rules Pillar)."""
        if not getattr(self, 'account_thresholds', None) or self.df is None or self.df.empty:
            return
        if "account_type" not in self.df.columns:
            return
            
        if "rule_based_fraud" not in self.df.columns:
            self.df["rule_based_fraud"] = False

        df_sorted = self.df.sort_values(by=["sender_id", "timestamp"])
        
        for acc_type, rules in self.account_thresholds.items():
            type_mask = (self.df["account_type"] == acc_type)
            if not type_mask.any():
                continue
                
            # 1. Single Tx Limit
            high_val = rules.get("high_value_threshold")
            if high_val:
                breach_mask = type_mask & (self.df["amount"] > high_val)
                self.df.loc[breach_mask, "rule_based_fraud"] = True
                for acc in self.df.loc[breach_mask, "sender_id"].unique():
                    self.account_patterns[acc].add("threshold_breach")
                    
            # 2. Daily Limit
            daily_limit = rules.get("daily_limit")
            if daily_limit:
                daily_sums = self.df[type_mask].groupby(["sender_id", self.df["timestamp"].dt.date])["amount"].sum()
                breach_accs = daily_sums[daily_sums > daily_limit].index.get_level_values(0).unique()
                for acc in breach_accs:
                    self.account_patterns[acc].add("threshold_breach")
                    
            # 3. Velocity Limit (10 min sliding window)
            vel_limit = rules.get("velocity_tx_limit")
            vel_window = rules.get("velocity_window_minutes")
            if vel_limit and vel_window:
                type_df = df_sorted[df_sorted["account_type"] == acc_type]
                for acc, grp in type_df.groupby("sender_id"):
                    grp = grp.set_index("timestamp")
                    rolling_count = grp["transaction_id"].rolling(f"{vel_window}min").count()
                    if (rolling_count > vel_limit).any():
                        self.account_patterns[acc].add("threshold_breach")
                        
            # 4. Credit Card Specific Multipliers
            cc_limit_mult = rules.get("credit_limit_multiplier")
            if cc_limit_mult and "credit_limit" in self.df.columns:
                cc_mask = type_mask & (self.df["amount"] > (self.df["credit_limit"] * cc_limit_mult))
                self.df.loc[cc_mask, "rule_based_fraud"] = True
                for acc in self.df.loc[cc_mask, "sender_id"].unique():
                    self.account_patterns[acc].add("threshold_breach")

    def _apply_pattern_hierarchy(self) -> None:
        """
        Enforce classification priority:
          cycle > shell > smurfing > structuring > high_velocity

        For each account, keep only the highest-priority pattern class.
        Lower-priority patterns are removed to prevent double-counting.
        """
        HIERARCHY = [
            {"cycle_length_3", "cycle_length_4", "cycle_length_5"},  # Priority 1
            {"shell_account"},                                        # Priority 2
            {"smurfing", "fan_in", "fan_out"},                       # Priority 3
            {"structuring"},                                          # Priority 4
            {"high_velocity", "high_velocity_24h"},                   # Priority 5
            {"low_variance"},                                         # Priority 6
        ]

        # Patterns that are always kept regardless of hierarchy
        # FIX: high_velocity and low_variance are additive signals — they must
        # NOT be stripped from structural accounts or they lose score contribution.
        KEEP_ALWAYS = {
            "isolation_cluster", "payroll", "merchant",
            "high_velocity", "high_velocity_24h", "low_variance",
        }

        for acc in list(self.account_patterns.keys()):
            patterns = self.account_patterns[acc]
            kept = patterns & KEEP_ALWAYS

            # Find the highest-priority group that this account belongs to
            for group in HIERARCHY:
                if patterns & group:
                    kept |= (patterns & group)
                    break  # Only keep the highest-priority structural group

            self.account_patterns[acc] = kept

    # ================================================================== #
    #  PHASE 5: COMPOSITE RISK SCORING (Score Before Suppression)          #
    # ================================================================== #

    def _assign_structural_roles(self) -> None:
        self.node_roles = {}
        if not self.G:
            return
        
        for n in self.G.nodes():
            in_deg = self.G.in_degree(n)
            out_deg = self.G.out_degree(n)
            total_deg = in_deg + out_deg
            
            if total_deg == 0:
                self.node_roles[n] = 'LEAF'
            elif in_deg > 0 and out_deg > 0:
                if total_deg >= self._median_degree * 3:
                    self.node_roles[n] = 'BRIDGE'
                else:
                    self.node_roles[n] = 'MULE'
            else:
                if total_deg >= self._median_degree * 5:
                    self.node_roles[n] = 'HUB'
                else:
                    self.node_roles[n] = 'LEAF'
                    
        # Hub logic override: node with highest degree in a ring
        for ring in self.fraud_rings:
            members = ring['member_accounts']
            if not members: continue
            hub = max(members, key=lambda x: self.G.in_degree(x) + self.G.out_degree(x))
            self.node_roles[hub] = 'HUB'

    def calculate_suspicion_scores(self) -> None:
        if self.G is None: return
        nodes = list(self.G.nodes())
        if not nodes: return

        # 1. GAT Pillar Setup (PageRank)
        try:
            pagerank = nx.pagerank(self.G, alpha=0.85, max_iter=100)
            max_pr = max(pagerank.values()) if pagerank else 1.0
        except:
            pagerank = {n: 0.0 for n in nodes}
            max_pr = 1.0

        # 2. EIF Pillar Setup (Isolation Forest)
        features = []
        vol_in_map = self.df.groupby('receiver_id')['amount'].sum().to_dict()
        vol_out_map = self.df.groupby('sender_id')['amount'].sum().to_dict()
        for n in nodes:
            features.append([self.G.in_degree(n), self.G.out_degree(n), float(vol_in_map.get(n, 0)), float(vol_out_map.get(n, 0))])
            
        feature_df = pd.DataFrame(features, columns=['in_degree', 'out_degree', 'vol_in', 'vol_out'], index=nodes)
        iso = IsolationForest(contamination=0.05 if len(feature_df) >= 20 else 'auto', random_state=42)
        iso.fit(feature_df.values)
        raw_scores = iso.decision_function(feature_df.values)
        min_s, max_s = raw_scores.min(), raw_scores.max()
        eif_normalized = (max_s - raw_scores) / (max_s - min_s) if max_s > min_s else np.zeros(len(raw_scores))
        
        # 3. LSTM Pillar Setup (Burst timing)
        df_sorted = self.df.sort_values(['sender_id', 'timestamp'])
        burst_scores = {}
        for acc, grp in df_sorted.groupby('sender_id'):
            if len(grp) >= 3:
                min_gap = grp['timestamp'].diff().min().total_seconds()
                burst_scores[acc] = max(0, 25.0 - (min_gap / 1800.0 * 25.0)) # decays over 30 min
            else:
                burst_scores[acc] = 0.0

        self.four_pillar_scores = {}
        self.enforcement_verdicts = {}
        
        STRUCTURAL_PATTERNS = {'cycle_length_3', 'cycle_length_4', 'cycle_length_5', 'shell_account', 'smurfing'}
        
        for idx, node in enumerate(nodes):
            patterns = self.account_patterns.get(node, set())
            
            # GAT Score (35%)
            gat_score = (pagerank.get(node, 0) / max_pr) * 15.0 # Increased baseline
            if 'cycle_length_3' in patterns: gat_score += 35.0
            elif 'cycle_length_4' in patterns: gat_score += 30.0
            elif 'cycle_length_5' in patterns: gat_score += 25.0
            elif 'shell_account' in patterns: gat_score += 30.0
            elif 'smurfing' in patterns: gat_score += 25.0
            elif 'fan_in' in patterns or 'fan_out' in patterns: gat_score += 20.0
            gat_score = min(35.0, gat_score)
            
            # LSTM Score (25%)
            lstm_score = burst_scores.get(node, 0.0)
            if node in self._immune_accounts: lstm_score *= 0.1 # Dampen for immune
            lstm_score = min(25.0, lstm_score)
            
            # EIF Score (20%)
            eif_score = float(eif_normalized[idx]) * 20.0
            if 'isolation_cluster' in patterns: eif_score += 15.0
            eif_score = min(20.0, eif_score)
            
            # Rules Score (20%)
            rules_score = 0.0
            if 'threshold_breach' in patterns: rules_score += 25.0  # Boost for breach
            if 'structuring' in patterns: rules_score += 15.0
            if 'high_velocity' in patterns or 'high_velocity_24h' in patterns: rules_score += 12.0
            if 'low_variance' in patterns: rules_score += 12.0
            rules_score = min(25.0, rules_score)  # Can exceed 20 to guarantee REVIEW
            
            # Combine 
            raw_score = gat_score + lstm_score + eif_score + rules_score
            
            # Role Multiplier
            role = self.node_roles.get(node, 'LEAF')
            mult = {'HUB': 1.25, 'BRIDGE': 1.15, 'MULE': 1.10, 'LEAF': 1.0}.get(role, 1.0)
            
            # Guarantee REVIEW (40) for strong fraud patterns as per specs
            STRONG_FRAUD_PATTERNS = {'cycle_length_3', 'cycle_length_4', 'cycle_length_5', 'shell_account', 'smurfing', 'threshold_breach'}
            has_strong_fraud = bool(patterns & STRONG_FRAUD_PATTERNS)
            if has_strong_fraud and raw_score < (40.0 / mult):
                raw_score = 40.0 / mult
            
            final_score = min(100.0, raw_score * mult)
            
            # Enforcement Verdict & Suppression
            if final_score < 40:
                verdict = 'APPROVE'
            elif final_score < 75:
                verdict = 'REVIEW'
            else:
                verdict = 'BLOCK'
                
            # Re-introduce Business Immunity suppression
            if node in self._immune_accounts and not has_strong_fraud:
                final_score = 0.0
                verdict = 'APPROVE'
                
            # If completely clean/approved, zero score so it drops from flagged list
            if verdict == 'APPROVE':
                final_score = 0.0
                
            self.four_pillar_scores[node] = {
                'GAT': round(gat_score, 1),
                'LSTM': round(lstm_score, 1),
                'EIF': round(eif_score, 1),
                'Rules': round(rules_score, 1),
                'Total': round(final_score, 1),
                'Multiplier': mult
            }
            self.enforcement_verdicts[node] = verdict
            self.suspicion_scores[node] = final_score
            
            # Expalnations
            parts = [f'{k}: {v}' for k, v in self.four_pillar_scores[node].items()]
            parts.append(f'Verdict: {verdict}')
            self._explanations[node] = ' | '.join(parts)
    # ================================================================== #
    #  JSON GENERATION                                                     #
    # ================================================================== #
    def generate_json(self) -> dict:
        account_rings: dict[str, list[str]] = defaultdict(list)
        for ring in self.fraud_rings:
            for acc in ring["member_accounts"]:
                account_rings[acc].append(ring["ring_id"])

        suspicious_accounts = []
        for acc, score in self.suspicion_scores.items():
            if score <= 0:
                continue
            suspicious_accounts.append({
                "account_id": acc,
                "suspicion_score": score,
                "four_pillar_scores": self.four_pillar_scores.get(acc, {}),
                "verdict": self.enforcement_verdicts.get(acc, "APPROVE"),
                "structural_role": self.node_roles.get(acc, "LEAF"),
                "detected_patterns": sorted(self.account_patterns.get(acc, set())),
                "ring_id": account_rings[acc][0] if account_rings[acc] else "NONE",
                "explanation": self._explanations.get(acc, ""),
            })

        suspicious_accounts.sort(key=lambda x: (-x["suspicion_score"], x["account_id"]))

        return {
            "suspicious_accounts": suspicious_accounts,
            "fraud_rings": self.fraud_rings,
            "summary": {
                "total_accounts_analyzed": len(self.G.nodes()) if self.G else 0,
                "suspicious_accounts_flagged": len(suspicious_accounts),
                "fraud_rings_detected": len(self.fraud_rings),
                "processing_time_seconds": round(self._processing_time, 2),
            },
        }

    # ================================================================== #
    #  GRAPH DATA (Vis.js)                                                 #
    # ================================================================== #
    def get_graph_data(self) -> dict:
        if self.G is None:
            return {"nodes": [], "edges": []}

        # Pre-compute per-node volume stats in one pass over edges
        in_volume:  dict[str, float] = {}
        out_volume: dict[str, float] = {}
        for u, v, data in self.G.edges(data=True):
            amt = float(data.get("amount", 0))
            out_volume[u] = out_volume.get(u, 0.0) + amt
            in_volume[v]  = in_volume.get(v, 0.0)  + amt

        nodes_list = []
        for node in self.G.nodes():
            score    = self.suspicion_scores.get(node, 0)
            patterns = sorted(self.account_patterns.get(node, set()))
            ring_ids = [r["ring_id"] for r in self.fraud_rings if node in r["member_accounts"]]

            nodes_list.append({
                "id":               node,
                "label":            node,
                "suspicion_score":  score,
                "four_pillar_scores": self.four_pillar_scores.get(node, {}),
                "verdict":          self.enforcement_verdicts.get(node, "APPROVE"),
                "structural_role":  self.node_roles.get(node, "LEAF"),
                "detected_patterns": patterns,
                "explanation":      self._explanations.get(node, ""),
                "ring_ids":         ring_ids,
                # degree info
                "in_degree":        self.G.in_degree(node),
                "out_degree":       self.G.out_degree(node),
                # financial volume
                "total_incoming":   round(in_volume.get(node, 0.0), 2),
                "total_outgoing":   round(out_volume.get(node, 0.0), 2),
            })

        # Deduplicate edges for vis.js (collapse MultiDiGraph parallel edges)
        edge_map: dict[tuple[str, str], float] = {}
        for u, v, data in self.G.edges(data=True):
            key = (u, v)
            edge_map[key] = edge_map.get(key, 0) + float(data.get("amount", 1))

        edges_list = []
        for (u, v), total_amount in edge_map.items():
            edges_list.append({
                "from":  u,
                "to":    v,
                "value": max(1, min(6, total_amount / 1000)),
                "title": f"${total_amount:,.2f}",
            })

        return {"nodes": nodes_list, "edges": edges_list}

    # ================================================================== #
    #  ORCHESTRATOR — Recall-Optimized Pipeline                            #
    # ================================================================== #
    def run_all(self) -> dict:
        self._start_time = time.time()

        # ---- Stage 0: Business Immunity (BEFORE all detection) ----
        self._detect_business_immunity()

        # ---- Stage 1: Detection algorithms...
        print(f"[{time.time()-self._start_time:.2f}s] Stage 1: Detection algorithms...")
        self.detect_cycles()
        self.detect_shells()
        self.detect_velocity()
        self._extract_smurf_candidates()
        self._score_smurf_candidates()
        self.detect_structuring()
        self.detect_structuring()
        self._apply_rule_thresholds()

        # ---- Stage 1.5: Immune Account Cleanup ----
        # Strip fraud patterns from immune accounts (keep only immune type tag)
        immune_keep = {"payroll", "merchant"}
        for acc in self._immune_accounts:
            self.account_patterns[acc] = self.account_patterns[acc] & immune_keep

        # Remove immune accounts from candidate ring membership
        cleaned_candidates = []
        for cand in self._candidate_rings:
            clean_members = [m for m in cand["members"]
                             if m not in self._immune_accounts]
            if len(clean_members) >= 3:
                cand["members"] = sorted(clean_members)
                cleaned_candidates.append(cand)
        self._candidate_rings = cleaned_candidates

        # ---- Stage 2: Ring Consolidation + Arbitration (§2 + §4) ----
        self._consolidate_rings()

        # ---- Stage 3: Pattern Hierarchy ----
        self._apply_pattern_hierarchy()

        # ---- Stage 4: Risk Scoring & Verdicts ----
        self._assign_structural_roles()
        self.calculate_suspicion_scores()

        self._processing_time = time.time() - self._start_time

        # ---- Summary Print ----
        ring_types = defaultdict(int)
        for r in self.fraud_rings:
            ring_types[r["pattern_type"]] += 1
        flagged = sum(1 for s in self.suspicion_scores.values() if s > 0)

        print(f"\n{'='*50}")
        print(f"  HYBRID SENTINEL v6.0 — Detection Report")
        print(f"{'='*50}")
        print(f"  Rings detected: {len(self.fraud_rings)}")
        for rtype, cnt in sorted(ring_types.items()):
            print(f"    - {rtype}: {cnt}")
        print(f"  Flagged accounts: {flagged}")
        print(f"  Runtime: {self._processing_time:.2f}s")
        print(f"{'='*50}\n")

        return self.generate_json()
