import numpy as np


def makeCarryOver(pattern):
	"""Make the carry-over table for the KMP algorithm."""
	m = len(pattern)
	carry_over = [0] * m
	j = 0
	for i in range(1, m):
		while j > 0 and pattern[i] != pattern[j]:
			j = carry_over[j - 1]
		if pattern[i] == pattern[j]:
			j += 1
			carry_over[i] = j
	return carry_over

def kmp_search(text, pattern, carry_over):
	"""KMP string matching algorithm."""
	n = len(text)
	m = len(pattern)
	j = 0
	number_of_occurrences = 0
	for i in range(n):
		while j > 0 and text[i] != pattern[j]:
			j = carry_over[j - 1]
		if text[i] == pattern[j]:
			j += 1
		if j == m:
			number_of_occurrences += 1
			return i - m + 1
	return number_of_occurrences

def listOccurrencs(lines, pattern):
	"""List all occurrences of pattern in text using KMP algorithm."""
	carry_over = makeCarryOver(pattern)
	acceptedLines = []

	for i, text in enumerate(lines):
		if kmp_search(text, pattern, carry_over) != -1:
			acceptedLines.append(i)

	return acceptedLines
