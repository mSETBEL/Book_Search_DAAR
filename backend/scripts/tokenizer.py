import re
import nltk
from nltk.corpus import stopwords
nltk.download('stopwords')


_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
MIN_LENGTH = 2  # drops stray single letters left by OCR or abbreviations

ENGLISH_STOP_WORDS = set(stopwords.words("english"))


STOP_WORDS = ENGLISH_STOP_WORDS # we can add more stop words later if needed, e.g. from other languages


def tokenize(text: str) -> list:
    """All words of the text that are long enough, lowercased, in order, without stop words.
    Possessives are stripped: "king's" -> "king".
    """
    tokens = []
    for match in _WORD_RE.finditer(text.lower()):
        tok = match.group().replace("’", "'")
        if tok.endswith("'s"):
            tok = tok[:-2]
        if len(tok) >= MIN_LENGTH:
            tokens.append(tok)
    return remove_stop_words(tokens)


def remove_stop_words(tokens) -> list:
    return [t for t in tokens if "'" not in t and t not in STOP_WORDS]


if __name__ == "__main__":
    sample = "The King's army, don't you know, crossed the river _twice_ in 1066!"
    print(tokenize(sample))