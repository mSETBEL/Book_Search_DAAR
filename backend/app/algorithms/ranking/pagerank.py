import numpy as np

def sparseProdMatVec(sparseMat, vec):
	"""Sparse matrix vector product"""
	u = np.zeros(sparseMat.shape[0])
	for i in range(sparseMat.shape[0]):
		for j in range(sparseMat.shape[1]):
			if sparseMat[i, j] != 0:
				u[i] += sparseMat[i, j] * vec[j]
	return u

def powerIteration(T,t,s, initState): 
	"""Power iteration algorithm to compute the stationary distribution of a Markov chain.
	T: transition matrix (numpy array)
	t: number of iterations
	s: teleportation factor (between 0 and 1)
	initState: initial state vector (numpy array)
	"""
	I = np.ones(T.shape[0]) / T.shape[0]
	X = initState
	for i in range(t):
		X = sparseProdMatVec(T, X)
		X = X *(1 - s) + I * s
		X /= np.linalg.norm(X, 1)

	return X


def pagerank(edges, book_ids, s=0.15, t=100):
	"""Compute PageRank scores for a graph represented by edges.
	edges: list of tuples (a, b, weight) representing directed edges from a to b with given weight
	book_ids: list of book IDs corresponding to the nodes in the graph
	s: teleportation factor (between 0 and 1)
	t: number of iterations
	"""
	n = len(book_ids)
	if n == 0:
		return {}
	
	# Create a mapping from book_id to index
	book_id_to_index = {book_id: i for i, book_id in enumerate(book_ids)}
	
	# Create the transition matrix
	T = np.zeros((n, n))
	for a, b, weight in edges:
		if a in book_id_to_index and b in book_id_to_index:
			i = book_id_to_index[a]
			j = book_id_to_index[b]
			T[i, j] += weight
	
	# Normalize the rows of the transition matrix
	row_sums = T.sum(axis=1)
	for i in range(n):
		if row_sums[i] > 0:
			T[i] /= row_sums[i]
	
	# Initial state vector (uniform distribution)
	initState = np.ones(n) / n
	
	# Compute PageRank using power iteration
	scores_vector = powerIteration(T, t, s, initState)
	
	# Map scores back to book_ids
	scores = {book_id: scores_vector[book_id_to_index[book_id]] for book_id in book_ids}
	
	return scores