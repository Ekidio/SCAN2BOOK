"""Közös adatszerkezetek az OCR, az elrendezés-elemzés és a szedés között."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float = 100.0
    italic: bool = False

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class Line:
    words: list[Word]

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)

    @property
    def y0(self) -> float:
        return min(w.y0 for w in self.words)

    @property
    def y1(self) -> float:
        return max(w.y1 for w in self.words)

    @property
    def cy(self) -> float:
        # a szavak középvonalainak mediánja: görbült sorokon is stabil
        cs = sorted((w.y0 + w.y1) / 2 for w in self.words)
        return cs[len(cs) // 2]

    @property
    def word_h(self) -> float:
        hs = sorted(w.h for w in self.words)
        return hs[len(hs) // 2]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Figure:
    x0: float
    y0: float
    x1: float
    y1: float
    path: str     # kivágott kép (PNG) helye


@dataclass
class PageOCR:
    index: int
    width: int    # a feldolgozott kép mérete pixelben
    height: int
    lines: list[Line] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "PageOCR":
        lines = [Line([Word(**w) for w in ln["words"]]) for ln in d["lines"]]
        figs = [Figure(**f) for f in d.get("figures", [])]
        return PageOCR(d["index"], d["width"], d["height"], lines, figs)


# --- az elrendezés-elemzés kimenete -------------------------------------------

@dataclass
class Run:
    text: str
    italic: bool = False


@dataclass
class TLine:
    """Egy kiszedendő sor, már eszközfüggetlen (szövegtükör-relatív) egységekben."""
    words: list[Run]
    align: str            # justify | left | center | right
    indent: float         # a szövegtükör szélességének hányadában
    grid: float           # sorrács-index (0 = a szövegtükör első sora)
    size: float = 1.0     # betűméret a kenyérszöveghez képest
    role: str = "body"    # body | heading | folio


@dataclass
class TFigure:
    path: str
    x: float       # bal szél, a szövegtükör szélességének hányadában
    w: float       # szélesség, ugyanígy
    grid: float    # felső szél a sorrácsban (sorközegységben)
    h: float       # magasság sorközegységben


@dataclass
class TPage:
    index: int
    lines: list[TLine]
    folio: TLine | None = None
    figures: list[TFigure] = field(default_factory=list)
