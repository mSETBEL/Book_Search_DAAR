"""Outils de centralité pour les benchmarks (n'altère pas le code du projet).

- load_graph        : lit books + jaccard_edges depuis PostgreSQL
- project_pagerank  : appelle TEL QUEL backend/app/algorithms/ranking/pagerank.py
- pagerank_reference: PageRank « de référence » (matrice creuse, bonne orientation),
                      uniquement pour VALIDER et CHRONOMÉTRER à titre de comparaison
- closeness / degree / betweenness (optionnel) pour comparer les indices
"""
import sys
import time

import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import shortest_path

from common import BACKEND

sys.path.insert(0, str(BACKEND))


def load_graph(conn):
    """Retourne (ids, meta, edges_undirected) ; edges = [(a, b, similarité)]."""
    meta = {r[0]: {"title": r[1], "author": r[2], "words": r[3], "pagerank": r[4]}
            for r in conn.execute(
                "SELECT gutenberg_id, title, author, word_count, pagerank FROM books "
                "ORDER BY gutenberg_id")}
    ids = list(meta)
    edges = [(a, b, 1.0 - d) for a, b, d in conn.execute(
        "SELECT book_a, book_b, distance FROM jaccard_edges")]
    return ids, meta, edges


def symmetrize(edges):
    """Le graphe de Jaccard est stocké comme une arête par paire (a<b) ;
    PageRank travaille sur un graphe orienté : on met a→b et b→a."""
    out = []
    for a, b, w in edges:
        out.append((a, b, w))
        out.append((b, a, w))
    return out


def project_pagerank(edges, ids):
    """PageRank du projet, appelé tel quel. Retourne (scores dict, secondes)."""
    from app.algorithms.ranking.pagerank import pagerank
    t0 = time.perf_counter()
    scores = pagerank(symmetrize(edges), ids)
    return {k: float(v) for k, v in scores.items()}, time.perf_counter() - t0


def pagerank_reference(edges, ids, damping=0.85, tol=1e-12, maxit=500):
    """PageRank classique : x <- d (Pᵀ x + masse des sommets sans sortie / n) + (1-d)/n,
    P = D⁻¹ A (stochastique par lignes), matrice creuse CSR."""
    t0 = time.perf_counter()
    n = len(ids)
    idx = {b: i for i, b in enumerate(ids)}
    sym = symmetrize(edges)
    r = np.fromiter((idx[a] for a, _, _ in sym), dtype=np.int64, count=len(sym))
    c = np.fromiter((idx[b] for _, b, _ in sym), dtype=np.int64, count=len(sym))
    w = np.fromiter((x for _, _, x in sym), dtype=float, count=len(sym))
    A = sp.csr_matrix((w, (r, c)), shape=(n, n))
    rs = np.asarray(A.sum(axis=1)).ravel()
    inv = np.divide(1.0, rs, out=np.zeros(n), where=rs > 0)
    P = sp.diags(inv) @ A
    PT = P.T.tocsr()
    dangling = rs == 0
    x = np.ones(n) / n
    it = 0
    for it in range(1, maxit + 1):
        nx = damping * (PT @ x + x[dangling].sum() / n) + (1 - damping) / n
        done = np.abs(nx - x).sum() < tol
        x = nx
        if done:
            break
    x /= x.sum()
    return {b: float(x[idx[b]]) for b in ids}, time.perf_counter() - t0, it


def degrees(edges, ids):
    d = {b: 0 for b in ids}
    for a, b, _ in edges:
        d[a] += 1
        d[b] += 1
    return d


def closeness(edges, ids):
    """Closeness normalisée de Wasserman-Faust (adaptée aux graphes non connexes) :
    C(v) = (r-1)/(n-1) * (r-1)/Σ d(v,u),  r = nombre de sommets atteignables (v inclus)."""
    n = len(ids)
    idx = {b: i for i, b in enumerate(ids)}
    r = [idx[a] for a, _, _ in edges] + [idx[b] for _, b, _ in edges]
    c = [idx[b] for _, b, _ in edges] + [idx[a] for a, _, _ in edges]
    A = sp.csr_matrix((np.ones(len(r)), (r, c)), shape=(n, n))
    D = shortest_path(A, method="D", unweighted=True, directed=False)
    out = {}
    for i, b in enumerate(ids):
        row = D[i]
        reach = np.isfinite(row)
        rr = int(reach.sum())
        s = row[reach].sum()
        out[b] = ((rr - 1) / (n - 1)) * ((rr - 1) / s) if s > 0 and n > 1 else 0.0
    return out


def betweenness(edges, ids):
    """Betweenness (Brandes) via networkx si disponible, sinon None."""
    try:
        import networkx as nx
    except ImportError:
        return None, None
    g = nx.Graph()
    g.add_nodes_from(ids)
    g.add_edges_from((a, b) for a, b, _ in edges)
    t0 = time.perf_counter()
    bc = nx.betweenness_centrality(g, normalized=True)
    return bc, time.perf_counter() - t0


def spearman(x, y):
    from scipy.stats import spearmanr
    r = spearmanr(x, y)
    return float(r.statistic if hasattr(r, "statistic") else r[0])
