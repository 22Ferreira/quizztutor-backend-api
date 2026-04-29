import re
from app.config import settings

def simple_out_of_scope_detector(scope_text: str, user_msg: str) -> bool:
    # heuristic: if user asks about unrelated subjects (very rough). We also do token overlap.
    def tok(s): 
        return set(re.findall(r"[\wÀ-ÿ]{4,}", s.lower()))
    a = tok(scope_text)
    b = tok(user_msg)
    if not a or not b:
        return False
    inter = len(a & b)
    ratio = inter / max(1, len(b))
    return ratio < settings.TUTOR_SIMILARITY_THRESHOLD
