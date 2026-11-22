#!/usr/bin/env python3
"""
Exemples de centralité sur un échantillon de livres (exigé par l'énoncé : définition,
calcul ET résultat de l'indice sur des extraits pertinents de quelques livres).

Lit le graphe de Jaccard de la base de benchmark (à lancer après run_benchmark.py,
donc sur la bibliothèque complète) et produit :
  - les statistiques du graphe (degré, composantes connexes)
  - le PageRank du PROJET (appelé tel quel) comparé à un PageRank de référence
  - une comparaison PageRank / degré / closeness / betweenness (corrélations de Spearman, temps de calcul)
  - le top / flop 10 par PageRank, et 3 « fiches livre » : mots-clés TF-IDF, voisins, calcul de Jaccard détaillé
  - results/centrality.json et results/centrality_tables.tex (tableaux prêts pour le rapport)

    python benchmarks/bench_centrality.py
    python benchmarks/bench_centrality.py --books 1342 2701 84      # choisir les livres des fiches
"""
import argparse
import re
import time

import numpy as np
import psycopg
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

import centrality_lib as cl
from common import DEFAULT_ADMIN_URL, RESULTS, db_url, save_json

from app.algorithms.ranking.jaccard import jaccard_similarity, top_n_keywords  # code du projet, tel quel


def tex(s):
    s = str(s or "")
    for a, b in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                 ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\~{}"), ("^", r"\^{}")]:
        s = s.replace(a, b)
    return s


def short(s, n=48):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def keywords_of(conn, book_id, doc_freq, n_docs, n=500):
    counts = dict(conn.execute("SELECT term, occurrences FROM inverted_index WHERE book_id=%s", (book_id,)))
    return counts, top_n_keywords(counts, n=n, doc_freq=doc_freq, n_docs=n_docs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--admin-url", default=DEFAULT_ADMIN_URL)
    ap.add_argument("--books", type=int, nargs="*", help="ids Gutenberg des 3 livres des fiches")
    ap.add_argument("--no-betweenness", action="store_true")
    args = ap.parse_args()

    with psycopg.connect(db_url(args.admin_url), autocommit=True) as conn:
        ids, meta, edges = cl.load_graph(conn)
        n = len(ids)
        if not edges:
            raise SystemExit("Graphe vide : lancer run_benchmark.py d'abord.")
        out = {"n_books": n, "n_edges": len(edges)}

        # ---- structure du graphe
        deg = cl.degrees(edges, ids)
        idx = {b: i for i, b in enumerate(ids)}
        A = csr_matrix((np.ones(len(edges)), ([idx[a] for a, _, _ in edges], [idx[b] for _, b, _ in edges])),
                       shape=(n, n))
        ncomp, labels = connected_components(A, directed=False)
        sizes = np.bincount(labels)
        dv = np.array([deg[b] for b in ids])
        out["graph"] = {"avg_degree": float(dv.mean()), "median_degree": float(np.median(dv)),
                        "max_degree": int(dv.max()), "min_degree": int(dv.min()),
                        "isolated": int((dv == 0).sum()), "components": int(ncomp),
                        "giant_component": int(sizes.max()),
                        "avg_similarity": float(np.mean([w for _, _, w in edges])),
                        "degree_histogram": {int(k): int(v) for k, v in zip(*np.unique(dv, return_counts=True))}}
        print(f"{n} livres, {len(edges)} arêtes, degré moyen {dv.mean():.1f} (max {dv.max()}), "
              f"{ncomp} composante(s) connexe(s), plus grande = {sizes.max()}")

        # ---- indices de centralité (+ temps de calcul)
        timing = {}
        pr_proj, timing["pagerank_project"] = cl.project_pagerank(edges, ids)
        pr_ref, timing["pagerank_reference"], iters = cl.pagerank_reference(edges, ids)
        t0 = time.perf_counter()
        clo = cl.closeness(edges, ids)
        timing["closeness"] = time.perf_counter() - t0
        bet = None
        if not args.no_betweenness:
            bet, timing["betweenness"] = cl.betweenness(edges, ids)
            if bet is None:
                print("(networkx absent : betweenness ignorée ; pip install networkx pour l'ajouter)")
        out["timing_s"] = timing

        vec = lambda d: np.array([d[b] for b in ids])  # noqa: E731
        P, R, C, D = vec(pr_proj), vec(pr_ref), vec(clo), dv.astype(float)
        sp = cl.spearman
        out["pagerank_project_check"] = {
            "min": float(P.min()), "max": float(P.max()), "max_over_min": float(P.max() / P.min()) if P.min() > 0 else None,
            "std_over_mean": float(P.std() / P.mean()),
            "spearman_vs_reference": sp(P, R), "spearman_vs_degree": sp(P, D)}
        out["pagerank_reference_check"] = {
            "min": float(R.min()), "max": float(R.max()), "max_over_min": float(R.max() / R.min()),
            "std_over_mean": float(R.std() / R.mean()), "iterations": iters, "sum": float(R.sum())}
        corr = {"pagerank_ref~degree": sp(R, D), "pagerank_ref~closeness": sp(R, C),
                "closeness~degree": sp(C, D)}
        if bet:
            Bv = vec(bet)
            corr.update({"pagerank_ref~betweenness": sp(R, Bv), "betweenness~degree": sp(Bv, D),
                         "closeness~betweenness": sp(C, Bv)})
        out["spearman"] = corr
        print("PageRank du projet : max/min =", out["pagerank_project_check"]["max_over_min"],
              "| Spearman vs référence =", out["pagerank_project_check"]["spearman_vs_reference"])
        print("PageRank référence : max/min = %.2f, itérations = %d" % (out["pagerank_reference_check"]["max_over_min"], iters))
        print("Corrélations de Spearman :", {k: round(v, 3) for k, v in corr.items()})
        print("Temps (s) :", {k: round(v, 3) for k, v in timing.items()})

        # ---- top / flop
        order = sorted(ids, key=lambda b: -pr_ref[b])
        order_proj = sorted(ids, key=lambda b: -pr_proj[b])

        def row(b):
            return {"id": b, "title": meta[b]["title"], "author": meta[b]["author"], "degree": deg[b],
                    "pagerank_ref": pr_ref[b], "pagerank_project": pr_proj[b], "closeness": clo[b],
                    "betweenness": bet[b] if bet else None}
        out["top10_reference"] = [row(b) for b in order[:10]]
        out["bottom10_reference"] = [row(b) for b in order[-10:]]
        out["top10_project"] = [row(b) for b in order_proj[:10]]
        out["overlap_top10_project_vs_reference"] = len(set(order[:10]) & set(order_proj[:10]))

        # ---- fiches livre : mots-clés TF-IDF, voisins, calcul de Jaccard
        doc_freq = dict(conn.execute("SELECT term, count(*) FROM inverted_index GROUP BY term"))
        picks = args.books or [order[0], order[n // 2], order[-1]]
        nb = {}
        for a, b, w in edges:
            nb.setdefault(a, []).append((b, w))
            nb.setdefault(b, []).append((a, w))
        fiches = []
        for b in picks:
            counts, kws = keywords_of(conn, b, doc_freq, n)
            top_kw = [t for t, _ in sorted(((t, counts[t] * np.log(n / (1 + doc_freq.get(t, 0)))) for t in kws),
                                           key=lambda x: -x[1])[:10]]
            neigh = sorted(nb.get(b, []), key=lambda x: -x[1])[:5]
            fiche = {"id": b, "title": meta[b]["title"], "author": meta[b]["author"], "words": meta[b]["words"],
                     "degree": deg[b], "pagerank_ref": pr_ref[b], "pagerank_project": pr_proj[b],
                     "rank_ref": order.index(b) + 1, "closeness": clo[b], "top_keywords": top_kw, "neighbors": []}
            for o, w in neigh:
                _, kws_o = keywords_of(conn, o, doc_freq, n)
                inter, union = kws & kws_o, kws | kws_o
                fiche["neighbors"].append({"id": o, "title": meta[o]["title"], "author": meta[o]["author"],
                                           "similarity": w, "distance": 1 - w, "intersection": len(inter),
                                           "union": len(union), "check": jaccard_similarity(kws, kws_o),
                                           "shared_examples": sorted(inter, key=lambda t: -counts.get(t, 0))[:8]})
            fiches.append(fiche)
        out["book_sheets"] = fiches
        out["per_book"] = {"id": ids, "degree": [int(x) for x in dv], "pagerank_ref": [float(x) for x in R],
                           "pagerank_project": [float(x) for x in P], "closeness": [float(x) for x in C]}
        save_json("centrality.json", out)

    # ---- tableaux LaTeX
    def table(rows, caption, label):
        lines = [r"\begin{table}[H]", r"\centering\small",
                 r"\begin{tabular}{r p{5.6cm} p{3.4cm} r r}", r"\hline",
                 r"\# & Titre & Auteur & Degré & PageRank ($\times 10^{-3}$) \\ \hline"]
        for i, r in enumerate(rows, 1):
            lines.append(f"{i} & {tex(short(r['title'], 52))} & {tex(short(r['author'], 28))} & {r['degree']} & "
                         f"{r['pagerank_ref'] * 1000:.3f} \\\\")
        lines += [r"\hline", r"\end{tabular}", f"\\caption{{{caption}}}", f"\\label{{{label}}}", r"\end{table}", ""]
        return "\n".join(lines)

    tex_out = [table(out["top10_reference"], "Les 10 livres les plus centraux selon PageRank (valeurs de référence).", "tab:pr-top"),
               table(out["bottom10_reference"], "Les 10 livres les moins centraux selon PageRank.", "tab:pr-bottom")]
    for f in fiches:
        t = [r"\begin{table}[H]", r"\centering\small", r"\begin{tabular}{p{5.2cm} r r r p{4cm}}", r"\hline",
             r"Voisin & $|A\cap B|$ & $|A\cup B|$ & $J(A,B)$ & Mots communs (exemples) \\ \hline"]
        for v in f["neighbors"]:
            t.append(f"{tex(short(v['title'], 44))} & {v['intersection']} & {v['union']} & {v['similarity']:.3f} & "
                     f"{tex(', '.join(v['shared_examples'][:4]))} \\\\")
        t += [r"\hline", r"\end{tabular}",
              f"\\caption{{Voisins de \\emph{{{tex(short(f['title'], 50))}}} dans le graphe de Jaccard "
              f"(rang PageRank {f['rank_ref']}/{n}, degré {f['degree']}). Mots-clés TF-IDF : "
              f"{tex(', '.join(f['top_keywords'][:8]))}.}}",
              f"\\label{{tab:fiche-{f['id']}}}", r"\end{table}", ""]
        tex_out.append("\n".join(t))
    (RESULTS / "centrality_tables.tex").write_text("\n".join(tex_out), encoding="utf-8")
    print("-> results/centrality.json, results/centrality_tables.tex")


if __name__ == "__main__":
    main()
