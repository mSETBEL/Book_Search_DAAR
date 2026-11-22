#!/usr/bin/env bash
# Enchaîne tout le protocole de test. À lancer depuis la RACINE du dépôt :
#     bash benchmarks/run_all.sh
# Pré-requis : voir benchmarks/README.md (conteneur PostgreSQL de benchmark démarré,
# livres dans database/books/, pip install -r backend/requirements.txt -r benchmarks/requirements-bench.txt).
set -euo pipefail
cd "$(dirname "$0")"

echo "### 1/6  Indexation, graphe, PageRank, temps de réponse (le plus long)"
python run_benchmark.py "$@"

echo "### 2/6  Test de charge"
python bench_load.py

echo "### 3/6  Pertinence (métriques automatiques)"
python bench_relevance.py auto

echo "### 4/6  Formulaire du test utilisateur"
python bench_relevance.py make-form

echo "### 5/6  Exemples de centralité"
python bench_centrality.py

echo "### 6/6  Figures, tableaux et macros LaTeX"
python make_figures.py

echo
echo "Terminé. Reste à faire noter results/relevance_form_template.csv par des testeurs, puis :"
echo "  python benchmarks/bench_relevance.py aggregate results/form_*.csv && python benchmarks/make_figures.py"
