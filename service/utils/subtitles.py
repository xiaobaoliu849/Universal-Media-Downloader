import re
from typing import List

# ---------------- Subtitle Utilities: merge multi-line cue to single line ----------------
_cjk_ranges = (
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x3040, 0x30FF),  # Hiragana + Katakana
    (0xAC00, 0xD7AF),  # Hangul Syllables
)

def _is_cjk_char(ch: str) -> bool:
    if not ch: return False
    code = ord(ch)
    for (start, end) in _cjk_ranges:
        if start <= code <= end:
            return True
    return False

def _merge_lines_to_single(lines: List[str]) -> str:
    """
    Merge multiple lines into one logic line.
    Strategy:
      If line A ends with CJK and line B starts with CJK -> join directly
      Otherwise -> join with space
    """
    if not lines:
        return ""
    
    cleaned = [ln.strip() for ln in lines if ln.strip()]
    if not cleaned:
        return ""
        
    result = cleaned[0]
    for i in range(1, len(cleaned)):
        prev = result[-1]
        curr = cleaned[i][0]
        if _is_cjk_char(prev) and _is_cjk_char(curr):
            result += cleaned[i]
        else:
            result += " " + cleaned[i]
    return result

def normalize_srt_inplace(path: str):
    """
    Re-process the .srt file:
    1. Merge multi-line text in one cue block into single line (smart CJK merge).
    2. Overwrite the file.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Regex to find SRT blocks: 
        # Group 1: Index
        # Group 2: Timestamp
        # Group 3: Content (multi-line)
        pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\n((?:.|[\r\n])*?)(?=\n\d+\n|\Z)', re.MULTILINE)
        
        new_blocks = []
        for match in pattern.finditer(content):
            idx = match.group(1)
            ts = match.group(2)
            raw_text = match.group(3)
            lines = raw_text.split('\n')
            merged = _merge_lines_to_single(lines)
            if merged:
                new_blocks.append(f"{idx}\n{ts}\n{merged}\n")
        
        if new_blocks:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(new_blocks))
                
    except Exception:
        pass
