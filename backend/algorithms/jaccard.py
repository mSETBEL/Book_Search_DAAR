import heapq

import numpy as np
import math



def jaccard_similarity(set1, set2):
	"""
	Compute the Jaccard similarity between two sets. |A ∩ B| / |A ∪ B|
	"""
	intersection = len(set1.intersection(set2))
	union = len(set1.union(set2))
		
	if union == 0:
			return 0.0
		
	return (intersection / union)
	

	
def jaccard_distance(set1, set2):
	"""
	Compute the Jaccard distance between two sets. 1 - |A ∩ B| / |A ∪ B|
	"""
	return 1 - jaccard_similarity(set1, set2)
	

# top n words for each book : a set of the most important words in the book
# we rank by tf-idf to keep out the frequent words like "the", "and", "so"... that are in everybook
# we are then left with the n words that are most significant in the book
def top_n_keywords(counts: dict, n: int = 500, doc_freq: dict = None, n_docs: int = None) -> set:
	"""Return the n most significant words of one book.
 
    counts:   {word: occurrences in this book}
    doc_freq: {word: number of books containing the word} (optional)
    n_docs:   total number of books (needed with doc_freq)
 
    Without doc_freq, words are ranked by raw count (dominated by common
    words, so use stop-word removal). With doc_freq, words are ranked by
    tf-idf, which favours words that characterise this book.
	"""

	if doc_freq is not None and n_docs is not None:
		# compute tf-idf scores
		def score(item):
			word, tf = item
			return tf * math.log(n_docs / (1 + doc_freq.get(word, 0)))
	else:
		def score(item):
			return item[1]
	best = heapq.nlargest(n, counts.items(), key=score)
	return {word for word, _ in best}

#top k neighbors  (k most similar books)
#O(n²)
def top_k_neighbors(sets: dict, k: int = 10, threshold: float = 0.0) -> dict:
    """For every book, its k most similar books.
 
    sets: {book_id: set_of_keywords}
    Returns {book_id: [(other_id, similarity), ...]} sorted best first,
    keeping only similarities above `threshold`.
 
    """
    ids = list(sets)
    result = {}
    for i in ids:
        si = sets[i]
        scored = ((jaccard_similarity(si, sets[j]), j) for j in ids if j != i)
        best = heapq.nlargest(k, scored)
        result[i] = [(j, s) for s, j in best if s > threshold]
    return result


		
