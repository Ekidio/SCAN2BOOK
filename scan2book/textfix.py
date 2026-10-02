"""OCR-utáni szövegjavítások (tipográfia + könyvszintű konzisztencia)."""
from __future__ import annotations

import re
from collections import Counter

from .model import TPage

DASHES = {"-", "—", "-—", "—-", "–", "--", "―"}
_PUNCT = ".,;:!?…"
_ACCENT_UP = {
    "O": "ÖŐÓ", "U": "ÜŰÚ", "A": "Á", "E": "É", "I": "Í",
    "Ö": "OŐÓ", "Ü": "UŰÚ", "Ő": "ÖO", "Ű": "ÜU",
}
_strip_re = re.compile(r"^[\"„“”'»«(\[]*(.*?)[\"„“”'»«)\].,;:!?…]*$")


def _core(tok: str) -> str:
    m = _strip_re.match(tok)
    return m.group(1) if m else tok


def fix_typography(tpages: list[TPage]) -> None:
    for tp in tpages:
        lines = list(tp.lines) + ([tp.folio] if tp.folio else [])
        for tl in lines:
            out = []
            for i, r in enumerate(tl.words):
                t = r.text
                if t in DASHES:
                    t = "–"
                elif re.fullmatch(r"[—–-]{1,2}([A-ZÁÉÍÓÖŐÚÜŰa-záéíóöőúüű„].*)", t) and i == 0:
                    # „—Csak” → „– Csak”
                    m = re.fullmatch(r"[—–-]{1,2}(.*)", t)
                    out.append(type(r)("–", r.italic))
                    t = m.group(1)
                # magányos írásjel egy már írásjellel záruló szó után (pl. „hullámzik. .”)
                if t in (".", ",") and out and out[-1].text and out[-1].text[-1] in _PUNCT:
                    continue
                t = t.replace("—", "–") if len(t) > 1 and not t.endswith("—") else t
                if t.endswith("—") and len(t) > 1:
                    t = t[:-1] + "–"
                r.text = t
                out.append(r)
            tl.words = [r for r in out if r.text]


def fix_consistency(tpages: list[TPage]) -> None:
    """Gyakori OCR-hiba: nagybetűs ékezet elvesztése (Ödön → Odön), csupa nagybetűs
    rövid szavak (AZ → Az). A könyv többi előfordulása alapján javítjuk."""
    counts: Counter[str] = Counter()
    for tp in tpages:
        for tl in tp.lines:
            for r in tl.words:
                counts[_core(r.text)] += 1

    repl: dict[str, str] = {}
    for word, n in counts.items():
        if len(word) < 2:
            continue
        c0 = word[0]
        if c0 in _ACCENT_UP:
            for alt in _ACCENT_UP[c0]:
                cand = alt + word[1:]
                if counts.get(cand, 0) >= max(3, 2 * n):
                    repl[word] = cand
                    break
        if word.isupper() and 2 <= len(word) <= 4 and word.isalpha():
            cand = word[0] + word[1:].lower()
            if counts.get(cand, 0) >= max(3, 5 * n):
                repl[word] = cand
    if not repl:
        return
    for tp in tpages:
        for tl in tp.lines:
            for r in tl.words:
                core = _core(r.text)
                if core in repl:
                    r.text = r.text.replace(core, repl[core], 1)


def fix_folios(tpages: list[TPage]) -> None:
    """Az oldalszámok egyesével nőnek: a félreolvasott számokat a sorozatból pótoljuk."""
    nums = []
    for tp in tpages:
        if tp.folio:
            m = re.search(r"\d+", " ".join(r.text for r in tp.folio.words))
            if m:
                nums.append(int(m.group()) - tp.index)
    if len(nums) < 3:
        return
    offset, cnt = Counter(nums).most_common(1)[0]
    if cnt < 0.5 * len(nums):
        return
    # a leggyakoribb oldalszám-forma (pl. „– # –” vagy „~ # ~”)
    templates = Counter()
    for tp in tpages:
        if tp.folio:
            txt = " ".join(r.text for r in tp.folio.words)
            if re.fullmatch(r"\D*\d+\D*", txt):
                templates[re.sub(r"\d+", "#", txt)] += 1
    template = templates.most_common(1)[0][0] if templates else "#"
    for tp in tpages:
        if not tp.folio:
            continue
        txt = " ".join(r.text for r in tp.folio.words)
        if not re.search(r"\d", txt):
            continue
        new = template.replace("#", str(tp.index + offset))
        tp.folio.words = [type(tp.folio.words[0])(t, False) for t in new.split()]
