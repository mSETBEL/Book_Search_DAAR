from backend.algorithms import jaccard

def build_graph(sets: dict, k: int = 10, threshold: float = 0.0) -> dict:
	"""For every book, its k most similar books.

	sets: {book_id: set_of_keywords}
	"""
	return jaccard.top_k_neighbors(sets, k=k, threshold=threshold)

if __name__ == "__main__":
    # Example usage
    sets = {
        "book1": {"word1", "word2", "word3"},
        "book2": {"word2", "word3", "word4"},
        "book3": {"word5", "word6"},
    }

    graph = build_graph(sets, k=2, threshold=0.1)
    print(graph)