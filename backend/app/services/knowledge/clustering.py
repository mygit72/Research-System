"""Clustering algorithms for paper embeddings, written out in numpy.

All three work on L2-normalized vectors with cosine distance (1 − cos), the same
geometry the dense retriever uses:

- **K-Means** (spherical via normalization) with k-means++ seeding and several
  restarts; `auto_kmeans` picks k by the silhouette score.
- **Agglomerative** clustering with average linkage (UPGMA), Lance–Williams updates,
  cut at k clusters or at a distance threshold.
- **HDBSCAN** (Campello, Moulavi & Sander, 2013): core distances → mutual reachability
  graph → minimum spanning tree (Prim) → single-linkage hierarchy → condensed tree
  with `min_cluster_size` → clusters chosen by excess of mass (stability). Points in
  no stable cluster are noise (label −1) — HDBSCAN says "this paper fits no group"
  instead of forcing it into one.

Library sizes are hundreds of papers, so O(n²) memory for the distance matrix is fine
and keeps every step inspectable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

NOISE = -1


def normalize(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    out: np.ndarray = x / np.maximum(norms, 1e-12)
    return out


def cosine_distances(x: np.ndarray) -> np.ndarray:
    xn = normalize(x)
    d = 1.0 - xn @ xn.T
    np.fill_diagonal(d, 0.0)
    out: np.ndarray = np.clip(d, 0.0, 2.0)
    return out


# --- K-Means -------------------------------------------------------------------------------------


@dataclass
class KMeansResult:
    labels: np.ndarray
    centroids: np.ndarray
    inertia: float
    iterations: int


def _kmeans_pp(x: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    """k-means++: each next centre is drawn with probability ∝ squared distance."""
    centres = [x[rng.integers(len(x))]]
    closest = ((x - centres[0]) ** 2).sum(axis=1)
    for _ in range(1, k):
        total = closest.sum()
        if total <= 0:  # all remaining points coincide with a centre
            centres.append(x[rng.integers(len(x))])
            continue
        idx = rng.choice(len(x), p=closest / total)
        centres.append(x[idx])
        closest = np.minimum(closest, ((x - x[idx]) ** 2).sum(axis=1))
    return np.array(centres)


def kmeans(
    x: np.ndarray, k: int, *, n_init: int = 8, max_iter: int = 100, seed: int = 0
) -> KMeansResult:
    x = normalize(x)
    if not 1 <= k <= len(x):
        raise ValueError(f"k must be between 1 and {len(x)}")
    rng = np.random.default_rng(seed)
    best: KMeansResult | None = None
    for _ in range(n_init):
        centres = _kmeans_pp(x, k, rng)
        labels = np.zeros(len(x), dtype=int)
        iterations = 0
        for iterations in range(1, max_iter + 1):
            dist = ((x[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
            new_labels = dist.argmin(axis=1)
            new_centres = centres.copy()
            for j in range(k):
                members = x[new_labels == j]
                if len(members):
                    new_centres[j] = members.mean(axis=0)
                else:  # empty cluster: restart it at the point farthest from its centre
                    new_centres[j] = x[dist.min(axis=1).argmax()]
            converged = iterations > 1 and np.array_equal(new_labels, labels)
            labels, centres = new_labels, new_centres
            if converged:
                break
        inertia = float(((x - centres[labels]) ** 2).sum())
        if best is None or inertia < best.inertia - 1e-12:
            best = KMeansResult(labels, centres, inertia, iterations)
    assert best is not None
    return best


def silhouette(distances: np.ndarray, labels: np.ndarray) -> float | None:
    """Mean silhouette over non-noise points; None when it isn't defined (< 2 clusters)."""
    mask = labels != NOISE
    d, lab = distances[np.ix_(mask, mask)], labels[mask]
    clusters = np.unique(lab)
    if len(clusters) < 2 or len(lab) <= len(clusters):
        return None
    scores = np.zeros(len(lab))
    for i in range(len(lab)):
        own = lab == lab[i]
        if own.sum() <= 1:
            continue  # singleton: silhouette 0 by convention
        a = d[i, own].sum() / (own.sum() - 1)
        b = min(d[i, lab == c].mean() for c in clusters if c != lab[i])
        scores[i] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return float(scores.mean())


@dataclass
class AutoK:
    k: int
    result: KMeansResult
    scores: dict[int, float | None] = field(default_factory=dict)


def auto_kmeans(
    x: np.ndarray, k_min: int = 2, k_max: int = 8, seed: int = 0, tolerance: float = 0.02
) -> AutoK:
    """K-Means for every k in range; keep the smallest k whose silhouette is within
    `tolerance` of the best (outliers otherwise "win" a few extra tiny clusters)."""
    n = len(x)
    k_max = max(1, min(k_max, n - 1))
    if n < 3 or k_max < k_min:
        result = kmeans(x, 1, seed=seed)
        return AutoK(1, result, {1: None})
    distances = cosine_distances(x)
    scores: dict[int, float | None] = {}
    results: dict[int, KMeansResult] = {}
    for k in range(k_min, k_max + 1):
        results[k] = kmeans(x, k, seed=seed)
        score = silhouette(distances, results[k].labels)
        scores[k] = None if score is None else round(score, 4)
    valid = {k: s for k, s in scores.items() if s is not None}
    if not valid:
        return AutoK(1, kmeans(x, 1, seed=seed), scores)
    top = max(valid.values())
    k = min(k for k, s in valid.items() if s >= top - tolerance)
    return AutoK(k, results[k], scores)


# --- Agglomerative (average linkage) -------------------------------------------------------------


def agglomerative(
    distances: np.ndarray, *, k: int | None = None, threshold: float | None = None
) -> np.ndarray:
    """Average-linkage clustering; stop at `k` clusters or when the closest pair of
    clusters is farther apart than `threshold` (cosine distance)."""
    n = len(distances)
    if k is None and threshold is None:
        raise ValueError("Give k or threshold")
    target = max(1, min(k, n)) if k is not None else 1
    d = distances.astype(np.float64).copy()
    np.fill_diagonal(d, np.inf)
    active = np.ones(n, dtype=bool)
    sizes = np.ones(n)
    members: list[list[int]] = [[i] for i in range(n)]
    count = n
    while count > target:
        masked = np.where(active[:, None] & active[None, :], d, np.inf)
        i, j = np.unravel_index(np.argmin(masked), masked.shape)
        if threshold is not None and masked[i, j] > threshold:
            break
        i, j = min(i, j), max(i, j)
        # Lance–Williams for average linkage: d(i∪j, m) = (|i| d(i,m) + |j| d(j,m)) / (|i|+|j|)
        merged = (sizes[i] * d[i] + sizes[j] * d[j]) / (sizes[i] + sizes[j])
        d[i, :], d[:, i] = merged, merged
        d[i, i] = np.inf
        d[j, :], d[:, j] = np.inf, np.inf
        sizes[i] += sizes[j]
        members[i].extend(members[j])
        members[j] = []
        active[j] = False
        count -= 1
    labels = np.empty(n, dtype=int)
    for label, cluster in enumerate(sorted((m for m in members if m), key=min)):
        labels[cluster] = label
    return labels


# --- HDBSCAN -------------------------------------------------------------------------------------


@dataclass
class HDBSCANResult:
    labels: np.ndarray
    stabilities: dict[int, float]  # label → stability of the selected cluster
    condensed_clusters: int


def _prim_mst(weights: np.ndarray) -> list[tuple[int, int, float]]:
    n = len(weights)
    in_tree = np.zeros(n, dtype=bool)
    best = np.full(n, np.inf)
    parent = np.full(n, -1)
    best[0] = 0.0
    edges: list[tuple[int, int, float]] = []
    for _ in range(n):
        candidates = np.where(in_tree, np.inf, best)
        u = int(np.argmin(candidates))
        in_tree[u] = True
        if parent[u] >= 0:
            edges.append((int(parent[u]), u, float(best[u])))
        closer = (~in_tree) & (weights[u] < best)
        best[closer] = weights[u][closer]
        parent[closer] = u
    return edges


def hdbscan(
    distances: np.ndarray, *, min_cluster_size: int = 3, min_samples: int | None = None
) -> HDBSCANResult:
    n = len(distances)
    min_cluster_size = max(2, min_cluster_size)
    min_samples = max(1, min(min_samples or min_cluster_size, n))
    if n < min_cluster_size * 2:
        return HDBSCANResult(np.full(n, NOISE), {}, 0)

    # 1. Core distance: distance to the min_samples-th nearest point (the point included).
    core = np.sort(distances, axis=1)[:, min_samples - 1]
    # 2. Mutual reachability: dense regions keep their distances, sparse points are pushed away.
    mreach = np.maximum(distances, np.maximum(core[:, None], core[None, :]))
    np.fill_diagonal(mreach, np.inf)
    # 3. Minimum spanning tree, then single-linkage merges in order of distance.
    edges = sorted(_prim_mst(mreach), key=lambda e: e[2])
    parent = list(range(2 * n - 1))
    size = [1] * n + [0] * (n - 1)
    children: dict[int, tuple[int, int, float]] = {}

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    node = n
    for a, b, w in edges:
        ra, rb = find(a), find(b)
        children[node] = (ra, rb, w)
        size[node] = size[ra] + size[rb]
        parent[ra] = parent[rb] = node
        node += 1
    root = node - 1

    def leaves(start: int) -> list[int]:
        out, stack = [], [start]
        while stack:
            current = stack.pop()
            if current < n:
                out.append(current)
            else:
                left, right, _ = children[current]
                stack.extend((left, right))
        return out

    # 4. Condensed tree: walk down from the root; a split counts only when both sides have
    #    at least min_cluster_size points, otherwise the small side "falls out" (λ = 1/d).
    births = [0.0]
    cluster_parent = [-1]
    cluster_children: list[list[int]] = [[]]
    fallen: list[list[tuple[int, float]]] = [[]]  # (point, λ when it left the cluster)
    split: list[tuple[float, int] | None] = [None]  # (λ, points at the split)
    stack = [(root, 0)]
    while stack:
        current, cluster = stack.pop()
        if current < n:
            fallen[cluster].append((current, births[cluster]))
            continue
        left, right, dist = children[current]
        lam = 1.0 / max(dist, 1e-6)
        big_left, big_right = size[left] >= min_cluster_size, size[right] >= min_cluster_size
        if big_left and big_right:
            split[cluster] = (lam, size[current])
            for child in (left, right):
                births.append(lam)
                cluster_parent.append(cluster)
                cluster_children.append([])
                fallen.append([])
                split.append(None)
                new = len(births) - 1
                cluster_children[cluster].append(new)
                stack.append((child, new))
        elif not big_left and not big_right:
            fallen[cluster].extend((p, lam) for p in leaves(current))
        else:
            small, big = (right, left) if big_left else (left, right)
            fallen[cluster].extend((p, lam) for p in leaves(small))
            stack.append((big, cluster))

    # 5. Stability (excess of mass): Σ over points of (λ_leave − λ_birth).
    stability = []
    for c, birth in enumerate(births):
        s = sum(lam - birth for _, lam in fallen[c])
        if split[c] is not None:
            lam, count = split[c]  # type: ignore[misc]
            s += count * (lam - birth)
        stability.append(s)

    # 6. Excess-of-mass selection, bottom-up (children always have larger ids than parents).
    selected = [False] * len(births)
    best = list(stability)
    for c in range(len(births) - 1, 0, -1):  # the root is never a cluster
        kids = cluster_children[c]
        if not kids:
            selected[c] = True
            continue
        child_total = sum(best[k] for k in kids)
        if stability[c] >= child_total:
            selected[c] = True
            stack_ids = list(kids)
            while stack_ids:
                k = stack_ids.pop()
                selected[k] = False
                stack_ids.extend(cluster_children[k])
        else:
            best[c] = child_total

    # 7. Labels: a point belongs to the selected cluster above the cluster it fell out of.
    owner: dict[int, int] = {}
    for c in range(len(births)):
        ancestor = c
        while ancestor > 0 and not selected[ancestor]:
            ancestor = cluster_parent[ancestor]
        if ancestor > 0:
            owner[c] = ancestor
    chosen = sorted({o for o in owner.values()})
    relabel = {c: i for i, c in enumerate(chosen)}
    labels = np.full(n, NOISE)
    for c, points in enumerate(fallen):
        if c in owner:
            for p, _ in points:
                labels[p] = relabel[owner[c]]
    return HDBSCANResult(
        labels=labels,
        stabilities={relabel[c]: round(stability[c], 4) for c in chosen},
        condensed_clusters=len(births),
    )


# --- 2-D projection ------------------------------------------------------------------------------


def pca_2d(x: np.ndarray) -> np.ndarray:
    """Project onto the top two principal components, scaled to [-1, 1]."""
    x = normalize(x)
    if len(x) == 1:
        return np.zeros((1, 2))
    centred = x - x.mean(axis=0)
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    coords = centred @ vt[:2].T
    if coords.shape[1] < 2:
        coords = np.pad(coords, ((0, 0), (0, 2 - coords.shape[1])))
    # Deterministic orientation: make the largest-magnitude coordinate of each axis positive.
    for axis in range(2):
        if coords[np.abs(coords[:, axis]).argmax(), axis] < 0:
            coords[:, axis] *= -1
    scale = np.abs(coords).max()
    return coords / scale if scale > 0 else coords


def explained_variance_2d(x: np.ndarray) -> float:
    x = normalize(x)
    centred = x - x.mean(axis=0)
    s = np.linalg.svd(centred, compute_uv=False)
    total = (s**2).sum()
    return float((s[:2] ** 2).sum() / total) if total > 0 else 1.0
