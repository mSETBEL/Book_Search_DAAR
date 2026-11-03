import numpy as np

def bad_char_heuristic(pattern, alphabet):
	"""Create the bad character heuristic table for the Boyer-Moore algorithm."""
	bad_char = [-1] * len(alphabet)
	for i in range(len(pattern)):
		bad_char[ord(pattern[i])] = i
	return bad_char


def preprocess_strong_suffix(shift, bpos, pat, m):
    """Preprocessing for strong good suffix rule."""
    # m is the length of pattern 
    i = m
    j = m + 1
    bpos[i] = j

    while i > 0:
        """if character at position i-1 is not equivalent to character at j-1, 
        then continue searching to right of the pattern for border """
        while j <= m and pat[i - 1] != pat[j - 1]:
            """
            the character preceding the occurrence of t in pattern P is different than the mismatching character in P,
            we stop skipping the occurrences and shift the pattern
            """
            # from i to j 
            if shift[j] == 0:
                shift[j] = j - i

            # Update the position of next border 
            j = bpos[j]
        # p[i-1] matched with p[j-1], border is found.
        # store the  beginning position of border 
        i -= 1
        j -= 1
        bpos[i] = j


def preprocess_case2(shift, bpos, pat, m):
    """Preprocessing for case 2."""
    j = bpos[0]
    for i in range(m + 1):
        # set the border position of the first character of the pattern to all indices in array shift having shift[i] = 0 
        if shift[i] == 0:
            shift[i] = j

        # suffix becomes shorter than bpos[0], use the position of next widest border as value of j 
        if i == j:
            j = bpos[j]


def search(text, pat):
	"""Boyer-Moore string matching algorithm using bad character and good suffix heuristics."""

    # s is shift of the pattern with respect to text
	s = 0
	m = len(pat)
	n = len(text)

	bpos = [0] * (m + 1)
	shift = [0] * (m + 1)


    # do preprocessing
	preprocess_strong_suffix(shift, bpos, pat, m)
	preprocess_case2(shift, bpos, pat, m)
	bad_char = bad_char_heuristic(pat, range(256))

	while s <= n - m:
		j = m - 1
		while j >= 0 and pat[j] == text[s + j]:
			j -= 1
		if j < 0:
            #print("Pattern occurs at shift = {}".format(s))
			s += (m - bad_char[ord(text[s + m])] if s + m < n else 1)
		else:
			s+= max(shift[j + 1], j - bad_char[ord(text[s + j])])

