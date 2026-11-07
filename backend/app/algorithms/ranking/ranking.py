PAGERANK_WEIGHT = 0.3  # score = (1 - w) * occurrences + w * pagerank


def rank(rows, pagerank_weight=PAGERANK_WEIGHT):
	"""Rank books by a weighted combination of occurrences and pagerank."""
    
	rows = list(rows)
	max_occ = max((r[3] for r in rows), default=0) or 1
	max_pr = max((r[4] for r in rows), default=0.0)
	w = pagerank_weight if max_pr > 0 else 0.0
	ranked = []
	for book_id, title, author, occ, pr in rows:
		score = (1 - w) * occ / max_occ + (w * pr / max_pr if w else 0.0) 
		ranked.append({"id": book_id, "title": title, "author": author,"occurrences": occ, "centrality": pr,"score": round(score, 3)})
	ranked.sort(key=lambda r: (r["score"], r["occurrences"]), reverse=True)
	return ranked