# Benchmarks (tests de performance, de pertinence et de centralité)

Ce dossier est **indépendant du projet** : il n'en modifie aucun fichier. Il importe le code de
`backend/` tel quel et le fait tourner sur une base PostgreSQL **séparée** (`daar_bench`),
jamais sur la vraie base de l'application. À placer à la racine du dépôt (`benchmarks/`, à côté de
`backend/`, `database/`…).

## 0. Pré-requis (une seule fois)

```bash
# depuis la racine du dépôt
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt -r benchmarks/requirements-bench.txt

# PostgreSQL dédié aux mesures, même version et mêmes réglages par défaut que docker-compose.yml.
# Port 55432 pour ne pas gêner la vraie base.
docker run -d --name daar-bench-pg -e POSTGRES_PASSWORD=bench -p 55432:5432 postgres:16-alpine
```

* Les livres doivent être dans `database/books/*.txt` (au moins 1664 livres valides, ≥ 10 000 mots).
  Si la bibliothèque est plus petite, les tailles non atteignables sont ignorées avec un message.
* NLTK télécharge ses mots vides au premier lancement (accès réseau nécessaire une fois).
* Autre PostgreSQL : `export BENCH_ADMIN_URL=postgresql://user:mdp@hote:port/postgres`.
* Fermer les applications gourmandes pendant les mesures, brancher la machine sur secteur,
  ne pas utiliser l'ordinateur pendant `run_benchmark.py` (les temps en dépendent).

## 1. Test rapide (≈ quelques minutes) pour vérifier que tout marche

```bash
python benchmarks/run_benchmark.py --sizes 200 --reps 5 --reps-index 3 --reps-text 2
python benchmarks/make_figures.py
```

## 2. Protocole complet

```bash
bash benchmarks/run_all.sh           # tout enchaîner (compter une à deux heures, à lancer et laisser tourner)
```

ou étape par étape :

| Étape | Commande | Produit |
|---|---|---|
| Indexation, graphe, PageRank, temps de réponse pour N = 200, 500, 1000, 1664 | `python benchmarks/run_benchmark.py` | `results/build_times.json`, `results/query_timings.csv`, `results/queries_selected.json`, `results/machine.json` |
| Test de charge (plusieurs clients) | `python benchmarks/bench_load.py` | `results/load_test_local.json` |
| Pertinence automatique | `python benchmarks/bench_relevance.py auto` | `results/relevance_auto.json` |
| Formulaire du test utilisateur | `python benchmarks/bench_relevance.py make-form` | `results/relevance_form_template.csv` |
| Exemples de centralité | `python benchmarks/bench_centrality.py` | `results/centrality.json`, `results/centrality_tables.tex` |
| Figures, tableaux, macros LaTeX | `python benchmarks/make_figures.py` | `results/figures/*.pdf`, `results/tab_*.tex`, `results/numbers.tex` |

Options utiles de `run_benchmark.py` : `--sizes`, `--reps` (30), `--reps-index` (10), `--reps-text` (5),
`--keep-queries` (si on ne relance qu'une partie des tailles, pour garder les mêmes requêtes),
`--pagerank-impl project|reference` (quel PageRank est stocké dans `books.pagerank` ; défaut : celui du projet).

**Le test de charge pour la démonstration multi-machines** : contre l'application réellement déployée
(nginx + API + base Docker), depuis un autre ordinateur du réseau local :

```bash
python benchmarks/bench_load.py --base-url http://<IP_DU_SERVEUR> --label lan
```
Cela produit `results/load_test_lan.json` et la figure correspondante.

## 3. Test utilisateur (pertinence subjective)

1. `python benchmarks/bench_relevance.py make-form` produit `results/relevance_form_template.csv` (12 requêtes,
   5 premiers résultats + 3 suggestions chacune).
2. Donner une copie à chaque testeur (idéalement 5 personnes ou plus, profils variés) : renseigner la colonne `tester`
   (prénom) et noter chaque ligne de **1** (hors sujet) à **5** (exactement ce que je cherchais) dans `grade_1_to_5`.
   Nommer les fichiers `results/form_<prenom>.csv`.
3. `python benchmarks/bench_relevance.py aggregate results/form_*.csv` puis `python benchmarks/make_figures.py`.

Adapter `FORM_KEYWORD` en tête de `bench_relevance.py` si un terme (ex. « whale ») n'existe pas dans votre bibliothèque.

## 4. Intégration au rapport

1. Copier `results/figures/*.pdf` dans le dossier `figures/` du rapport et `results/numbers.tex`, `results/tab_*.tex`,
   `results/centrality_tables.tex` à côté de votre `.tex`.
2. Ajouter dans le préambule : `\input{numbers}`.
3. Remplacer la section « Tests et performances expérimentales » par `report/section_tests.tex`.
4. Relire les commentaires `% VÉRIFIER` / `% À COMPLÉTER` / `% TODO` : ils signalent les phrases à confronter aux vrais résultats.
   Si une macro n'a pas de valeur (benchmark pas encore lancé), elle s'affiche `[?]` et `make_figures.py` la liste.
5. Les tableaux de `centrality_tables.tex` sont nombreux (top 10, flop 10, 3 fiches livre) : en supprimer pour tenir
   dans la limite de pages du sujet.

## 5. Ce que mesurent les scripts (pour le rapport)

* **Temps de réponse** : temps rapporté par l'API elle-même (`time_ms`), après un échauffement, sur 30 / 10 / 5 répétitions
  selon le mode. Les temps côté client sont aussi enregistrés (`client_ms`).
* **Chargement** : `load_books.load_book` du projet ; **graphe** : `python -m scripts.build_graph` du projet, exécuté tel quel
  (temps total mesuré de l'extérieur + phases lues dans sa sortie) ; **PageRank** : `pagerank()` du projet.
* **Comparaisons de référence, mesurées à part, jamais appliquées au projet** : PageRank en matrice creuse, regex sur le
  vocabulaire distinct (table `bench_vocab`, dans la base de benchmark uniquement), closeness et betweenness.
