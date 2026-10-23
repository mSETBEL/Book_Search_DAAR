# Book_Search_DAAR 

lien vers rapport : 
https://www.overleaf.com/project/6adbb2fed75dded5e5cea2a1/share#1135ca6eb90859bd6edad5feb742bd1c998719aae1a2b5d9 

## TO DO LIST 
- partie algos (backend) :
  - implementer recherche simple : lookup dans l’index
  - implémenter recherche avancée : appliquer la RegEx sur le vocabulaire de l’index (rapide), bonus: sur le texte complet (lent, à mesurer tests de perf) 
  - implementer graphe de Jaccard : distance entre ensembles de mots des livres, avec arête si la distance est sous un seuil (seuil à définir)
  - Centralité : PageRank est le plus simple et supporte bien un graphe non connexe. Closeness pose problème sur un graphe non connexe. Betweenness (algorithme de Brandes, O(VE)) est plus coûteux. Le plus sûr est d’implémenter PageRank, et une deuxième mesure si le temps le permet, pour pouvoir comparer dans le rapport.
  - Classement : combiner occurrences et centralité, et documenter la formule.
  - Suggestion : voisins dans le graphe de Jaccard des 2-3 meilleurs résultats

- partie data:
  - Récupérer au moins livres de min 10 000 mots (commencer par 10)
  - Nettoyer les en-têtes et pieds de page Gutenberg, puis tokeniser (minuscules, ponctuation, mots vides)
  - Construire l’index inversé : mot → {livre : nombre d’occurrences}.

- partie client/serveur (frontend):
  - API REST branchée sur l’index et le graphe précalculés
 
- tests de perf:
  - temps de réponse en fonction de la taille de la bibliothèque (200, 500, 1000, 1664 livres), recherche simple contre RegEx sur l’index et sur le texte complet, temps de construction du graphe.
  - Pertinence : subjectif, tester si on aime les résultats
  - Exemples de centralité sur un échantillon de livres
  
