#!/usr/bin/env python3
"""
Test de charge : plusieurs clients simultanés (comme plusieurs ordinateurs/téléphones
connectés à l'application pendant la démonstration).

Scénario A : C clients lancent en boucle des recherches par mots-clés (C = 1, 2, 5, 10, 20).
Scénario B : 5 clients « mots-clés » PENDANT qu'un client lance en boucle des regex sur le TEXTE COMPLET.
Scénario C : idem avec un client qui lance des regex sur l'INDEX.

Deux façons de l'utiliser :
  - par défaut : lance l'API du projet (uvicorn, 1 worker) sur la base de benchmark (taille maximale,
    après run_benchmark.py) ;
  - avec --base-url http://<IP> : teste l'application réellement déployée (nginx + API + base Docker),
    éventuellement depuis UN AUTRE ordinateur du réseau local (--label lan).

    python benchmarks/bench_load.py
    python benchmarks/bench_load.py --base-url http://192.168.1.20 --label lan
"""
import argparse
import random
import threading
import time
from pathlib import Path

import requests

from common import (DEFAULT_ADMIN_URL, REPO, ApiServer, db_url, load_json, save_json, summarize)

DEFAULT_KW = ["love", "sea", "king", "ship", "war", "garden", "mother", "night"]


def light_client(base, queries, stop_at, out, seed):
    rng = random.Random(seed)
    sess = requests.Session()
    while time.perf_counter() < stop_at:
        q = rng.choice(queries)
        t0 = time.perf_counter()
        try:
            r = sess.get(base + "/api/search", params={"q": q}, timeout=600)
            ok = r.ok
        except Exception:
            ok = False
        out.append(((time.perf_counter() - t0) * 1000, ok))


def heavy_client(base, scope, regex, stop_evt, out):
    sess = requests.Session()
    while not stop_evt.is_set():
        t0 = time.perf_counter()
        try:
            r = sess.get(base + "/api/search/advanced", params={"regex": regex, "scope": scope}, timeout=1800)
            ok = r.ok
        except Exception:
            ok = False
        out.append(((time.perf_counter() - t0) * 1000, ok))


def run_level(base, queries, n_light, duration, heavy=None):
    """Retourne un dict de statistiques pour les clients légers (et le client lourd éventuel)."""
    light_out = [[] for _ in range(n_light)]
    stop_at = time.perf_counter() + duration
    heavy_out, stop_evt, ht = [], threading.Event(), None
    if heavy:
        ht = threading.Thread(target=heavy_client, args=(base, heavy[0], heavy[1], stop_evt, heavy_out))
        ht.start()
        time.sleep(0.5)
    t_start = time.perf_counter()
    threads = [threading.Thread(target=light_client, args=(base, queries, stop_at, light_out[i], i))
               for i in range(n_light)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t_start
    stop_evt.set()
    flat = [x for o in light_out for x in o]
    lat = [ms for ms, ok in flat if ok]
    res = {"clients": n_light, "duration_s": round(elapsed, 1), "requests": len(flat),
           "errors": sum(1 for _, ok in flat if not ok),
           "throughput_rps": round(len(lat) / elapsed, 2) if elapsed else 0,
           "latency_ms": summarize(lat)}
    if ht:
        res["heavy_completed"] = len(heavy_out)      # terminées PENDANT la fenêtre de mesure
        res["heavy_latency_ms"] = summarize([ms for ms, ok in heavy_out if ok])
        ht.join()              # on laisse finir la requête lourde en cours avant le scénario suivant
    return res


def run_all(base, queries, args):
    out = {"base_url": base, "label": args.label, "scenario_A": [], "scenario_B_text": None,
           "scenario_C_index": None}
    print("Échauffement…")
    for q in queries:
        requests.get(base + "/api/search", params={"q": q}, timeout=600)
    print("Scénario A : clients mots-clés seuls")
    for c in args.clients:
        r = run_level(base, queries, c, args.duration)
        out["scenario_A"].append(r)
        print(f"  {c:>3} clients : {r['throughput_rps']:7.1f} req/s | moyenne {r['latency_ms'].get('mean', 0):7.1f} ms "
              f"| p95 {r['latency_ms'].get('p95', 0):7.1f} ms | erreurs {r['errors']}")
    rx = args.heavy_regex
    print(f"Scénario B : 5 clients mots-clés + 1 client regex TEXTE ({rx!r}) en boucle")
    out["scenario_B_text"] = run_level(base, queries, 5, args.duration_heavy, heavy=("text", rx))
    r = out["scenario_B_text"]
    print(f"  mots-clés : {r['throughput_rps']} req/s, moyenne {r['latency_ms'].get('mean', 0):.1f} ms, "
          f"p95 {r['latency_ms'].get('p95', 0):.1f} ms ; requêtes lourdes terminées : {r['heavy_completed']}")
    print(f"Scénario C : 5 clients mots-clés + 1 client regex INDEX ({rx!r}) en boucle")
    out["scenario_C_index"] = run_level(base, queries, 5, args.duration_heavy, heavy=("index", rx))
    r = out["scenario_C_index"]
    print(f"  mots-clés : {r['throughput_rps']} req/s, moyenne {r['latency_ms'].get('mean', 0):.1f} ms, "
          f"p95 {r['latency_ms'].get('p95', 0):.1f} ms ; requêtes lourdes terminées : {r['heavy_completed']}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", help="URL d'une application déjà lancée (sinon : API lancée ici sur la base de benchmark)")
    ap.add_argument("--admin-url", default=DEFAULT_ADMIN_URL)
    ap.add_argument("--books-dir", type=Path, default=REPO / "database" / "books")
    ap.add_argument("--clients", type=int, nargs="+", default=[1, 2, 5, 10, 20])
    ap.add_argument("--duration", type=int, default=20, help="secondes par niveau (scénario A)")
    ap.add_argument("--duration-heavy", type=int, default=60, help="secondes (scénarios B et C)")
    ap.add_argument("--heavy-regex", default=r"s(a|g|r)+on")
    ap.add_argument("--label", default="local", help="étiquette du fichier de sortie")
    args = ap.parse_args()

    sel = load_json("queries_selected.json")
    queries = [v for k, v in sel["keyword"].items() if k in ("kw_rare", "kw_mid", "kw_freq", "kw_2words")] \
        if sel else DEFAULT_KW
    if args.base_url:
        res = run_all(args.base_url.rstrip("/"), queries, args)
    else:
        with ApiServer(db_url(args.admin_url), args.books_dir, port=8766) as srv:
            res = run_all(srv.base, queries, args)
    res["queries_used"] = queries
    save_json(f"load_test_{args.label}.json", res)
    print(f"-> results/load_test_{args.label}.json")


if __name__ == "__main__":
    main()
