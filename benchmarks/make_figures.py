#!/usr/bin/env python3
"""
Génère, à partir de results/*.json|csv :
  results/figures/*.pdf (+ .png)   les courbes, diagrammes bâton (moyenne ± écart type) et histogrammes
  results/tab_build.tex, tab_response.tex, tab_queries.tex   tableaux LaTeX prêts à \\input
  results/numbers.tex              macros LaTeX (\\KwMeanMax, \\RatioTxtIdx, …) utilisées par la rédaction

    python benchmarks/make_figures.py
"""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import NullFormatter

from common import RESULTS, load_json, summarize

FIG = RESULTS / "figures"
FIG.mkdir(exist_ok=True)
plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": 0.3, "figure.dpi": 130,
                     "axes.spines.top": False, "axes.spines.right": False})
SHORT = {"keyword": "Mots-clés", "index": "Regex index (projet)", "text": "Regex texte complet",
         "index_vocab": "Regex vocabulaire (piste)"}
COL = {"keyword": "#1f77b4", "index": "#d62728", "text": "#2ca02c", "index_vocab": "#9467bd"}
LAB = {"keyword": "Mots-clés", "index": "Regex sur l'index (projet)", "text": "Regex sur le texte complet",
       "index_vocab": "Regex sur le vocabulaire distinct (piste)"}
MACROS = {}
# macros utilisées par report/section_tests.tex ; celles dont le benchmark n'a pas (encore) tourné
# sont définies à « [?] » pour que le rapport compile quand même.
EXPECTED = ['AlphaGraphWall', 'AlphaIdx', 'AlphaKw', 'AlphaNeighbors', 'AlphaPrProj', 'AlphaTxt', 'AuthN', 'AuthP', 'AuthR', 'AvgDegreeMax', 'CompCount', 'DistinctTermsMax', 'EdgesMax', 'GiantComp', 'GraphKwMax', 'GraphNbMax', 'GraphWallMax', 'GraphWriteMax', 'IdxMBMax', 'IdxMeanMax', 'IdxRowsMax', 'IdxStdMax', 'IsolatedMax', 'KwClientOverheadMs', 'KwMeanMax', 'KwMeanMin', 'KwStdMax', 'LoadBFactor', 'LoadBHeavyDone', 'LoadBMean', 'LoadCFactor', 'LoadClientsMax', 'LoadMax', 'LoadMaxMin', 'LoadMeanMax', 'LoadPctMax', 'LoadRpsMax', 'LoadRpsOne', 'MachineDesc', 'MaxDegree', 'NBooksMax', 'PrProjMax', 'PrProjRatio', 'PrRefMax', 'PrRefRatio', 'PrSpearman', 'PrSpeedup', 'RatioIdxKw', 'RatioTxtIdx', 'SpBetw', 'SpClose', 'SpDegree', 'SpeedupVoc', 'SugLift', 'SugRand', 'SugSame', 'TBetw', 'TClose', 'TPrRef', 'TextMBMax', 'TieShare', 'TitleFive', 'TitleMRR', 'TitleN', 'TitleOne', 'TitleTen', 'TokensMax', 'TxtSecMax', 'UserMean', 'UserNdcg', 'UserPfive', 'UserStd', 'UserSugMean', 'UserTesters', 'VocMeanMax']


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / f"{name}.pdf")
    fig.savefig(FIG / f"{name}.png", dpi=160)
    plt.close(fig)
    print("  figure", name)


def fr(x, d=1):
    """Nombre au format français (virgule), espace fine pour les milliers."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "--"
    s = f"{x:,.{d}f}".replace(",", "\\,").replace(".", ",")
    return s


def macro(name, value):
    MACROS[name] = value


def load_rows():
    p = RESULTS / "query_timings.csv"
    if not p.exists():
        return []
    rows = []
    with open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["warmup"] == "1" or r["server_ms"] in ("", "None"):
                continue
            r["size"] = int(r["size"])
            r["server_ms"] = float(r["server_ms"])
            r["client_ms"] = float(r["client_ms"])
            rows.append(r)
    return rows


# ---------------------------------------------------------------------------
def fig_response(rows, build):
    sizes = sorted({r["size"] for r in rows})
    modes = [m for m in ("keyword", "index", "text", "index_vocab") if any(r["mode"] == m for r in rows)]
    if not sizes or not modes:
        return
    stats = {m: {n: summarize([r["server_ms"] for r in rows if r["mode"] == m and r["size"] == n]) for n in sizes}
             for m in modes}

    # (1) courbes : temps moyen ± écart type, échelle log
    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    for m in modes:
        ns = [n for n in sizes if stats[m][n]]
        mean = np.array([stats[m][n]["mean"] for n in ns])
        std = np.array([stats[m][n]["std"] for n in ns])
        ax.errorbar(ns, mean, yerr=std, marker="o", capsize=3, color=COL[m], label=LAB[m],
                    ls="--" if m == "index_vocab" else "-")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks(sizes)
    ax.set_xticklabels([str(n) for n in sizes])
    ax.set_xlabel("Taille de la bibliothèque N (livres)")
    ax.set_ylabel("Temps de réponse côté serveur (ms, échelle log)")
    ax.set_title("Temps de réponse selon la taille de la bibliothèque")
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2, frameon=False)
    save(fig, "fig_response_vs_size")

    # (2) barres moyenne ± écart type, une barre par mode et par taille
    fig, ax = plt.subplots(figsize=(7, 4.2))
    w = 0.8 / len(modes)
    x = np.arange(len(sizes))
    for k, m in enumerate(modes):
        mean = [stats[m][n].get("mean", np.nan) for n in sizes]
        std = [stats[m][n].get("std", 0) for n in sizes]
        ax.bar(x + k * w - 0.4 + w / 2, mean, w, yerr=std, capsize=2, color=COL[m], label=LAB[m])
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels([f"N = {n}" for n in sizes])
    ax.set_ylabel("Temps moyen ± écart type (ms, log)")
    ax.legend(fontsize=8)
    save(fig, "fig_response_bars")

    # exposants empiriques (pente log-log) + macros
    ns_all = np.array(sizes, dtype=float)
    for m, nm in (("keyword", "Kw"), ("index", "Idx"), ("text", "Txt"), ("index_vocab", "Voc")):
        if m in stats and len([n for n in sizes if stats[m][n]]) >= 3:
            means = np.array([stats[m][n]["mean"] for n in sizes])
            slope = np.polyfit(np.log(ns_all), np.log(means), 1)[0]
            macro(f"Alpha{nm}", fr(slope, 2))
    nmax = sizes[-1]
    macro("NBooksMax", fr(nmax, 0))
    for m, nm in (("keyword", "Kw"), ("index", "Idx"), ("text", "Txt"), ("index_vocab", "Voc")):
        if m in stats and stats[m][nmax]:
            macro(f"{nm}MeanMax", fr(stats[m][nmax]["mean"], 1))
            macro(f"{nm}StdMax", fr(stats[m][nmax]["std"], 1))
            macro(f"{nm}SecMax", fr(stats[m][nmax]["mean"] / 1000, 1))
            macro(f"{nm}MeanMin", fr(stats[m][sizes[0]]["mean"], 1))
    if "index" in stats and "text" in stats and stats["index"][nmax] and stats["text"][nmax]:
        macro("RatioTxtIdx", fr(stats["text"][nmax]["mean"] / stats["index"][nmax]["mean"], 1))
    if "keyword" in stats and "index" in stats and stats["keyword"][nmax] and stats["index"][nmax]:
        macro("RatioIdxKw", fr(stats["index"][nmax]["mean"] / stats["keyword"][nmax]["mean"], 0))
    if "index" in stats and "index_vocab" in stats and stats["index_vocab"][nmax] and stats["index"][nmax]:
        macro("SpeedupVoc", fr(stats["index"][nmax]["mean"] / stats["index_vocab"][nmax]["mean"], 1))
    # client vs serveur (surcoût réseau + JSON)
    kw = [r for r in rows if r["mode"] == "keyword" and r["size"] == nmax]
    if kw:
        macro("KwClientOverheadMs", fr(np.mean([r["client_ms"] - r["server_ms"] for r in kw]), 1))
    return stats


def fig_by_query(rows):
    sizes = sorted({r["size"] for r in rows})
    if not sizes:
        return
    nmax = sizes[-1]
    # mots-clés : barres par requête et par taille
    qk = [q for q in dict.fromkeys(r["qname"] for r in rows if r["mode"] == "keyword")]
    if qk:
        fig, ax = plt.subplots(figsize=(8, 4))
        w = 0.8 / len(sizes)
        for k, n in enumerate(sizes):
            m = [summarize([r["server_ms"] for r in rows if r["mode"] == "keyword" and r["size"] == n and r["qname"] == q]) for q in qk]
            ax.bar(np.arange(len(qk)) + k * w - 0.4 + w / 2, [s.get("mean", 0) for s in m], w,
                   yerr=[s.get("std", 0) for s in m], capsize=2, label=f"N = {n}")
        ax.set_xticks(range(len(qk)))
        ax.set_xticklabels([q.replace("kw_", "") for q in qk], rotation=20)
        ax.set_ylabel("Temps moyen ± écart type (ms)")
        ax.set_title("Recherche par mots-clés, par type de requête")
        ax.legend(fontsize=8)
        save(fig, "fig_keyword_by_query")
    # regex : par requête, à N max
    qr = [q for q in dict.fromkeys(r["qname"] for r in rows if r["mode"] in ("index", "text"))]
    modes = [m for m in ("index", "text", "index_vocab") if any(r["mode"] == m and r["size"] == nmax for r in rows)]
    if qr and modes:
        fig, ax = plt.subplots(figsize=(8, 4))
        w = 0.8 / len(modes)
        for k, mo in enumerate(modes):
            m = [summarize([r["server_ms"] for r in rows if r["mode"] == mo and r["size"] == nmax and r["qname"] == q]) for q in qr]
            ax.bar(np.arange(len(qr)) + k * w - 0.4 + w / 2, [s.get("mean", np.nan) for s in m], w,
                   yerr=[s.get("std", 0) for s in m], capsize=2, color=COL[mo], label=LAB[mo])
        ax.set_yscale("log")
        ax.set_xticks(range(len(qr)))
        ax.set_xticklabels([q.replace("rx_", "") for q in qr], rotation=20)
        ax.set_ylabel("Temps moyen ± écart type (ms, log)")
        ax.set_title(f"Recherche par expression régulière, N = {nmax}")
        ax.legend(fontsize=8)
        save(fig, "fig_regex_by_query")


def fig_hist(rows):
    sizes = sorted({r["size"] for r in rows})
    if not sizes:
        return
    nmax = sizes[-1]
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.4))
    for ax, m in zip(axes, ("keyword", "index", "text")):
        v = [r["server_ms"] for r in rows if r["mode"] == m and r["size"] == nmax]
        if v:
            ax.hist(v, bins=min(25, max(5, len(v) // 3)), color=COL[m], alpha=0.85)
            ax.axvline(np.mean(v), color="k", ls="--", lw=1)
        ax.set_title(f"{LAB[m]}", fontsize=9)
        ax.set_xlabel("ms")
    axes[0].set_ylabel("Fréquence")
    fig.suptitle(f"Distribution des temps de réponse (N = {nmax}, toutes requêtes et répétitions ; trait = moyenne)", fontsize=9)
    save(fig, "fig_latency_hist")


def fig_build(build):
    if not build:
        return
    ns = [b["size"] for b in build]
    # indexation
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.6))
    ax[0].plot(ns, [b["load_s_cumulative"] for b in build], "o-", color="#1f77b4")
    ax[0].set_xlabel("N (livres)")
    ax[0].set_ylabel("Temps cumulé (s)")
    ax[0].set_title("Nettoyage + tokenisation + index inversé")
    ax[1].bar([str(n) for n in ns], [b["index_bytes"] / 2**20 for b in build], color="#7f7f7f")
    ax[1].set_ylabel("Taille de inverted_index (Mo)")
    ax[1].set_xlabel("N (livres)")
    ax[1].set_title("Espace disque de l'index")
    save(fig, "fig_indexing")
    # graphe : barres empilées
    kw = np.array([b.get("graph_keywords_s") or 0 for b in build])
    nb = np.array([b.get("graph_neighbors_s") or 0 for b in build])
    wr = np.array([b.get("graph_write_and_other_s") or 0 for b in build])
    fig, ax = plt.subplots(figsize=(6.4, 4))
    x = np.arange(len(ns))
    ax.bar(x, kw, label="Sélection des mots-clés TF-IDF", color="#1f77b4")
    ax.bar(x, nb, bottom=kw, label="Voisins (Jaccard, $O(N^2)$)", color="#ff7f0e")
    ax.bar(x, wr, bottom=kw + nb, label="Écriture en base + autres", color="#2ca02c")
    ax.set_xticks(x)
    ax.set_xticklabels([f"N = {n}" for n in ns])
    ax.set_ylabel("Temps (s)")
    ax.set_title("Construction du graphe de Jaccard (script du projet)")
    ax.legend(fontsize=8)
    save(fig, "fig_graph_build")
    # pagerank
    fig, ax = plt.subplots(figsize=(6.4, 4))
    ax.plot(ns, [b["pagerank_project_s"] for b in build], "o-", color="#d62728", label="PageRank du projet (matrice dense)")
    ax.plot(ns, [b["pagerank_reference_s"] for b in build], "s--", color="#9467bd", label="Référence (matrice creuse)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks(ns)
    ax.set_xticklabels([str(n) for n in ns])
    ax.set_xlabel("N (livres)")
    ax.set_ylabel("Temps (s, log)")
    ax.set_title("Temps de calcul du PageRank")
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.legend(fontsize=8)
    save(fig, "fig_pagerank_time")
    last = build[-1]
    macro("LoadMax", fr(last["load_s_cumulative"], 0))
    macro("LoadMaxMin", fr(last["load_s_cumulative"] / 60, 1))
    macro("GraphWallMax", fr(last["graph_wall_s"], 0))
    macro("GraphKwMax", fr(last.get("graph_keywords_s"), 0))
    macro("GraphNbMax", fr(last.get("graph_neighbors_s"), 0))
    macro("GraphWriteMax", fr(last.get("graph_write_and_other_s"), 0))
    macro("PrProjMax", fr(last["pagerank_project_s"], 1))
    macro("PrRefMax", fr(last["pagerank_reference_s"], 3))
    if last["pagerank_reference_s"]:
        macro("PrSpeedup", fr(last["pagerank_project_s"] / last["pagerank_reference_s"], 0))
    macro("IdxRowsMax", fr(last["index_rows"] / 1e6, 1))
    macro("IdxMBMax", fr(last["index_bytes"] / 2**20, 0))
    macro("TextMBMax", fr(last["text_bytes"] / 2**20, 0))
    macro("TokensMax", fr(last["tokens"] / 1e6, 1))
    macro("DistinctTermsMax", fr(last["distinct_terms"], 0))
    macro("EdgesMax", fr(last.get("edges"), 0))
    macro("AvgDegreeMax", fr(last.get("avg_degree"), 1))
    macro("IsolatedMax", fr(last.get("isolated_books"), 0))
    sp = last.get("pagerank_spearman_project_vs_reference")
    macro("PrSpearman", fr(sp, 2) if sp is not None else "--")
    macro("PrProjRatio", fr(last.get("pagerank_project_max_over_min"), 3))
    macro("PrRefRatio", fr(last.get("pagerank_reference_max_over_min"), 1))
    if len(build) >= 3:
        slope = np.polyfit(np.log(ns), np.log([b["pagerank_project_s"] for b in build]), 1)[0]
        macro("AlphaPrProj", fr(slope, 2))
        slope = np.polyfit(np.log(ns), np.log([b["graph_neighbors_s"] for b in build]), 1)[0]
        macro("AlphaNeighbors", fr(slope, 2))
        slope = np.polyfit(np.log(ns), np.log([b["graph_wall_s"] for b in build]), 1)[0]
        macro("AlphaGraphWall", fr(slope, 2))


def fig_load(stats_unused=None):
    for p in sorted(RESULTS.glob("load_test_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        lab = d.get("label", p.stem)
        A = d["scenario_A"]
        c = [a["clients"] for a in A]
        fig, ax = plt.subplots(1, 2, figsize=(9.5, 3.8))
        ax[0].plot(c, [a["throughput_rps"] for a in A], "o-", color="#1f77b4")
        ax[0].set_xlabel("Clients simultanés")
        ax[0].set_ylabel("Débit (requêtes/s)")
        ax[0].set_title("Débit, recherche par mots-clés")
        ax[1].errorbar(c, [a["latency_ms"]["mean"] for a in A], yerr=[a["latency_ms"]["std"] for a in A],
                       marker="o", capsize=3, color="#d62728", label="moyenne ± écart type")
        ax[1].plot(c, [a["latency_ms"]["p95"] for a in A], "s--", color="#7f7f7f", label="95e centile")
        ax[1].set_xlabel("Clients simultanés")
        ax[1].set_ylabel("Latence (ms)")
        ax[1].set_title("Latence côté client")
        ax[1].legend(fontsize=8)
        save(fig, f"fig_load_A_{lab}")
        base5 = next((a for a in A if a["clients"] == 5), None)
        if base5 and d.get("scenario_B_text") and d.get("scenario_C_index"):
            B, C = d["scenario_B_text"], d["scenario_C_index"]
            fig, ax = plt.subplots(figsize=(6, 3.8))
            names = ["5 clients seuls", "+ regex sur l'index", "+ regex sur le texte"]
            vals = [base5["latency_ms"], C["latency_ms"], B["latency_ms"]]
            ax.bar(names, [v["mean"] for v in vals], yerr=[v["std"] for v in vals], capsize=4,
                   color=["#1f77b4", "#d62728", "#2ca02c"])
            ax.set_yscale("log")
            ax.set_ylabel("Latence moyenne des recherches mots-clés (ms, log)")
            ax.set_title("Effet d'une requête lourde concurrente")
            save(fig, f"fig_load_BC_{lab}")
        if lab == "local":
            m5 = base5["latency_ms"]["mean"] if base5 else None
            macro("LoadRpsOne", fr(A[0]["throughput_rps"], 0))
            macro("LoadRpsMax", fr(max(a["throughput_rps"] for a in A), 0))
            macro("LoadClientsMax", fr(A[-1]["clients"], 0))
            macro("LoadPctMax", fr(A[-1]["latency_ms"]["p95"], 0))
            macro("LoadMeanMax", fr(A[-1]["latency_ms"]["mean"], 0))
            if d.get("scenario_B_text") and m5:
                macro("LoadBMean", fr(d["scenario_B_text"]["latency_ms"]["mean"], 0))
                macro("LoadBFactor", fr(d["scenario_B_text"]["latency_ms"]["mean"] / m5, 1))
                macro("LoadBHeavyDone", fr(d["scenario_B_text"]["heavy_completed"], 0))
            if d.get("scenario_C_index") and m5:
                macro("LoadCMean", fr(d["scenario_C_index"]["latency_ms"]["mean"], 0))
                macro("LoadCFactor", fr(d["scenario_C_index"]["latency_ms"]["mean"] / m5, 1))


def fig_centrality():
    d = load_json("centrality.json")
    if not d or "per_book" not in d:
        return
    pb = d["per_book"]
    deg, ref, proj, clo = (np.array(pb[k]) for k in ("degree", "pagerank_ref", "pagerank_project", "closeness"))
    fig, ax = plt.subplots(1, 3, figsize=(11, 3.5))
    ax[0].scatter(deg + np.random.default_rng(0).uniform(-0.2, 0.2, len(deg)), ref * 1e3, s=6, alpha=0.5, color="#1f77b4")
    ax[0].set_xlabel("Degré dans le graphe de Jaccard")
    ax[0].set_ylabel("PageRank de référence ($\\times 10^{-3}$)")
    ax[0].set_title(f"PageRank vs degré (Spearman = {d['spearman']['pagerank_ref~degree']:.2f})", fontsize=9)
    ax[1].scatter(clo, ref * 1e3, s=6, alpha=0.5, color="#2ca02c")
    ax[1].set_xlabel("Closeness (Wasserman-Faust)")
    ax[1].set_ylabel("PageRank de référence ($\\times 10^{-3}$)")
    ax[1].set_title(f"PageRank vs closeness (Spearman = {d['spearman']['pagerank_ref~closeness']:.2f})", fontsize=9)
    lo, hi = min(ref.min(), proj.min()) * 1e3, max(ref.max(), proj.max()) * 1e3
    bins = np.linspace(lo, hi if hi > lo else lo + 1e-6, 31)   # mêmes classes ; robuste si le PageRank est quasi constant
    ax[2].hist(ref * 1e3, bins=bins, alpha=0.7, label="référence", color="#1f77b4")
    ax[2].hist(proj * 1e3, bins=bins, alpha=0.7, label="projet", color="#d62728")
    ax[2].set_xlabel("PageRank ($\\times 10^{-3}$)")
    ax[2].set_ylabel("Nombre de livres")
    ax[2].set_title("Distribution des scores", fontsize=9)
    ax[2].legend(fontsize=8)
    save(fig, "fig_centrality")
    g = d["graph"]
    macro("CompCount", fr(g["components"], 0))
    macro("GiantComp", fr(g["giant_component"], 0))
    macro("MaxDegree", fr(g["max_degree"], 0))
    macro("SpDegree", fr(d["spearman"]["pagerank_ref~degree"], 2))
    macro("SpClose", fr(d["spearman"]["pagerank_ref~closeness"], 2))
    if "pagerank_ref~betweenness" in d["spearman"]:
        macro("SpBetw", fr(d["spearman"]["pagerank_ref~betweenness"], 2))
    for k, nm in (("pagerank_reference", "TPrRef"), ("closeness", "TClose"), ("betweenness", "TBetw")):
        if k in d["timing_s"]:
            macro(nm, fr(d["timing_s"][k], 2))


def fig_relevance():
    a = load_json("relevance_auto.json")
    if a:
        macro("AuthP", fr(a["author_queries"]["precision_at_10"].get("mean", float("nan")), 2))
        macro("AuthR", fr(a["author_queries"]["recall_at_10"].get("mean", float("nan")), 2))
        t = a["title_queries"]
        macro("TitleOne", fr(t["success_at_1"] * 100, 0))
        macro("TitleFive", fr(t["success_at_5"] * 100, 0))
        macro("TitleTen", fr(t["success_at_10"] * 100, 0))
        macro("TitleMRR", fr(t["mrr"], 2))
        macro("TitleN", fr(t["n"], 0))
        macro("AuthN", fr(a["author_queries"]["n"], 0))
        s = a["suggestions_same_author"]
        if s["rate_mean"] is not None:
            macro("SugSame", fr(s["rate_mean"] * 100, 0))
            macro("SugRand", fr((s["random_baseline_mean"] or 0) * 100, 1))
            macro("SugLift", fr(s["lift"], 0) if s["lift"] else "--")
        macro("TieShare", fr(a["score_ties_top20"]["tie_share"].get("mean", float("nan")) * 100, 0))
    u = load_json("relevance_user_test.json")
    if u:
        macro("UserMean", fr(u["results_grade"].get("mean"), 2))
        macro("UserStd", fr(u["results_grade"].get("std"), 2))
        macro("UserSugMean", fr(u["suggestions_grade"].get("mean"), 2))
        macro("UserPfive", fr((u["p_at_5_mean"] or 0) * 100, 0))
        macro("UserNdcg", fr(u["ndcg_at_5_mean"], 2))
        macro("UserTesters", fr(len(u["testers"]), 0))
        dist = u["grade_distribution_results"]
        fig, ax = plt.subplots(1, 2, figsize=(9, 3.6))
        ks = [1, 2, 3, 4, 5]
        ax[0].bar(ks, [dist.get(str(k), dist.get(k, 0)) for k in ks], color="#1f77b4")
        ax[0].set_xlabel("Note (1 = hors sujet, 5 = parfait)")
        ax[0].set_ylabel("Nombre de jugements")
        ax[0].set_title("Notes attribuées aux résultats")
        pq = u["per_query"]
        ax[1].barh([q["query"] for q in pq][::-1], [q["mean_grade"] for q in pq][::-1], color="#2ca02c")
        ax[1].set_xlim(1, 5)
        ax[1].set_xlabel("Note moyenne (top 5)")
        ax[1].set_title("Pertinence par requête")
        save(fig, "fig_relevance_user")


# ---------------------------------------------------------------------------
def tables(rows, stats, build, machine):
    parts = {}
    out = []
    if machine:
        macro("MachineDesc", (
            f"{machine.get('cpu', machine.get('machine', ''))}, {machine.get('cpu_count', '?')} c\\oe urs logiques, "
            f"{machine.get('ram_gb', '?')}~Go de RAM, {machine.get('platform', '')}".replace("_", "\\_").replace("#", "\\#")))
    if build:
        t = [r"\begin{table}[H]", r"\centering", r"\resizebox{\textwidth}{!}{%", r"\begin{tabular}{r r r r r r r r}", r"\hline",
             r"$N$ & Mots (M) & Lignes d'index (M) & Index (Mo) & Chargement (s) & Graphe (s) & PageRank projet (s) & PageRank réf. (s) \\ \hline"]
        for b in build:
            t.append(f"{b['size']} & {fr(b['tokens'] / 1e6, 1)} & {fr(b['index_rows'] / 1e6, 2)} & {fr(b['index_bytes'] / 2**20, 0)} & "
                     f"{fr(b['load_s_cumulative'], 0)} & {fr(b['graph_wall_s'], 0)} & {fr(b['pagerank_project_s'], 1)} & {fr(b['pagerank_reference_s'], 3)} \\\\")
        t += [r"\hline", r"\end{tabular}}",
              r"\caption{Coûts de préparation des données selon la taille de la bibliothèque (mesures uniques ; chargement cumulé).}",
              r"\label{tab:build}", r"\end{table}", ""]
        parts["tab_build.tex"] = t
    if stats:
        sizes = sorted(next(iter(stats.values())).keys())
        t = [r"\begin{table}[H]", r"\centering", r"\resizebox{\textwidth}{!}{%", r"\begin{tabular}{l " + "r " * len(sizes) + "}", r"\hline",
             "Mode & " + " & ".join(f"$N={n}$" for n in sizes) + r" \\ \hline"]
        for m in ("keyword", "index", "text", "index_vocab"):
            if m in stats:
                cells = [f"{fr(stats[m][n]['mean'], 1)} $\\pm$ {fr(stats[m][n]['std'], 1)}" if stats[m][n] else "--" for n in sizes]
                t.append(f"{SHORT[m]} & " + " & ".join(cells) + r" \\")
        t += [r"\hline", r"\end{tabular}}",
              r"\caption{Temps de réponse côté serveur (ms), moyenne $\pm$ écart type sur l'ensemble des requêtes et répétitions.}",
              r"\label{tab:response}", r"\end{table}", ""]
        parts["tab_response.tex"] = t
    sel = load_json("queries_selected.json")
    if sel:
        t = [r"\begin{table}[H]", r"\centering\small", r"\begin{tabular}{l l l}", r"\hline",
             r"Famille & Nom & Requête \\ \hline"]
        for fam, key in (("Mots-clés", "keyword"), ("Regex", "regex")):
            for k, v in sel[key].items():
                v = v.replace("\\", r"\textbackslash{}").replace("_", r"\_").replace("{", r"\{").replace("}", r"\}")
                t.append(f"{fam} & \\texttt{{{k.replace('_', chr(92) + '_')}}} & \\texttt{{{v}}} \\\\")
        t += [r"\hline", r"\end{tabular}", r"\caption{Requêtes utilisées pour les mesures.}", r"\label{tab:queries}", r"\end{table}", ""]
        parts["tab_queries.tex"] = t
    for name, lines in parts.items():
        (RESULTS / name).write_text("\n".join(lines), encoding="utf-8")


def main():
    rows = load_rows()
    build = load_json("build_times.json", [])
    machine = load_json("machine.json")
    stats = None
    if rows:
        stats = fig_response(rows, build)
        fig_by_query(rows)
        fig_hist(rows)
    fig_build(build)
    fig_load()
    fig_centrality()
    fig_relevance()
    tables(rows, stats, build, machine)
    missing = [k for k in EXPECTED if k not in MACROS]
    if missing:
        print("ATTENTION : macros sans valeur (benchmark pas encore exécuté ?) :", ", ".join(missing))
    lines = ["% Généré par make_figures.py — ne pas éditer à la main"]
    lines += [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(MACROS.items())]
    lines += [f"\\newcommand{{\\{k}}}{{\\textbf{{[?]}}}}" for k in missing]
    (RESULTS / "numbers.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(MACROS)} macros -> results/numbers.tex ; tableaux -> results/tab_*.tex ; figures -> results/figures/")


if __name__ == "__main__":
    main()
