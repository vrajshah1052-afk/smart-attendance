"""Recognition benchmark: latency + accuracy vs gallery size (100 / 1k / 10k embeddings).

The gallery is synthetic but shaped like ArcFace score distributions: genuine
pairs mostly 0.45-0.75 with a low tail (pose, blur, glasses), impostors near 0
with a lookalike tail (identities drawn from shared "family" clusters).
--difficulty easy | realistic | hard controls those tails.
Backends compared:
  numpy        - the production EmbeddingIndex (exact, max over a student's templates)
  faiss-flat   - FAISS IndexFlatIP (exact)
  faiss-hnsw   - FAISS HNSW graph (approximate nearest neighbour)
Optionally times the real face engine on images with --images DIR.

    python -m scripts.benchmark                      # charts + JSON/CSV in ./benchmarks
    python -m scripts.benchmark --sizes 100 1000 10000 100000 --threshold 0.45
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

import numpy as np

from app.face.matcher import HAS_FAISS, EmbeddingIndex

if HAS_FAISS:
    import faiss

DIM = 512
DIFFICULTY = {  # (mean alignment of a sample to its identity, sd, max lookalike correlation)
    "easy": (0.82, 0.04, 0.0),
    "realistic": (0.76, 0.08, 0.35),
    "hard": (0.70, 0.10, 0.60),
}


def unit_rows(rng: np.random.Generator, n: int) -> np.ndarray:
    m = rng.standard_normal((n, DIM)).astype(np.float32)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def samples_of(base: np.ndarray, rng: np.random.Generator, k: int, mu: float, sd: float) -> np.ndarray:
    """k noisy captures of one identity; alignment to the identity ~ N(mu, sd)."""
    s = np.clip(rng.normal(mu, sd, size=(k, 1)), 0.35, 0.98).astype(np.float32)
    noise = unit_rows(rng, k)
    noise -= (noise @ base)[:, None] * base[None, :]
    noise /= np.linalg.norm(noise, axis=1, keepdims=True)
    out = s * base[None, :] + np.sqrt(1 - s ** 2) * noise
    return out / np.linalg.norm(out, axis=1, keepdims=True)


def identities(rng: np.random.Generator, n: int, centres: np.ndarray, rho_max: float) -> np.ndarray:
    """People drawn from a population with lookalike clusters."""
    unique = unit_rows(rng, n)
    if rho_max <= 0:
        return unique
    rho = rng.uniform(0, rho_max, size=(n, 1)).astype(np.float32)
    c = centres[rng.integers(0, len(centres), size=n)]
    out = np.sqrt(rho) * c + np.sqrt(1 - rho) * unique
    return out / np.linalg.norm(out, axis=1, keepdims=True)


def make_dataset(n_embeddings: int, per_student: int, n_queries: int, seed: int, difficulty: str):
    mu, sd, rho_max = DIFFICULTY[difficulty]
    rng = np.random.default_rng(seed)
    n_students = max(1, n_embeddings // per_student)
    centres = unit_rows(rng, max(1, n_students // 25))
    bases = identities(rng, n_students, centres, rho_max)
    labels, rows = [], []
    for i, b in enumerate(bases):
        rows.append(samples_of(b, rng, per_student, mu, sd))
        labels += [f"S{i:06d}"] * per_student
    gallery = np.vstack(rows)[:n_embeddings]
    labels = labels[:n_embeddings]
    who = rng.integers(0, n_students, size=n_queries)
    genuine = np.vstack([samples_of(bases[i], rng, 1, mu, sd) for i in who])
    strangers = identities(rng, n_queries, centres, rho_max)  # unseen people, same population
    impostor = np.vstack([samples_of(b, rng, 1, mu, sd) for b in strangers])
    return gallery, labels, genuine, [f"S{i:06d}" for i in who], impostor


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else 0.0


def evaluate(search, genuine, truth, impostor, threshold):
    """search(q) -> (best_label, best_score)."""
    single = []
    correct = false_reject = false_accept = 0
    for q, t in zip(genuine, truth):
        t0 = time.perf_counter()
        label, score = search(q)
        single.append((time.perf_counter() - t0) * 1000)
        if score >= threshold and label == t:
            correct += 1
        else:
            false_reject += 1
    for q in impostor:
        _, score = search(q)
        if score >= threshold:
            false_accept += 1
    n = len(genuine)
    return {
        "p50_ms": round(percentile(single, 50), 4),
        "p95_ms": round(percentile(single, 95), 4),
        "mean_ms": round(statistics.fmean(single), 4),
        "top1_accuracy": round(correct / n, 4),
        "false_reject_rate": round(false_reject / n, 4),
        "false_accept_rate": round(false_accept / len(impostor), 4),
    }


def bench_numpy(gallery, labels, genuine, truth, impostor, threshold):
    index = EmbeddingIndex(backend="numpy")
    t0 = time.perf_counter()
    index.build(list(zip(labels, gallery)), version=1, model="bench")
    build_ms = (time.perf_counter() - t0) * 1000

    def search(q):
        top = index.top_k(q, k=1)
        return (top[0].prn, top[0].score) if top else (None, -1.0)

    res = evaluate(search, genuine, truth, impostor, threshold)
    t0 = time.perf_counter()
    index.per_student_scores(genuine)  # batch = one group photo with many faces
    res["batch_qps"] = round(len(genuine) / (time.perf_counter() - t0), 1)
    res["build_ms"] = round(build_ms, 2)
    return res


def bench_faiss(gallery, labels, genuine, truth, impostor, threshold, kind):
    d = gallery.shape[1]
    t0 = time.perf_counter()
    if kind == "flat":
        index = faiss.IndexFlatIP(d)
    else:
        index = faiss.IndexHNSWFlat(d, 32, faiss.METRIC_INNER_PRODUCT)
        index.hnsw.efConstruction = 80
    index.add(gallery)
    if kind == "hnsw":
        index.hnsw.efSearch = 64
    build_ms = (time.perf_counter() - t0) * 1000
    labels_arr = np.array(labels)

    def search(q):
        scores, idx = index.search(q[None, :], 5)
        return (labels_arr[idx[0][0]], float(scores[0][0])) if idx[0][0] >= 0 else (None, -1.0)

    res = evaluate(search, genuine, truth, impostor, threshold)
    t0 = time.perf_counter()
    index.search(genuine, 5)
    res["batch_qps"] = round(len(genuine) / (time.perf_counter() - t0), 1)
    res["build_ms"] = round(build_ms, 2)
    return res


def threshold_sweep(gallery, labels, genuine, truth, impostor) -> list[dict]:
    index = EmbeddingIndex(backend="numpy")
    index.build(list(zip(labels, gallery)), version=1, model="bench")
    g_scores, g_labels = index.per_student_scores(genuine)
    i_scores, _ = index.per_student_scores(impostor)
    g_best = g_scores.max(axis=1)
    g_ok = np.array([g_labels[j] == t for j, t in zip(g_scores.argmax(axis=1), truth)])
    i_best = i_scores.max(axis=1)
    rows = []
    for t in np.arange(0.20, 0.725, 0.025):
        rows.append({"threshold": round(float(t), 3),
                     "false_reject_rate": round(float(np.mean(~(g_ok & (g_best >= t)))), 4),
                     "false_accept_rate": round(float(np.mean(i_best >= t)), 4)})
    return rows


def bench_engine(images_dir: Path) -> dict:
    import cv2

    from app.config import get_settings
    from app.face.engines import create_engine

    s = get_settings()
    engine = create_engine(s.face_engine, s.insightface_model, s.insightface_root, s.det_size)
    times, faces = [], 0
    for path in sorted(images_dir.glob("*")):
        img = cv2.imread(str(path))
        if img is None:
            continue
        t0 = time.perf_counter()
        found = engine.detect(img)
        times.append((time.perf_counter() - t0) * 1000)
        faces += len(found)
    return {"engine": engine.name, "images": len(times), "faces": faces,
            "p50_ms": round(percentile(times, 50), 1), "p95_ms": round(percentile(times, 95), 1)}


def plot(results: list[dict], sweep: list[dict], out_dir: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    files = []
    backends = sorted({r["backend"] for r in results})
    colours = {"numpy": "#2554C7", "faiss-flat": "#B06A04", "faiss-hnsw": "#C43228"}

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for b in backends:
        rows = [r for r in results if r["backend"] == b]
        ax.plot([r["embeddings"] for r in rows], [r["p50_ms"] for r in rows], marker="o", label=f"{b} p50",
                color=colours.get(b))
        ax.plot([r["embeddings"] for r in rows], [r["p95_ms"] for r in rows], marker=".", linestyle="--",
                color=colours.get(b), alpha=0.6, label=f"{b} p95")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Embeddings in gallery")
    ax.set_ylabel("Search latency per face (ms)")
    ax.set_title("1:N search latency")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = out_dir / "latency.png"
    fig.savefig(path, dpi=140)
    files.append(str(path))
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for b in backends:
        rows = [r for r in results if r["backend"] == b]
        ax.plot([r["embeddings"] for r in rows], [100 * r["top1_accuracy"] for r in rows], marker="o",
                label=f"{b} top-1 accuracy", color=colours.get(b))
        ax.plot([r["embeddings"] for r in rows], [100 * r["false_accept_rate"] for r in rows], marker="x",
                linestyle=":", label=f"{b} false accepts", color=colours.get(b))
    ax.set_xscale("log")
    ax.set_xlabel("Embeddings in gallery")
    ax.set_ylabel("%")
    ax.set_ylim(-2, 102)
    ax.set_title("Identification accuracy at the match threshold")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = out_dir / "accuracy.png"
    fig.savefig(path, dpi=140)
    files.append(str(path))
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4.2))
    ts = [r["threshold"] for r in sweep]
    ax.plot(ts, [100 * r["false_accept_rate"] for r in sweep], marker=".", color="#C43228", label="false accept (wrong person marked)")
    ax.plot(ts, [100 * r["false_reject_rate"] for r in sweep], marker=".", color="#2554C7", label="false reject (student missed)")
    ax.axvline(0.45, color="#586A62", linestyle="--", label="default threshold 0.45")
    ax.set_xlabel("Cosine similarity threshold")
    ax.set_ylabel("% of queries")
    ax.set_title("Choosing the threshold (largest gallery)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = out_dir / "threshold.png"
    fig.savefig(path, dpi=140)
    files.append(str(path))
    plt.close(fig)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 10000])
    parser.add_argument("--per-student", type=int, default=5)
    parser.add_argument("--queries", type=int, default=500)
    parser.add_argument("--threshold", type=float, default=0.45)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--difficulty", choices=list(DIFFICULTY), default="realistic")
    parser.add_argument("--out", type=Path, default=Path("benchmarks"))
    parser.add_argument("--images", type=Path, help="folder of real photos to time the face engine")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    results = []
    for n in args.sizes:
        gallery, labels, genuine, truth, impostor = make_dataset(n, args.per_student, args.queries, args.seed + n,
                                                                 args.difficulty)
        runs = [("numpy", lambda: bench_numpy(gallery, labels, genuine, truth, impostor, args.threshold))]
        if HAS_FAISS:
            runs.append(("faiss-flat", lambda: bench_faiss(gallery, labels, genuine, truth, impostor, args.threshold, "flat")))
            runs.append(("faiss-hnsw", lambda: bench_faiss(gallery, labels, genuine, truth, impostor, args.threshold, "hnsw")))
        for name, fn in runs:
            row = {"backend": name, "embeddings": n, "students": n // args.per_student, **fn()}
            results.append(row)
            print(f"{name:11s} N={n:>7d}  p50={row['p50_ms']:.3f}ms p95={row['p95_ms']:.3f}ms  "
                  f"acc={row['top1_accuracy']:.3f} FAR={row['false_accept_rate']:.3f} batch={row['batch_qps']:.0f} q/s")

    sweep = threshold_sweep(gallery, labels, genuine, truth, impostor)
    report = {"threshold": args.threshold, "queries": args.queries, "per_student": args.per_student,
              "difficulty": args.difficulty, "faiss_available": HAS_FAISS, "results": results, "threshold_sweep": sweep}
    if args.images:
        report["engine"] = bench_engine(args.images)
        print("engine:", report["engine"])
    (args.out / "results.json").write_text(json.dumps(report, indent=2))
    with open(args.out / "results.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    charts = plot(results, sweep, args.out)

    print("\n| backend | embeddings | p50 ms | p95 ms | top-1 acc | FAR | batch q/s |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for r in results:
        print(f"| {r['backend']} | {r['embeddings']} | {r['p50_ms']} | {r['p95_ms']} | {r['top1_accuracy']:.3f} | "
              f"{r['false_accept_rate']:.3f} | {r['batch_qps']} |")
    print(f"\nThreshold sweep at N={args.sizes[-1]} (numpy):")
    for r in sweep[::2]:
        print(f"  t={r['threshold']:.3f}  FAR={r['false_accept_rate']:.3f}  FRR={r['false_reject_rate']:.3f}")
    print("\nSaved:", ", ".join([str(args.out / "results.json"), str(args.out / "results.csv"), *charts]))


if __name__ == "__main__":
    main()
