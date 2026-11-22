#!/usr/bin/env python3
"""
Tests de pertinence.

La pertinence est un critère subjectif (cf. énoncé) : on la traite à deux niveaux.

  (A) Métriques automatiques « proxy », calculées à partir des métadonnées des livres
      (auteur, titre) qui servent de vérité terrain :
        - requêtes par nom d'auteur  : précision@10 et rappel@10
        - requêtes par mots du titre : rang du livre visé (MRR, succès@1/@5/@10)
        - cohérence des suggestions  : part de suggestions du même auteur que le meilleur résultat,
                                       comparée au hasard (lift)
        - utilité du PageRank        : part des paires consécutives du top-20 à score égal
                                       (seules ces paires sont départagées par PageRank)
  (B) Test utilisateur : génération d'un formulaire CSV à faire noter (1-5) par des testeurs,
      puis agrégation (moyenne ± écart type, P@5, nDCG@5, accord entre testeurs).

    python benchmarks/bench_relevance.py auto
    python benchmarks/bench_relevance.py make-form
    python benchmarks/bench_relevance.py aggregate results/form_alice.csv results/form_bob.csv ...
"""
import argparse
import csv
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import psycopg
import requests

from common import (BACKEND, DEFAULT_ADMIN_URL, REPO, RESULTS, SEED, ApiServer, db_url, load_json,
                    save_json, summarize)

sys.path.insert(0, str(BACKEND))
from scripts import tokenizer  # noqa: E402  (tokenizer du projet : mêmes mots vides que l'application)

THEMATIC = ["love", "sea", "war", "king", "ship", "ghost", "garden", "murder", "island",
            "treasure", "mother", "poison"]

# requêtes du formulaire utilisateur (adapter si un terme est absent de votre bibliothèque)
FORM_KEYWORD = ["whale", "ghost", "pirate treasure", "detective", "love letter", "railway",
                "dickens", "shakespeare", "alice wonderland", "war peace"]
FORM_REGEX = [("index", r"(king|queen)dom"), ("index", r"s(a|g|r)+on")]


def get(sess, base, path, **params):
    r = sess.get(base + path, params=params, timeout=600)
    r.raise_for_status()
    return r.json()


def surname_of(author):
    for w in re.findall(r"[A-Za-z]{3,}", author or ""):
        w = w.lower()
        if tokenizer.tokenize(w):          # exclut les mots vides
            return w
    return None


def author_has(author, word):
    return bool(re.search(rf"\b{re.escape(word)}\b", (author or "").lower()))


# ----------------------------------------------------------------------------
def auto(conn, sess, base, n_authors, n_titles):
    rng = random.Random(SEED)
    books = conn.execute("SELECT gutenberg_id, title, author FROM books ORDER BY gutenberg_id").fetchall()
    N = len(books)
    out = {"n_books": N}

    # ---- A1 : auteurs
    by_author = defaultdict(list)
    for gid, t, a in books:
        if a:
            by_author[a].append(gid)
    multi = sorted(a for a, ids in by_author.items() if len(ids) >= 2 and surname_of(a))
    rng.shuffle(multi)
    precs, recs, sug_same, sug_base, per_author = [], [], [], [], []
    for a in multi[:n_authors]:
        w = surname_of(a)
        res = get(sess, base, "/api/search", q=w, limit=10)
        top = res["results"]
        total_author_books = sum(1 for _, _, x in books if author_has(x, w))
        hits = sum(1 for r in top if author_has(r["author"], w))
        p = hits / len(top) if top else 0.0
        r_ = hits / min(10, total_author_books) if total_author_books else 0.0
        precs.append(p)
        recs.append(r_)
        # suggestions : même auteur que le meilleur résultat ?
        if top:
            ref = top[0]["author"]
            sg = res.get("suggestions", [])
            if sg:
                same = sum(1 for s in sg if s["author"] == ref) / len(sg)
                n_same_total = len(by_author.get(ref, []))
                base_rate = max(0, n_same_total - 3) / max(1, N - 3)   # ≈ hasard (3 meilleurs exclus)
                sug_same.append(same)
                sug_base.append(base_rate)
        per_author.append({"author": a, "query": w, "p_at_10": p, "r_at_10": r_,
                           "books_of_author": total_author_books})
    out["author_queries"] = {
        "n": len(precs), "precision_at_10": summarize(precs), "recall_at_10": summarize(recs),
        "details": per_author}
    out["suggestions_same_author"] = {
        "n": len(sug_same), "rate_mean": sum(sug_same) / len(sug_same) if sug_same else None,
        "random_baseline_mean": sum(sug_base) / len(sug_base) if sug_base else None,
        "lift": (sum(sug_same) / max(1e-12, sum(sug_base))) if sug_same and sum(sug_base) > 0 else None}

    # ---- A2 : titres
    ranks, details = [], []
    sample = [b for b in books if b[1]]
    rng.shuffle(sample)
    done = 0
    for gid, title, author in sample:
        words = []
        for w in sorted(set(tokenizer.tokenize(re.sub(r"[^A-Za-z' ]", " ", title))), key=len, reverse=True):
            if len(w) >= 4:
                words.append(w)
        if len(words) < 2:
            continue
        q = " ".join(words[:2])
        res = get(sess, base, "/api/search", q=q, limit=50)
        ids = [r["id"] for r in res["results"]]
        rank = ids.index(gid) + 1 if gid in ids else None
        ranks.append(rank)
        details.append({"id": gid, "title": title, "query": q, "rank": rank, "total": res["total"]})
        done += 1
        if done >= n_titles:
            break
    found = [r for r in ranks if r]
    out["title_queries"] = {
        "n": len(ranks),
        "success_at_1": sum(1 for r in ranks if r == 1) / max(1, len(ranks)),
        "success_at_5": sum(1 for r in ranks if r and r <= 5) / max(1, len(ranks)),
        "success_at_10": sum(1 for r in ranks if r and r <= 10) / max(1, len(ranks)),
        "not_in_top50": sum(1 for r in ranks if r is None) / max(1, len(ranks)),
        "mrr": sum(1 / r for r in found) / max(1, len(ranks)),
        "details": details}

    # ---- A4 : égalités de score dans le top-20 (utilité réelle du PageRank)
    sel = load_json("queries_selected.json") or {"keyword": {}}
    qs = THEMATIC + list(sel["keyword"].values())
    ties, per_q = [], []
    for q in qs:
        res = get(sess, base, "/api/search", q=q, limit=20)
        sc = [r["score"] for r in res["results"]]
        if len(sc) >= 2:
            tie = sum(1 for x, y in zip(sc, sc[1:]) if x == y) / (len(sc) - 1)
            ties.append(tie)
            per_q.append({"query": q, "total": res["total"], "tie_share": tie,
                          "distinct_scores": len(set(sc))})
    out["score_ties_top20"] = {"n": len(ties), "tie_share": summarize(ties), "details": per_q}
    return out


# ----------------------------------------------------------------------------
def make_form(sess, base, path, k):
    rows = []
    specs = [("keyword", q) for q in FORM_KEYWORD] + [("regex", r) for _, r in FORM_REGEX]
    for kind, q in specs:
        if kind == "keyword":
            res = get(sess, base, "/api/search", q=q, limit=k)
        else:
            res = get(sess, base, "/api/search/advanced", regex=q, scope="index")
        for i, r in enumerate(res["results"][:k], 1):
            rows.append(["", q, kind, "result", i, r["id"], r["title"], r["author"], ""])
        for i, r in enumerate(res.get("suggestions", [])[:3], 1):
            rows.append(["", q, kind, "suggestion", i, r["id"], r["title"], r["author"], ""])
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["tester", "query", "mode", "kind", "rank", "book_id", "title", "author", "grade_1_to_5"])
        w.writerows(rows)
    print(f"Formulaire écrit : {path}  ({len(rows)} lignes à noter)")
    print("Consigne : pour chaque ligne, noter de 1 (hors sujet) à 5 (exactement ce que je cherchais) ;"
          " renseigner la colonne `tester` (prénom). Un fichier par testeur.")


def dcg(gains):
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def aggregate(files):
    items = defaultdict(dict)       # (query, kind, rank, book_id) -> {tester: grade}
    for fpath in files:
        with open(fpath, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                g = (r.get("grade_1_to_5") or "").strip()
                if not g:
                    continue
                items[(r["query"], r["kind"], int(r["rank"]), r["book_id"])][r["tester"]] = int(g)
    res_grades = [g for k, v in items.items() if k[1] == "result" for g in v.values()]
    sug_grades = [g for k, v in items.items() if k[1] == "suggestion" for g in v.values()]
    per_query = defaultdict(list)
    for (q, kind, rank, bid), v in items.items():
        if kind == "result":
            per_query[q].append((rank, sum(v.values()) / len(v)))
    pq = []
    for q, lst in per_query.items():
        lst.sort()
        grades = [g for _, g in lst][:5]
        ideal = sorted(grades, reverse=True)
        gains = [g - 1 for g in grades]
        ig = [g - 1 for g in ideal]
        pq.append({"query": q, "mean_grade": sum(grades) / len(grades),
                   "p_at_5": sum(1 for g in grades if g >= 4) / len(grades),
                   "ndcg_at_5": dcg(gains) / dcg(ig) if dcg(ig) > 0 else 1.0})
    # accord entre testeurs : corrélation de Spearman moyenne sur les paires de testeurs
    testers = sorted({t for v in items.values() for t in v})
    agree = []
    if len(testers) >= 2:
        from scipy.stats import spearmanr
        for i in range(len(testers)):
            for j in range(i + 1, len(testers)):
                pairs = [(v[testers[i]], v[testers[j]]) for v in items.values()
                         if testers[i] in v and testers[j] in v]
                if len(pairs) >= 5 and len({p[0] for p in pairs}) > 1 and len({p[1] for p in pairs}) > 1:
                    agree.append(float(spearmanr([p[0] for p in pairs], [p[1] for p in pairs])[0]))
    out = {"testers": testers, "n_graded_items": len(items),
           "results_grade": summarize(res_grades), "suggestions_grade": summarize(sug_grades),
           "grade_distribution_results": dict(sorted(Counter(res_grades).items())),
           "per_query": sorted(pq, key=lambda x: -x["mean_grade"]),
           "p_at_5_mean": sum(x["p_at_5"] for x in pq) / len(pq) if pq else None,
           "ndcg_at_5_mean": sum(x["ndcg_at_5"] for x in pq) / len(pq) if pq else None,
           "inter_tester_spearman_mean": sum(agree) / len(agree) if agree else None}
    save_json("relevance_user_test.json", out)
    print(f"{len(testers)} testeur(s), {len(items)} éléments notés")
    print(f"note moyenne des résultats : {out['results_grade'].get('mean', float('nan')):.2f} "
          f"± {out['results_grade'].get('std', float('nan')):.2f}  | suggestions : "
          f"{out['suggestions_grade'].get('mean', float('nan')):.2f}")
    print(f"P@5 moyenne (note >= 4) = {out['p_at_5_mean']}, nDCG@5 moyen = {out['ndcg_at_5_mean']}")
    print("-> results/relevance_user_test.json")


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["auto", "make-form", "aggregate"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--base-url")
    ap.add_argument("--admin-url", default=DEFAULT_ADMIN_URL)
    ap.add_argument("--books-dir", type=Path, default=REPO / "database" / "books")
    ap.add_argument("--authors", type=int, default=20)
    ap.add_argument("--titles", type=int, default=50)
    ap.add_argument("--k", type=int, default=5, help="résultats par requête dans le formulaire")
    ap.add_argument("--out", type=Path, default=RESULTS / "relevance_form_template.csv")
    args = ap.parse_args()

    if args.mode == "aggregate":
        if not args.files:
            sys.exit("Donner au moins un CSV rempli.")
        return aggregate(args.files)

    def run(base):
        with psycopg.connect(db_url(args.admin_url), autocommit=True) as conn, requests.Session() as sess:
            if args.mode == "auto":
                res = auto(conn, sess, base, args.authors, args.titles)
                save_json("relevance_auto.json", res)
                a, t, s, ties = (res["author_queries"], res["title_queries"],
                                 res["suggestions_same_author"], res["score_ties_top20"])
                print(f"Auteurs ({a['n']}) : P@10 = {a['precision_at_10'].get('mean', 0):.3f}, "
                      f"R@10 = {a['recall_at_10'].get('mean', 0):.3f}")
                print(f"Titres ({t['n']}) : succès@1 = {t['success_at_1']:.2f}, @5 = {t['success_at_5']:.2f}, "
                      f"@10 = {t['success_at_10']:.2f}, MRR = {t['mrr']:.3f}")
                print(f"Suggestions : même auteur = {s['rate_mean']}, hasard = {s['random_baseline_mean']}, lift = {s['lift']}")
                print(f"Égalités de score dans le top-20 : {ties['tie_share'].get('mean', 0):.2%} des paires consécutives")
                print("-> results/relevance_auto.json")
            else:
                make_form(sess, base, args.out, args.k)

    if args.base_url:
        run(args.base_url.rstrip("/"))
    else:
        with ApiServer(db_url(args.admin_url), args.books_dir, port=8767) as srv:
            run(srv.base)


if __name__ == "__main__":
    main()
