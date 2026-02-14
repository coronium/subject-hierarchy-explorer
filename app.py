#!/usr/bin/env python3
"""
Subject Hierarchy Explorer — Cloud deployment version.

Loads precomputed co-occurrence data (no SQLite dependency).
Generate the data file locally with:
    cd ingest
    python examples/subject_hierarchy_explorer.py --export-data precomputed.json
"""

import json
import os
import time
from collections import defaultdict
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)


# =============================================================================
# Co-occurrence Engine (precomputed data only)
# =============================================================================

class CooccurrenceEngine:
    """Serves precomputed subject co-occurrence statistics."""

    def __init__(self):
        self.concept_names: dict[str, str] = {}
        self.concept_counts: dict[str, int] = {}
        self.total_citations = 0
        self.relationships: list[dict] = []
        self._loaded = False

    def load_precomputed(self, path: str):
        if self._loaded:
            return
        t0 = time.time()
        with open(path, 'r') as f:
            data = json.load(f)
        self.concept_names = data['concept_names']
        self.concept_counts = data['concept_counts']
        self.total_citations = data['total_citations']
        self.relationships = data['relationships']
        self._loaded = True
        t1 = time.time()
        print(f"Loaded precomputed data: {len(self.concept_names)} concepts, "
              f"{len(self.relationships)} relationships in {t1-t0:.1f}s")

    def get_filtered_relationships(self, min_narrower_count=10, min_cooc=5,
                                    min_p_broader=0.3, min_asymmetry=1.5,
                                    concept_filter=None, sort_by='asymmetry',
                                    sort_desc=True, limit=500):
        results = []
        concept_filter_lower = concept_filter.lower().strip() if concept_filter else None

        for r in self.relationships:
            if r['narrower_count'] < min_narrower_count:
                continue
            if r['cooc_count'] < min_cooc:
                continue
            if r['p_broader_given_narrower'] < min_p_broader:
                continue
            if r['asymmetry'] < min_asymmetry:
                continue
            if concept_filter_lower:
                if (concept_filter_lower not in r['narrower_name'].lower() and
                    concept_filter_lower not in r['broader_name'].lower()):
                    continue
            results.append(r)

        reverse = sort_desc
        if sort_by == 'asymmetry':
            results.sort(key=lambda r: r['asymmetry'], reverse=reverse)
        elif sort_by == 'p_broader_given_narrower':
            results.sort(key=lambda r: r['p_broader_given_narrower'], reverse=reverse)
        elif sort_by == 'cooc_count':
            results.sort(key=lambda r: r['cooc_count'], reverse=reverse)
        elif sort_by == 'narrower_name':
            results.sort(key=lambda r: r['narrower_name'].lower(), reverse=reverse)
        elif sort_by == 'broader_name':
            results.sort(key=lambda r: r['broader_name'].lower(), reverse=reverse)

        return results[:limit], len(results)

    def get_concept_tree(self, concept_name, min_p_broader=0.3, min_asymmetry=1.5,
                         min_cooc=3, min_count=5):
        concept_name_lower = concept_name.lower().strip()

        concept_id = None
        for cbid, name in self.concept_names.items():
            if name.lower() == concept_name_lower:
                concept_id = cbid
                break

        if not concept_id:
            matches = []
            for cbid, name in self.concept_names.items():
                if concept_name_lower in name.lower():
                    matches.append({'id': cbid, 'name': name, 'count': self.concept_counts.get(cbid, 0)})
            matches.sort(key=lambda x: x['count'], reverse=True)
            return {'suggestions': matches[:20], 'broader': [], 'narrower': [], 'symmetric': []}

        broader = []
        narrower = []
        symmetric = []

        for r in self.relationships:
            passes_filters = (r['cooc_count'] >= min_cooc and
                              r['narrower_count'] >= min_count)
            if not passes_filters:
                continue

            if r['narrower_id'] == concept_id:
                if r['p_broader_given_narrower'] >= min_p_broader and r['asymmetry'] >= min_asymmetry:
                    broader.append(r)
            elif r['broader_id'] == concept_id:
                if r['p_broader_given_narrower'] >= min_p_broader and r['asymmetry'] >= min_asymmetry:
                    narrower.append(r)

        for r in self.relationships:
            if r['cooc_count'] < min_cooc:
                continue
            if r['narrower_id'] == concept_id or r['broader_id'] == concept_id:
                if r['asymmetry'] < min_asymmetry and r['p_broader_given_narrower'] >= 0.2:
                    symmetric.append(r)

        broader.sort(key=lambda r: r['p_broader_given_narrower'], reverse=True)
        narrower.sort(key=lambda r: r['p_broader_given_narrower'], reverse=True)
        symmetric.sort(key=lambda r: r['cooc_count'], reverse=True)

        return {
            'concept_id': concept_id,
            'concept_name': self.concept_names[concept_id],
            'concept_count': self.concept_counts[concept_id],
            'broader': broader[:50],
            'narrower': narrower[:50],
            'symmetric': symmetric[:30],
        }

    def get_all_concepts(self, min_count=5):
        concepts = []
        for cbid, name in self.concept_names.items():
            count = self.concept_counts.get(cbid, 0)
            if count >= min_count:
                concepts.append({'id': cbid, 'name': name, 'count': count})
        concepts.sort(key=lambda x: x['count'], reverse=True)
        return concepts

    def build_hierarchy_tree(self, min_p_broader=0.5, min_asymmetry=2.0,
                              min_cooc=5, min_count=10):
        children_of: dict[str, list[dict]] = defaultdict(list)
        has_parent: set[str] = set()

        for r in self.relationships:
            if (r['p_broader_given_narrower'] >= min_p_broader and
                r['asymmetry'] >= min_asymmetry and
                r['cooc_count'] >= min_cooc and
                r['narrower_count'] >= min_count):
                children_of[r['broader_id']].append({
                    'id': r['narrower_id'],
                    'name': r['narrower_name'],
                    'count': r['narrower_count'],
                    'p': r['p_broader_given_narrower'],
                    'asymmetry': r['asymmetry'],
                })
                has_parent.add(r['narrower_id'])

        for parent_id in children_of:
            children_of[parent_id].sort(key=lambda x: x['p'], reverse=True)

        roots = []
        for parent_id in children_of:
            if parent_id not in has_parent:
                roots.append({
                    'id': parent_id,
                    'name': self.concept_names[parent_id],
                    'count': self.concept_counts[parent_id],
                })

        roots.sort(key=lambda x: x['count'], reverse=True)

        def build_subtree(node_id, depth=0, visited=None):
            if visited is None:
                visited = set()
            if node_id in visited or depth > 5:
                return []
            visited.add(node_id)
            result = []
            for child in children_of.get(node_id, []):
                subtree = build_subtree(child['id'], depth + 1, visited.copy())
                result.append({**child, 'children': subtree})
            return result

        tree = []
        for root in roots:
            subtree = build_subtree(root['id'])
            if subtree:
                tree.append({**root, 'children': subtree})

        return tree

    def get_stats(self):
        return {
            'total_concepts': len(self.concept_names),
            'total_citations': self.total_citations,
            'total_pairs': len(self.relationships),
            'total_relationships': len(self.relationships),
        }


# Global engine — loaded at import time for gunicorn --preload
engine = CooccurrenceEngine()
data_path = os.environ.get('PRECOMPUTED_DATA',
    str(Path(__file__).parent / 'subject_cooccurrence_data.json'))
engine.load_precomputed(data_path)


# =============================================================================
# API Routes
# =============================================================================

@app.route('/api/stats')
def api_stats():
    return jsonify(engine.get_stats())


@app.route('/api/relationships')
def api_relationships():
    results, total = engine.get_filtered_relationships(
        min_narrower_count=int(request.args.get('min_count', 10)),
        min_cooc=int(request.args.get('min_cooc', 5)),
        min_p_broader=float(request.args.get('min_p', 0.3)),
        min_asymmetry=float(request.args.get('min_asym', 1.5)),
        concept_filter=request.args.get('filter', None),
        sort_by=request.args.get('sort', 'asymmetry'),
        sort_desc=request.args.get('desc', 'true') == 'true',
        limit=int(request.args.get('limit', 500)),
    )
    return jsonify({'results': results, 'total': total})


@app.route('/api/concept_tree')
def api_concept_tree():
    concept = request.args.get('concept', '')
    if not concept:
        return jsonify({'error': 'No concept specified'}), 400

    tree = engine.get_concept_tree(
        concept,
        min_p_broader=float(request.args.get('min_p', 0.3)),
        min_asymmetry=float(request.args.get('min_asym', 1.5)),
        min_cooc=int(request.args.get('min_cooc', 3)),
        min_count=int(request.args.get('min_count', 5)),
    )
    return jsonify(tree)


@app.route('/api/hierarchy_tree')
def api_hierarchy_tree():
    tree = engine.build_hierarchy_tree(
        min_p_broader=float(request.args.get('min_p', 0.5)),
        min_asymmetry=float(request.args.get('min_asym', 2.0)),
        min_cooc=int(request.args.get('min_cooc', 5)),
        min_count=int(request.args.get('min_count', 10)),
    )
    return jsonify(tree)


@app.route('/api/concepts')
def api_concepts():
    min_count = int(request.args.get('min_count', 5))
    concepts = engine.get_all_concepts(min_count=min_count)
    return jsonify(concepts)


@app.route('/api/export_yaml')
def api_export_yaml():
    min_p = float(request.args.get('min_p', 0.6))
    min_asym = float(request.args.get('min_asym', 2.5))
    min_cooc = int(request.args.get('min_cooc', 5))
    min_count = int(request.args.get('min_count', 10))

    results, total = engine.get_filtered_relationships(
        min_narrower_count=min_count,
        min_cooc=min_cooc,
        min_p_broader=min_p,
        min_asymmetry=min_asym,
        sort_by='broader_name',
        sort_desc=False,
        limit=5000,
    )

    groups: dict[str, list] = defaultdict(list)
    for r in results:
        groups[r['broader_name']].append(r)

    lines = [
        "# CB Co-occurrence Relationships (Empirically Derived)",
        f"# Filters: P(broader|narrower) >= {min_p}, asymmetry >= {min_asym}, "
        f"co-occurrences >= {min_cooc}, min citations >= {min_count}",
        f"# Total relationships: {total}",
        "",
        "cb_cooccurrence:",
    ]

    for broader_name in sorted(groups.keys()):
        narrower_list = groups[broader_name]
        narrower_list.sort(key=lambda r: r['p_broader_given_narrower'], reverse=True)
        lines.append(f"  - broader: {broader_name}")
        lines.append(f"    narrower:")
        for r in narrower_list:
            pct = round(r['p_broader_given_narrower'] * 100, 1)
            lines.append(f"      - {r['narrower_name']}  # {pct}%")
        lines.append("")

    return '\n'.join(lines), 200, {'Content-Type': 'text/plain; charset=utf-8'}


# =============================================================================
# HTML Template
# =============================================================================

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Subject Hierarchy Explorer — IsisCB</title>
<style>
:root {
    --deep-space-blue: #173753;
    --sky-reflection: #6daedb;
    --blue-bell: #2892d7;
    --charcoal-blue: #1b4353;
    --cornflower-ocean: #1d70a2;
    --sky-light: #e8f4fb;
    --sky-lighter: #f4f9fd;
    --color-text: var(--deep-space-blue);
    --color-primary: var(--blue-bell);
    --color-primary-hover: var(--cornflower-ocean);
    --success: #28a745;
    --warning: #e9a100;
    --danger: #dc3545;
    --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --font-mono: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: var(--font-sans);
    background: var(--sky-lighter);
    color: var(--color-text);
    font-size: 14px;
    line-height: 1.5;
}

header {
    background: linear-gradient(135deg, var(--deep-space-blue) 0%, var(--charcoal-blue) 100%);
    color: white;
    padding: 16px 24px;
    display: flex;
    align-items: center;
    gap: 20px;
}
header .logo { font-size: 11px; line-height: 1.2; opacity: 0.7; letter-spacing: 2px; }
header h1 { font-size: 20px; font-weight: 600; }
header .subtitle { font-size: 12px; opacity: 0.8; }
header .stats { margin-left: auto; font-size: 12px; opacity: 0.7; }

.tabs {
    display: flex;
    background: var(--deep-space-blue);
    padding: 0 24px;
    gap: 0;
}
.tab {
    padding: 10px 20px;
    color: rgba(255,255,255,0.6);
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    border-bottom: 2px solid transparent;
    transition: all 0.2s;
}
.tab:hover { color: rgba(255,255,255,0.9); }
.tab.active { color: white; border-bottom-color: var(--sky-reflection); }

.container { max-width: 1400px; margin: 0 auto; padding: 20px 24px; }

.tab-content { display: none; }
.tab-content.active { display: block; }

.filters {
    background: white;
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    align-items: flex-end;
}
.filter-group { display: flex; flex-direction: column; gap: 4px; }
.filter-group label { font-size: 11px; font-weight: 600; color: var(--charcoal-blue); text-transform: uppercase; letter-spacing: 0.5px; }
.filter-group input, .filter-group select {
    padding: 6px 10px;
    border: 1px solid #d0d5dd;
    border-radius: 6px;
    font-size: 13px;
    font-family: var(--font-sans);
    min-width: 80px;
}
.filter-group input:focus, .filter-group select:focus {
    outline: none;
    border-color: var(--color-primary);
    box-shadow: 0 0 0 2px rgba(40,146,215,0.15);
}
.filter-group input[type="text"] { min-width: 200px; }

button {
    padding: 7px 16px;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    font-family: var(--font-sans);
    transition: background 0.2s;
}
.btn-primary { background: var(--color-primary); color: white; }
.btn-primary:hover { background: var(--color-primary-hover); }

.results-info { font-size: 12px; color: #666; margin-bottom: 8px; }

table {
    width: 100%;
    border-collapse: collapse;
    background: white;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    font-size: 13px;
}
th {
    background: var(--sky-light);
    padding: 10px 12px;
    text-align: left;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--charcoal-blue);
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
}
th:hover { background: #d4ecf7; }
th .sort-arrow { margin-left: 4px; opacity: 0.4; }
th.sorted .sort-arrow { opacity: 1; }
td { padding: 8px 12px; border-top: 1px solid #f0f0f0; }
tr:hover { background: #fafbfc; }

.concept-link { color: var(--color-primary); cursor: pointer; text-decoration: none; }
.concept-link:hover { text-decoration: underline; }

.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.badge-strong { background: #dcfce7; color: #166534; }
.badge-moderate { background: #fef9c3; color: #854d0e; }
.badge-weak { background: #fee2e2; color: #991b1b; }

.prob-bar { display: inline-flex; align-items: center; gap: 6px; min-width: 120px; }
.prob-bar-track { width: 60px; height: 6px; background: #e5e7eb; border-radius: 3px; overflow: hidden; }
.prob-bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.prob-value { font-family: var(--font-mono); font-size: 12px; min-width: 40px; }

.concept-search {
    background: white; border-radius: 8px; padding: 20px;
    margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.concept-search input {
    width: 100%; padding: 10px 14px; border: 2px solid #e5e7eb;
    border-radius: 8px; font-size: 15px; font-family: var(--font-sans);
}
.concept-search input:focus {
    outline: none; border-color: var(--color-primary);
    box-shadow: 0 0 0 3px rgba(40,146,215,0.15);
}

.concept-detail { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.concept-panel { background: white; border-radius: 8px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.concept-panel h3 { font-size: 14px; font-weight: 600; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 2px solid var(--sky-light); }
.concept-panel.broader h3 { color: var(--cornflower-ocean); border-bottom-color: var(--sky-reflection); }
.concept-panel.narrower h3 { color: var(--success); border-bottom-color: #a7f3d0; }
.concept-panel.symmetric h3 { color: var(--warning); border-bottom-color: #fde68a; }
.concept-panel.full-width { grid-column: 1 / -1; }

.rel-item { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid #f5f5f5; }
.rel-item:last-child { border-bottom: none; }
.rel-item .name { flex: 1; }
.rel-item .meta { font-size: 11px; color: #888; font-family: var(--font-mono); }

.tree-container { background: white; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.tree-node { padding-left: 24px; position: relative; }
.tree-node::before { content: ''; position: absolute; left: 8px; top: 0; bottom: 0; width: 1px; background: #e5e7eb; }
.tree-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; position: relative; }
.tree-item::before { content: ''; position: absolute; left: -16px; top: 50%; width: 12px; height: 1px; background: #e5e7eb; }
.tree-root { padding-left: 0; }
.tree-root::before { display: none; }
.tree-root > .tree-item::before { display: none; }
.tree-toggle {
    width: 18px; height: 18px; border-radius: 4px; border: 1px solid #d0d5dd;
    background: white; cursor: pointer; display: flex; align-items: center;
    justify-content: center; font-size: 10px; color: #666; flex-shrink: 0;
}
.tree-toggle:hover { background: var(--sky-light); }
.tree-label { font-weight: 500; }
.tree-count { font-size: 11px; color: #888; font-family: var(--font-mono); }
.tree-prob { font-size: 11px; color: var(--cornflower-ocean); font-family: var(--font-mono); }

.suggestions { background: white; border-radius: 8px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.suggestion-item {
    display: inline-block; padding: 4px 12px; margin: 3px;
    background: var(--sky-light); border-radius: 16px; font-size: 13px;
    cursor: pointer; transition: background 0.2s;
}
.suggestion-item:hover { background: var(--sky-reflection); color: white; }
.suggestion-count { font-size: 11px; opacity: 0.7; }

.loading { text-align: center; padding: 40px; color: #888; }
.empty-state { text-align: center; padding: 40px; color: #888; }

.export-panel { background: white; border-radius: 8px; padding: 16px 20px; margin-top: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.export-panel pre {
    background: #f8f9fa; padding: 16px; border-radius: 6px; overflow-x: auto;
    font-family: var(--font-mono); font-size: 12px; line-height: 1.6;
    max-height: 500px; overflow-y: auto;
}
</style>
</head>
<body>

<header>
    <div class="logo">━━━━━━━━━━━━<br>━━━━━━━━<br>━━━━━━━━━━━━━━</div>
    <div>
        <h1>Subject Hierarchy Explorer</h1>
        <div class="subtitle">Discovering broader/narrower relationships from IsisCB citation co-occurrence</div>
    </div>
    <div class="stats" id="headerStats">Loading...</div>
</header>

<div class="tabs">
    <div class="tab active" onclick="switchTab('relationships')">Relationships Table</div>
    <div class="tab" onclick="switchTab('explorer')">Concept Explorer</div>
    <div class="tab" onclick="switchTab('tree')">Hierarchy Tree</div>
    <div class="tab" onclick="switchTab('export')">Export</div>
</div>

<div class="container">

<div class="tab-content active" id="tab-relationships">
    <div class="filters">
        <div class="filter-group">
            <label>Search concepts</label>
            <input type="text" id="filterText" placeholder="e.g. astronomy, physics..." onkeydown="if(event.key==='Enter') loadRelationships()">
        </div>
        <div class="filter-group">
            <label>Min P(B|A)</label>
            <input type="number" id="filterMinP" value="0.3" min="0" max="1" step="0.05">
        </div>
        <div class="filter-group">
            <label>Min asymmetry</label>
            <input type="number" id="filterMinAsym" value="1.5" min="1" step="0.5">
        </div>
        <div class="filter-group">
            <label>Min co-occurrences</label>
            <input type="number" id="filterMinCooc" value="5" min="1" step="1">
        </div>
        <div class="filter-group">
            <label>Min citations</label>
            <input type="number" id="filterMinCount" value="10" min="1" step="5">
        </div>
        <div class="filter-group">
            <label>&nbsp;</label>
            <button class="btn-primary" onclick="loadRelationships()">Apply Filters</button>
        </div>
    </div>
    <div class="results-info" id="resultsInfo"></div>
    <table id="relTable">
        <thead>
            <tr>
                <th onclick="sortBy('narrower_name')">Narrower Term <span class="sort-arrow">&#9650;</span></th>
                <th onclick="sortBy('broader_name')">Broader Term <span class="sort-arrow">&#9650;</span></th>
                <th onclick="sortBy('p_broader_given_narrower')" class="sorted">P(B|A) <span class="sort-arrow">&#9660;</span></th>
                <th onclick="sortBy('p_narrower_given_broader')">P(A|B) <span class="sort-arrow">&#9650;</span></th>
                <th onclick="sortBy('asymmetry')">Asymmetry <span class="sort-arrow">&#9650;</span></th>
                <th onclick="sortBy('cooc_count')">Co-occur <span class="sort-arrow">&#9650;</span></th>
                <th>Counts</th>
            </tr>
        </thead>
        <tbody id="relBody"></tbody>
    </table>
</div>

<div class="tab-content" id="tab-explorer">
    <div class="concept-search">
        <input type="text" id="conceptInput" placeholder="Type a concept name (e.g. Astronomy, Medicine, Physics)..."
               onkeydown="if(event.key==='Enter') exploreConcept()">
        <div style="margin-top: 8px; font-size: 12px; color: #888;">
            Press Enter to explore. Shows all broader terms (this concept implies those),
            narrower terms (those imply this concept), and symmetric relationships.
        </div>
    </div>
    <div id="conceptResults"></div>
</div>

<div class="tab-content" id="tab-tree">
    <div class="filters">
        <div class="filter-group">
            <label>Min P(B|A)</label>
            <input type="number" id="treeMinP" value="0.5" min="0" max="1" step="0.05">
        </div>
        <div class="filter-group">
            <label>Min asymmetry</label>
            <input type="number" id="treeMinAsym" value="2.0" min="1" step="0.5">
        </div>
        <div class="filter-group">
            <label>Min co-occurrences</label>
            <input type="number" id="treeMinCooc" value="5" min="1" step="1">
        </div>
        <div class="filter-group">
            <label>Min citations</label>
            <input type="number" id="treeMinCount" value="10" min="1" step="5">
        </div>
        <div class="filter-group">
            <label>&nbsp;</label>
            <button class="btn-primary" onclick="loadTree()">Build Tree</button>
        </div>
    </div>
    <div id="treeContainer" class="tree-container">
        <div class="empty-state">Click "Build Tree" to generate the hierarchy.</div>
    </div>
</div>

<div class="tab-content" id="tab-export">
    <div class="filters">
        <div class="filter-group">
            <label>Min P(B|A)</label>
            <input type="number" id="exportMinP" value="0.6" min="0" max="1" step="0.05">
        </div>
        <div class="filter-group">
            <label>Min asymmetry</label>
            <input type="number" id="exportMinAsym" value="2.5" min="1" step="0.5">
        </div>
        <div class="filter-group">
            <label>Min co-occurrences</label>
            <input type="number" id="exportMinCooc" value="5" min="1" step="1">
        </div>
        <div class="filter-group">
            <label>Min citations</label>
            <input type="number" id="exportMinCount" value="10" min="1" step="5">
        </div>
        <div class="filter-group">
            <label>&nbsp;</label>
            <button class="btn-primary" onclick="loadExport()">Generate YAML</button>
        </div>
    </div>
    <div class="export-panel" id="exportPanel">
        <p style="margin-bottom: 12px; font-size: 13px; color: #666;">
            Generates YAML in the format used by <code>interest_synonyms_hierarchy.yaml</code>.
            Adjust filters above and click "Generate YAML".
        </p>
        <pre id="exportContent">Click "Generate YAML" to generate output.</pre>
    </div>
</div>

</div>

<script>
let currentSort = 'asymmetry';
let currentSortDesc = true;

function switchTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    const tabs = document.querySelectorAll('.tab');
    const tabNames = ['relationships', 'explorer', 'tree', 'export'];
    const idx = tabNames.indexOf(name);
    if (idx >= 0) tabs[idx].classList.add('active');
    document.getElementById('tab-' + name).classList.add('active');
}

async function loadStats() {
    const resp = await fetch('/api/stats');
    const data = await resp.json();
    document.getElementById('headerStats').innerHTML =
        `${data.total_concepts.toLocaleString()} concepts &middot; ` +
        `${data.total_citations.toLocaleString()} citations &middot; ` +
        `${data.total_pairs.toLocaleString()} co-occurring pairs`;
}

function probBar(value, color) {
    const pct = Math.round(value * 100);
    const barColor = color || (pct >= 80 ? '#28a745' : pct >= 50 ? '#e9a100' : '#6b7280');
    return `<div class="prob-bar">
        <div class="prob-bar-track"><div class="prob-bar-fill" style="width:${pct}%;background:${barColor}"></div></div>
        <span class="prob-value">${pct}%</span>
    </div>`;
}

function asymBadge(value) {
    if (value >= 5) return `<span class="badge badge-strong">${value}x</span>`;
    if (value >= 2.5) return `<span class="badge badge-moderate">${value}x</span>`;
    return `<span class="badge badge-weak">${value}x</span>`;
}

function sortBy(field) {
    if (currentSort === field) { currentSortDesc = !currentSortDesc; }
    else { currentSort = field; currentSortDesc = true; }
    loadRelationships();
}

async function loadRelationships() {
    const params = new URLSearchParams({
        filter: document.getElementById('filterText').value,
        min_p: document.getElementById('filterMinP').value,
        min_asym: document.getElementById('filterMinAsym').value,
        min_cooc: document.getElementById('filterMinCooc').value,
        min_count: document.getElementById('filterMinCount').value,
        sort: currentSort, desc: currentSortDesc, limit: 500,
    });
    const resp = await fetch('/api/relationships?' + params);
    const data = await resp.json();
    document.getElementById('resultsInfo').textContent =
        `Showing ${data.results.length} of ${data.total} relationships`;
    const tbody = document.getElementById('relBody');
    tbody.innerHTML = data.results.map(r => `
        <tr>
            <td><a class="concept-link" onclick="jumpToConcept('${escHtml(r.narrower_name)}')">${escHtml(r.narrower_name)}</a></td>
            <td><a class="concept-link" onclick="jumpToConcept('${escHtml(r.broader_name)}')">${escHtml(r.broader_name)}</a></td>
            <td>${probBar(r.p_broader_given_narrower)}</td>
            <td>${probBar(r.p_narrower_given_broader, '#6b7280')}</td>
            <td>${asymBadge(r.asymmetry)}</td>
            <td style="font-family:var(--font-mono);font-size:12px;">${r.cooc_count}</td>
            <td style="font-size:11px;color:#888;">${r.narrower_count} / ${r.broader_count}</td>
        </tr>
    `).join('');
}

async function exploreConcept(name) {
    const conceptName = name || document.getElementById('conceptInput').value;
    if (!conceptName.trim()) return;
    document.getElementById('conceptInput').value = conceptName;
    const params = new URLSearchParams({ concept: conceptName, min_p: 0.2, min_asym: 1.3, min_cooc: 3, min_count: 5 });
    const resp = await fetch('/api/concept_tree?' + params);
    const data = await resp.json();
    const container = document.getElementById('conceptResults');
    if (data.suggestions) {
        container.innerHTML = `<div class="suggestions"><p style="margin-bottom:10px;font-weight:600;">Did you mean:</p>
            ${data.suggestions.map(s => `<span class="suggestion-item" onclick="exploreConcept('${escHtml(s.name)}')">${escHtml(s.name)} <span class="suggestion-count">(${s.count})</span></span>`).join('')}</div>`;
        return;
    }
    let html = `<div style="margin-bottom:16px;font-size:16px;font-weight:600;">${escHtml(data.concept_name)} <span style="font-size:13px;font-weight:400;color:#888;margin-left:8px;">${data.concept_count} citations</span></div>`;
    html += '<div class="concept-detail">';
    html += `<div class="concept-panel broader"><h3>Broader Terms (${data.broader.length})</h3><p style="font-size:11px;color:#888;margin-bottom:8px;">When "${escHtml(data.concept_name)}" appears, these also tend to appear</p>`;
    if (data.broader.length === 0) { html += '<div style="color:#888;font-size:13px;">No broader terms found at current thresholds</div>'; }
    else { html += data.broader.map(r => `<div class="rel-item"><a class="concept-link name" onclick="exploreConcept('${escHtml(r.broader_name)}')">${escHtml(r.broader_name)}</a><span class="meta">${Math.round(r.p_broader_given_narrower*100)}%</span>${asymBadge(r.asymmetry)}</div>`).join(''); }
    html += '</div>';
    html += `<div class="concept-panel narrower"><h3>Narrower Terms (${data.narrower.length})</h3><p style="font-size:11px;color:#888;margin-bottom:8px;">These concepts tend to imply "${escHtml(data.concept_name)}"</p>`;
    if (data.narrower.length === 0) { html += '<div style="color:#888;font-size:13px;">No narrower terms found at current thresholds</div>'; }
    else { html += data.narrower.map(r => `<div class="rel-item"><a class="concept-link name" onclick="exploreConcept('${escHtml(r.narrower_name)}')">${escHtml(r.narrower_name)}</a><span class="meta">${Math.round(r.p_broader_given_narrower*100)}%</span>${asymBadge(r.asymmetry)}</div>`).join(''); }
    html += '</div>';
    if (data.symmetric.length > 0) {
        html += `<div class="concept-panel symmetric full-width"><h3>Symmetric / Peer Relationships (${data.symmetric.length})</h3><p style="font-size:11px;color:#888;margin-bottom:8px;">Concepts that frequently co-occur without a clear hierarchy</p>`;
        html += data.symmetric.map(r => {
            const otherName = r.narrower_name === data.concept_name ? r.broader_name : r.narrower_name;
            return `<div class="rel-item"><a class="concept-link name" onclick="exploreConcept('${escHtml(otherName)}')">${escHtml(otherName)}</a><span class="meta">${r.cooc_count} co-occ</span></div>`;
        }).join('');
        html += '</div>';
    }
    html += '</div>';
    container.innerHTML = html;
}

function jumpToConcept(name) {
    document.getElementById('conceptInput').value = name;
    switchTab('explorer');
    exploreConcept(name);
}

async function loadTree() {
    const container = document.getElementById('treeContainer');
    container.innerHTML = '<div class="loading">Building hierarchy tree...</div>';
    const params = new URLSearchParams({
        min_p: document.getElementById('treeMinP').value,
        min_asym: document.getElementById('treeMinAsym').value,
        min_cooc: document.getElementById('treeMinCooc').value,
        min_count: document.getElementById('treeMinCount').value,
    });
    const resp = await fetch('/api/hierarchy_tree?' + params);
    const tree = await resp.json();
    if (tree.length === 0) { container.innerHTML = '<div class="empty-state">No hierarchy found at these thresholds. Try lowering the filters.</div>'; return; }
    container.innerHTML = `<p style="margin-bottom:16px;font-size:13px;color:#666;">${tree.length} root concepts found. Click arrows to expand/collapse.</p>` + tree.map(node => renderTreeNode(node, true)).join('');
}

function renderTreeNode(node, isRoot) {
    const hasChildren = node.children && node.children.length > 0;
    const rootClass = isRoot ? ' tree-root' : '';
    const probStr = node.p ? `<span class="tree-prob">${Math.round(node.p * 100)}%</span>` : '';
    let html = `<div class="tree-node${rootClass}"><div class="tree-item">
        ${hasChildren ? `<button class="tree-toggle" onclick="toggleTreeNode(this)">+</button>` : '<span style="width:18px;display:inline-block;"></span>'}
        <a class="concept-link tree-label" onclick="jumpToConcept('${escHtml(node.name)}')">${escHtml(node.name)}</a>
        <span class="tree-count">(${node.count})</span>${probStr}</div>`;
    if (hasChildren) {
        html += `<div class="tree-children" style="display:none;">`;
        html += node.children.map(child => renderTreeNode(child, false)).join('');
        html += '</div>';
    }
    html += '</div>';
    return html;
}

function toggleTreeNode(btn) {
    const children = btn.closest('.tree-node').querySelector('.tree-children');
    if (children) { const h = children.style.display === 'none'; children.style.display = h ? 'block' : 'none'; btn.textContent = h ? '\u2212' : '+'; }
}

async function loadExport() {
    const params = new URLSearchParams({
        min_p: document.getElementById('exportMinP').value,
        min_asym: document.getElementById('exportMinAsym').value,
        min_cooc: document.getElementById('exportMinCooc').value,
        min_count: document.getElementById('exportMinCount').value,
    });
    const resp = await fetch('/api/export_yaml?' + params);
    const text = await resp.text();
    document.getElementById('exportContent').textContent = text;
}

function escHtml(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

loadStats();
loadRelationships();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5030))
    app.run(host='0.0.0.0', port=port, debug=False)
