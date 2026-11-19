"""Placering der maksimerer forventet overlevelse - med fast fordeling mellem by og land.

Hver beboer vægtes ens (efter alder): gevinsten ved et nyt sted er stigningen i
overlevelsessandsynlighed for alle, der får kortere tid til første stød, gange
deres risiko. Med `shares` fordeles stederne mellem urbaniseringsklasser i samme
forhold som hjertestoppene: ethvert top-N-udsnit har den fordeling, så listen
ikke kan skævvrides mod tætte byområder. Inden for hver klasse vælges grådigt
med lazy evaluation (målfunktionen er submodulær).
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from src.survival import survival, time_to_aed


@dataclass(frozen=True)
class Hoods:
    """Naboskaber i CSR-form: kandidat c rækker til efterspørgselscellerne idx[indptr[c]:indptr[c+1]]."""

    indptr: np.ndarray
    idx: np.ndarray
    dist: np.ndarray


@dataclass(frozen=True)
class FairPick:
    rank: int
    candidate: int
    klasse: int
    gain: float
    improved_cells: tuple[int, ...]
    delta_survival: tuple[float, ...]


def build_neighbourhoods(demand_xy: np.ndarray, cand_xy: np.ndarray, radii: np.ndarray, chunk: int = 50_000) -> Hoods:
    tree = cKDTree(demand_xy)
    lens_parts, idx_parts, dist_parts = [], [], []
    for start in range(0, len(cand_xy), chunk):
        c = cand_xy[start : start + chunk]
        lists = tree.query_ball_point(c, r=radii[start : start + chunk], workers=-1, return_sorted=False)
        lens = np.fromiter((len(h) for h in lists), dtype=np.int64, count=len(lists))
        flat = np.fromiter(itertools.chain.from_iterable(lists), dtype=np.int64, count=int(lens.sum()))
        owner = np.repeat(np.arange(len(c)), lens)
        d = np.hypot(demand_xy[flat, 0] - c[owner, 0], demand_xy[flat, 1] - c[owner, 1])
        lens_parts.append(lens)
        idx_parts.append(flat.astype(np.int32))
        dist_parts.append(d.astype(np.float32))
    lens = np.concatenate(lens_parts) if lens_parts else np.zeros(0, np.int64)
    indptr = np.concatenate([[0], np.cumsum(lens)]).astype(np.int64)
    idx = np.concatenate(idx_parts) if idx_parts else np.zeros(0, np.int32)
    dist = np.concatenate(dist_parts) if dist_parts else np.zeros(0, np.float32)
    return Hoods(indptr, idx, dist)


class _State:
    def __init__(self, risk: np.ndarray, cur_t: np.ndarray, hoods: Hoods):
        self.risk = risk
        self.s_cur = survival(cur_t)
        self.hoods = hoods
        self.s_aed = survival(time_to_aed(hoods.dist))

    def all_gains(self) -> np.ndarray:
        h = self.hoods
        contrib = self.risk[h.idx] * np.maximum(self.s_aed - self.s_cur[h.idx], 0)
        owner = np.repeat(np.arange(len(h.indptr) - 1), np.diff(h.indptr))
        return np.bincount(owner, weights=contrib, minlength=len(h.indptr) - 1)

    def gain(self, c: int) -> float:
        s, e = self.hoods.indptr[c], self.hoods.indptr[c + 1]
        j = self.hoods.idx[s:e]
        return float((self.risk[j] * np.maximum(self.s_aed[s:e] - self.s_cur[j], 0)).sum())

    def accept(self, c: int) -> tuple[tuple[int, ...], tuple[float, ...]]:
        s, e = self.hoods.indptr[c], self.hoods.indptr[c + 1]
        j = self.hoods.idx[s:e]
        better = self.s_aed[s:e] > self.s_cur[j]
        cells = j[better]
        delta = self.s_aed[s:e][better] - self.s_cur[cells]
        self.s_cur[cells] = self.s_aed[s:e][better]
        return tuple(cells.tolist()), tuple(delta.tolist())


def _pick_class(heaps: list[list], picked: np.ndarray, shares: np.ndarray | None, n: int) -> int | None:
    alive = [k for k, h in enumerate(heaps) if h]
    if not alive:
        return None
    if shares is None:
        return max(alive, key=lambda k: -heaps[k][0][0])
    return max(alive, key=lambda k: ((n + 1) * shares[k] - picked[k], -heaps[k][0][0]))


def fair_greedy(
    risk: np.ndarray,
    cur_t: np.ndarray,
    cand_class: np.ndarray,
    hoods: Hoods,
    k: int,
    shares: np.ndarray | None,
    min_gain: float = 1e-9,
) -> list[FairPick]:
    """Vælg op til `k` steder. `shares=None` giver ren effektivitet uden fordelingskrav.

    `cur_t` er nuværende tid til første stød (min) pr. efterspørgselscelle og ændres ikke.
    """
    state = _State(risk, np.asarray(cur_t, dtype=float), hoods)
    gains = state.all_gains()
    n_classes = 1 if shares is None else len(shares)
    pool = np.zeros(len(cand_class), dtype=int) if shares is None else cand_class
    heaps: list[list] = [[] for _ in range(n_classes)]
    for c in np.flatnonzero(gains > min_gain):
        heaps[pool[c]].append((-gains[c], int(c)))
    for h in heaps:
        heapq.heapify(h)

    picks: list[FairPick] = []
    picked = np.zeros(n_classes)
    while len(picks) < k:
        cls = _pick_class(heaps, picked, shares, len(picks))
        if cls is None:
            break
        heap = heaps[cls]
        _, c = heapq.heappop(heap)
        fresh = state.gain(c)
        if fresh <= min_gain:
            continue
        if heap and fresh < -heap[0][0]:
            heapq.heappush(heap, (-fresh, c))
            continue
        cells, delta = state.accept(c)
        picked[cls] += 1
        picks.append(FairPick(len(picks) + 1, c, int(cand_class[c]), fresh, cells, delta))
    return picks
