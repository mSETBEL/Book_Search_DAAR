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