"""Quantum Supersampling (QSS) of the Mona Lisa — Programming Quantum Computers, Ch. 11.

本書の QSS を Qiskit のゲートレベル回路で実装し、512x512 の 1bit 画像を
4x4 タイル (128x128 = 16384 タイル) ごとに量子和推定して 128x128 画像を作る。

1 タイルの回路 (4 + t qubit):
  pos[0..3]   : サブピクセル位置 x = 4*qy + qx  (pos0,pos1 = qx, pos2,pos3 = qy)
  counter[t]  : Grover 反復回数を重ね合わせで持つレジスタ
  1. H on pos (白紙のキャンバス), H on counter
  2. counter[j] を制御に (O_f -> G) を 2^j 回      (O_f: 白サブピクセルの位相を π 反転)
                                                  (G: 本書 grover_iteration = H X MCZ X H)
  3. counter に逆 QFT -> 測定値 y
  4. ルックアップ表 P(y|k) で白の数 k を推定し、明るさ k/16 とする

制御付きにするとき、X/H による共役部分は制御 OFF なら打ち消し合うので
多制御 Z ゲートにだけ counter[j] の制御を足せばよい (本書 mask_with_condition と同じ考え方)。

出力: figures/ と results/ (metrics.json, 各推定画像)
"""
import argparse
import json
from pathlib import Path
from time import perf_counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import numpy as np
from PIL import Image
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit.library import QFTGate, ZGate
from qiskit.quantum_info import Operator, Statevector

ROOT = Path(__file__).resolve().parent.parent
TILE = 4
NPOS = 4                 # 位置 qubit 数 (4x4 = 16 サブピクセル)
NSUB = TILE * TILE


# ----------------------------------------------------------------------------
# 回路
# ----------------------------------------------------------------------------
def append_phase_flip(qc, pos, pattern, controls=()):
    """|pattern> (4bit) の位相だけを π 反転する。controls があれば制御付き。

    pattern のビットが 0 の qubit を X で挟み、多制御 Z で |1111> を反転する。
    """
    zeros = [pos[b] for b in range(NPOS) if not (pattern >> b) & 1]
    if zeros:
        qc.x(zeros)
    qc.append(ZGate().control(NPOS - 1 + len(controls)), [*controls, *pos])
    if zeros:
        qc.x(zeros)


def append_oracle(qc, pos, mask, controls=()):
    """位相オラクル O_f: 白サブピクセル (mask[qy, qx] = 1) の位相を反転 (= 本書の pixel shader)。"""
    for x in np.flatnonzero(mask.ravel()):
        append_phase_flip(qc, pos, int(x), controls)


def append_diffusion(qc, pos, controls=()):
    """本書 grover_iteration: H X (|0000> の位相反転) X H  = I - 2|s><s|。"""
    qc.h(pos)
    append_phase_flip(qc, pos, 0, controls)
    qc.h(pos)


def grover_step(mask, controlled=False, barrier=True):
    """1 回の Grover 反復 Q = (I - 2|s><s|) O_f を回路として返す (図・検証用)。"""
    pos = QuantumRegister(NPOS, "pos")
    regs = [pos]
    ctrl = ()
    if controlled:
        c = QuantumRegister(1, "c")
        regs = [c, pos]
        ctrl = (c[0],)
    qc = QuantumCircuit(*regs, name="Q")
    append_oracle(qc, pos, mask, ctrl)
    if barrier:
        qc.barrier()
    append_diffusion(qc, pos, ctrl)
    return qc


def qss_circuit(mask, t, measure=False):
    """1 タイルの QSS 回路 (ゲートレベル)。counter が上位 (後ろ) の qubit。"""
    pos = QuantumRegister(NPOS, "pos")
    cnt = QuantumRegister(t, "counter")
    qc = QuantumCircuit(pos, cnt, name="QSS tile")
    qc.h(pos)
    qc.h(cnt)
    for j in range(t):
        for _ in range(2 ** j):
            append_oracle(qc, pos, mask, (cnt[j],))
            append_diffusion(qc, pos, (cnt[j],))
    qc.append(QFTGate(t).inverse(), cnt)
    if measure:
        cr = ClassicalRegister(t, "y")
        qc.add_register(cr)
        qc.measure(cnt, cr)
    return qc


def counter_probs(mask, t):
    """counter の測定確率 P(y) を状態ベクトルで厳密に計算する。"""
    qc = qss_circuit(mask, t)
    sv = Statevector.from_instruction(qc)
    return sv.probabilities(qargs=list(range(NPOS, NPOS + t)))


def mask_with_k(k):
    return (np.arange(NSUB) < k).astype(np.uint8).reshape(TILE, TILE)


# ----------------------------------------------------------------------------
# ルックアップ表と検証
# ----------------------------------------------------------------------------
def build_lut(t):
    """本書 Example 11-5: 列 k (白の数 0..16) ごとの P(y|k)。shape (2^t, 17)。"""
    return np.stack([counter_probs(mask_with_k(k), t) for k in range(NSUB + 1)], axis=1)


def closed_form_lut(t):
    """P(y|k) = 1/2 [F_N(phi+ - y/N) + F_N(phi- - y/N)],  phi± = 1/2 ± theta/pi,  sin^2 theta = k/16
    (F_N: 正規化 Fejér 核)。k = 0, 16 でもそのまま成り立つ。"""
    n = 2 ** t
    y = np.arange(n) / n

    def fejer(d):
        s = np.sin(np.pi * d)
        small = np.abs(s) < 1e-12
        return np.where(small, 1.0, (np.sin(np.pi * n * d) / (n * np.where(small, 1.0, s))) ** 2)

    cols = []
    for k in range(NSUB + 1):
        th = np.arcsin(np.sqrt(k / NSUB))
        cols.append(0.5 * (fejer(0.5 + th / np.pi - y) + fejer(0.5 - th / np.pi - y)))
    return np.stack(cols, axis=1)


def expected_metrics(lut, k_img, n_calls):
    """画像の k の分布 w(k) から QSS / Monte Carlo の誤差の期待値を計算する。"""
    from scipy.stats import binom
    w = np.bincount(k_img.ravel(), minlength=NSUB + 1) / k_img.size
    k_hat = lut.argmax(axis=1)
    ks = np.arange(NSUB + 1)
    q_mae = sum(w[k] * lut[:, k] @ np.abs(k_hat - k) for k in ks) / NSUB
    q_z = sum(w[k] * lut[k_hat == k, k].sum() for k in ks)
    hits = np.arange(n_calls + 1)
    m_mae = m_z = 0.0
    for k in ks:
        pr = binom.pmf(hits, n_calls, k / NSUB)
        est = np.round(hits / n_calls * NSUB)
        m_mae += w[k] * pr @ np.abs(est - k) / NSUB
        m_z += w[k] * pr[est == k].sum()
    return {"qss": {"mean_abs_error": float(q_mae), "zero_error_fraction": float(q_z)},
            "monte_carlo_rounded": {"mean_abs_error": float(m_mae), "zero_error_fraction": float(m_z)},
            "decodable_levels": sorted(set(int(v) for v in k_hat))}


def verify(t, lut, tiles, rng, n_real=40):
    """(a) ゲートレベル Q が行列 (I-2|s><s|)O と一致, (b) 分布が k だけで決まる
    (位置を並べ替えた mask / 実画像のタイルで LUT と一致) ことを確かめる。"""
    out = {}
    mask = tiles[rng.integers(len(tiles))]
    s = np.full(NSUB, 0.25)
    expected = (np.eye(NSUB) - 2 * np.outer(s, s)) @ np.diag(1 - 2.0 * mask.ravel())
    out["grover_operator_max_abs_diff"] = float(np.abs(Operator(grover_step(mask)).data - expected).max())

    errs = []
    for k in range(NSUB + 1):
        m = rng.permutation(mask_with_k(k).ravel()).reshape(TILE, TILE)
        errs.append(np.abs(counter_probs(m, t) - lut[:, k]).max())
    out["permuted_masks_max_prob_diff"] = float(max(errs))

    uniq = {m.tobytes(): m for m in tiles}
    keys = list(uniq)
    pick = rng.choice(len(keys), size=min(n_real, len(keys)), replace=False)
    errs = []
    for i in pick:
        m = uniq[keys[i]]
        errs.append(np.abs(counter_probs(m, t) - lut[:, int(m.sum())]).max())
    out["real_tiles_checked"] = int(len(pick))
    out["real_tiles_max_prob_diff"] = float(max(errs))
    out["closed_form_max_prob_diff"] = float(np.abs(closed_form_lut(t) - lut).max())
    return out


# ----------------------------------------------------------------------------
# 画像全体
# ----------------------------------------------------------------------------
def to_tiles(bit):
    n = bit.shape[0] // TILE
    return bit.reshape(n, TILE, n, TILE).transpose(0, 2, 1, 3)  # (n, n, 4, 4)


def qss_image(k_img, lut, rng):
    """各タイルで 1 回だけ測定 (本書と同じ) し、LUT で k を復号する。

    回路の出力分布は k だけで決まる (verify で確認) ので、タイルごとの
    測定は LUT の列 P(y|k) からのサンプリングで等価に行える。"""
    k_hat_of_y = lut.argmax(axis=1)                       # 本書 qss_count_to_hits
    conf_of_y = lut.max(axis=1) / lut.sum(axis=1)         # 一様事前分布での事後確率
    cdf = np.cumsum(lut, axis=0)
    u = rng.random(k_img.shape)
    y = (u[None] > cdf[:, k_img]).sum(axis=0)
    y = np.minimum(y, lut.shape[0] - 1)
    return k_hat_of_y[y] / NSUB, conf_of_y[y], y


def monte_carlo_image(k_img, n_samples, rng):
    """従来の supersampling: タイル内のランダムなサブピクセルを n 回見て白の割合を数える。
    比較しやすいよう 1/16 刻み (17 階調) に丸める。"""
    hits = rng.binomial(n_samples, k_img / NSUB)
    raw = hits / n_samples
    return np.round(raw * NSUB) / NSUB, raw


def metrics(est, ideal):
    err = np.abs(est - ideal)
    return {"mean_abs_error": float(err.mean()),
            "zero_error_fraction": float((err < 1e-9).mean()),
            "max_abs_error": float(err.max())}


# ----------------------------------------------------------------------------
# 図
# ----------------------------------------------------------------------------
def save_img(a, path):
    Image.fromarray(np.rint(np.clip(a, 0, 1) * 255).astype(np.uint8)).save(path)


def fig_comparison(path, panels):
    n = len(panels)
    rows = 2 if any(p[2] is not None for p in panels) else 1
    fig, axes = plt.subplots(rows, n, figsize=(2.1 * n, 2.25 * rows), squeeze=False)
    for i, (img, title, err) in enumerate(panels):
        axes[0, i].imshow(img, cmap="gray" if img.ndim == 2 else None, vmin=0, vmax=1,
                          interpolation="nearest")
        axes[0, i].set_title(title, fontsize=10.5)
        axes[0, i].axis("off")
        if axes.shape[0] > 1:
            axes[1, i].axis("off")
            if err is not None:
                axes[1, i].imshow(err, cmap="magma", vmin=0, vmax=0.5, interpolation="nearest")
                axes[1, i].set_title("|error|", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def fig_grid(path, panels, ncols=3):
    """誤差マップなしの画像を ncols 列に並べる (段組の 1 カラム用)。"""
    nrows = -(-len(panels) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(2.3 * ncols, 2.45 * nrows), squeeze=False)
    for ax in axes.ravel():
        ax.axis("off")
    for ax, (img, title, _) in zip(axes.ravel(), panels):
        ax.imshow(img, interpolation="nearest")
        ax.set_title(title, fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def fig_lut(path, luts):
    fig, axes = plt.subplots(1, len(luts), figsize=(4.2 * len(luts), 3.8))
    for ax, (t, lut) in zip(np.atleast_1d(axes), luts):
        im = ax.imshow(lut, cmap="gray", aspect="auto", origin="upper", vmin=0, vmax=lut.max())
        ax.set_xlabel("white subpixels k in tile")
        ax.set_ylabel("readout y")
        ax.set_title(f"t = {t} counter qubits")
        ax.set_xticks(range(0, 17, 2))
        k_hat = lut.argmax(axis=1)
        ax.plot(k_hat, np.arange(lut.shape[0]), "o", ms=3, color="tab:red", label="decoded k")
        ax.legend(loc="lower right", fontsize=8)
        fig.colorbar(im, ax=ax, fraction=0.046, label="P(y|k)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_circle_notation(path, mask, origin):
    qc = QuantumCircuit(NPOS)
    qc.h(range(NPOS))
    append_oracle(qc, qc.qubits, mask)
    amp = Statevector.from_instruction(qc).data
    fig, ax = plt.subplots(figsize=(5, 5.4))
    for x, a in enumerate(amp):
        qy, qx = divmod(x, TILE)
        ph = np.angle(a)
        r = 0.4 * abs(a) / 0.25
        ax.add_patch(Circle((qx, -qy), 0.42, fill=False, ec="0.6"))
        ax.add_patch(Circle((qx, -qy), r, color="#6fa8dc"))
        ax.plot([qx, qx + r * np.sin(ph)], [-qy, -qy + r * np.cos(ph)], color="k", lw=2)
        ax.text(qx, -qy - 0.5, f"|{x}>", ha="center", fontsize=11)
    ax.set(xlim=(-0.6, 3.6), ylim=(-3.75, 0.6), aspect="equal")
    ax.axis("off")

    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def fig_circuits(fig_dir, mask, t):
    style = {"fontsize": 15, "subfontsize": 12}
    # (1) 全体: Q^(2^j) をまとめたブロックで描く
    pos = QuantumRegister(NPOS, "pos")
    cnt = QuantumRegister(t, "counter")
    cr = ClassicalRegister(t, "y")
    qc = QuantumCircuit(pos, cnt, cr)
    qc.h(pos)
    qc.h(cnt)
    qc.barrier()
    q_gate = grover_step(mask, barrier=False).to_gate()
    for j in range(t):
        g = q_gate.power(2 ** j)
        g.label = rf"$Q^{{{2 ** j}}}$"   # 描画用ラベル
        qc.append(g.control(1), [cnt[j], *pos])
    qc.barrier()
    iqft = QFTGate(t).inverse()
    iqft.label = r"QFT$^\dagger$"
    qc.append(iqft, cnt)
    qc.measure(cnt, cr)
    qc.draw("mpl", style=style).savefig(fig_dir / f"circuit_qss_overview_t{t}.png", dpi=170,
                                        bbox_inches="tight")
    # (2) 1 回の Grover 反復 (ゲートレベル, 制御なし / 制御付き)
    grover_step(mask).draw("mpl", style=style, fold=40).savefig(
        fig_dir / "circuit_grover_step.png", dpi=170, bbox_inches="tight")
    grover_step(mask, controlled=True).draw("mpl", style=style, fold=40).savefig(
        fig_dir / "circuit_grover_step_controlled.png", dpi=170, bbox_inches="tight")
    # (3) 逆 QFT の分解
    iq = QuantumCircuit(QuantumRegister(t, "c"))
    iq.append(QFTGate(t).inverse(), iq.qubits)
    iq.decompose(reps=1).draw("mpl", style={"fontsize": 15, "subfontsize": 13}, fold=10).savefig(
        fig_dir / f"circuit_inverse_qft_t{t}.png", dpi=170, bbox_inches="tight", pad_inches=0.35)
    plt.close("all")


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--counter-bits", type=int, nargs="+", default=[4, 6])
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    fig_dir = ROOT / "figures"
    res_dir = ROOT / "results"
    fig_dir.mkdir(exist_ok=True)
    res_dir.mkdir(exist_ok=True)
    data = np.load(ROOT / "data" / "mona_512.npz")
    tiles_gray = to_tiles(data["bit"])                                   # (128,128,4,4)
    k_gray = tiles_gray.sum(axis=(2, 3))
    k_rgb = np.stack([to_tiles(data["rgb_bits"][..., c]).sum(axis=(2, 3)) for c in range(3)], -1)
    ideal_gray = k_gray / NSUB
    ideal_rgb = k_rgb / NSUB
    flat_tiles = tiles_gray.reshape(-1, TILE, TILE)

    report = {"image": "data/mona_512.npz (512x512, Bayer 1bit)", "tiles": list(k_gray.shape),
              "tile_size": TILE, "seed": args.seed, "runs": {}}
    started = perf_counter()
    luts = []
    gray_panels = [(ideal_gray, "ideal k/16", None)]
    for t in args.counter_bits:
        t0 = perf_counter()
        lut = build_lut(t)
        luts.append((t, lut))
        np.save(res_dir / f"lut_t{t}.npy", lut)
        check = verify(t, lut, flat_tiles, rng)
        n_calls = 2 ** t - 1                       # 1 タイルあたりのオラクル (shader) 呼び出し回数
        q_gray, conf, _ = qss_image(k_gray, lut, rng)
        mc_gray, mc_raw = monte_carlo_image(k_gray, n_calls, rng)
        q_rgb = np.stack([qss_image(k_rgb[..., c], lut, rng)[0] for c in range(3)], -1)
        mc_rgb = np.stack([monte_carlo_image(k_rgb[..., c], n_calls, rng)[0] for c in range(3)], -1)

        save_img(q_gray, res_dir / f"qss_gray_t{t}.png")
        save_img(mc_gray, res_dir / f"mc_gray_n{n_calls}.png")
        save_img(q_rgb, res_dir / f"qss_rgb_t{t}.png")
        save_img(mc_rgb, res_dir / f"mc_rgb_n{n_calls}.png")
        save_img(conf, res_dir / f"confidence_t{t}.png")
        gray_panels += [(q_gray, f"QSS, t={t}", np.abs(q_gray - ideal_gray)),
                        (mc_gray, f"Monte Carlo, n={n_calls}", np.abs(mc_gray - ideal_gray))]

        # 信頼度マップ
        fig, ax = plt.subplots(1, 3, figsize=(9, 3.4))
        for a, img, title in [(ax[0], q_gray, f"QSS result (t={t})"),
                              (ax[1], conf, "confidence"),
                              (ax[2], (np.abs(q_gray - ideal_gray) < 1e-9).astype(float),
                               "actually correct (white)")]:
            a.imshow(img, cmap="gray", vmin=0, vmax=1, interpolation="nearest")
            a.set_title(title, fontsize=11)
            a.axis("off")
        fig.tight_layout()
        fig.savefig(fig_dir / f"confidence_t{t}.png", dpi=150)
        plt.close(fig)

        report["runs"][f"t={t}"] = {
            "qubits_per_tile_circuit": NPOS + t,
            "oracle_calls_per_tile": n_calls,
            "gate_count_example_tile": dict(qss_circuit(flat_tiles[len(flat_tiles) // 2], t)
                                            .decompose(reps=3).count_ops()),
            "verification": check,
            "expected_gray": expected_metrics(lut, k_gray, n_calls),
            "gray": {"qss": metrics(q_gray, ideal_gray), "monte_carlo_rounded": metrics(mc_gray, ideal_gray),
                     "monte_carlo_raw_mae": float(np.abs(mc_raw - ideal_gray).mean())},
            "rgb": {"qss": metrics(q_rgb, ideal_rgb), "monte_carlo_rounded": metrics(mc_rgb, ideal_rgb)},
            "corr_confidence_vs_correct": float(np.corrcoef(conf.ravel(),
                                                (np.abs(q_gray - ideal_gray) < 1e-9).ravel())[0, 1]),
            "seconds": perf_counter() - t0,
        }
        print(f"t={t}: done in {perf_counter() - t0:.1f}s", flush=True)

    save_img(ideal_gray, res_dir / "ideal_gray.png")
    save_img(ideal_rgb, res_dir / "ideal_rgb.png")
    fig_comparison(fig_dir / "comparison_gray.png", gray_panels)
    rgb_panels = [(data["rgb"], "512x512 input", None), (ideal_rgb, "ideal k/16", None)]
    for t in args.counter_bits:
        rgb_panels += [(np.asarray(Image.open(res_dir / f"qss_rgb_t{t}.png")) / 255, f"QSS, t={t}", None),
                       (np.asarray(Image.open(res_dir / f"mc_rgb_n{2 ** t - 1}.png")) / 255,
                        f"Monte Carlo, n={2 ** t - 1}", None)]
    fig_grid(fig_dir / "comparison_rgb.png", rgb_panels)
    fig_lut(fig_dir / "lookup_tables.png", luts)

    # 代表タイル (顔付近で k が中間のもの) の位相エンコードと回路図
    cand = np.argwhere((k_gray >= 5) & (k_gray <= 9))
    r, c = min(cand, key=lambda rc: np.hypot(rc[0] - 35, rc[1] - 64))
    fig_circle_notation(fig_dir / "circle_notation_tile.png", tiles_gray[r, c], (r, c))
    fig_circuits(fig_dir, tiles_gray[r, c], min(args.counter_bits))
    report["example_tile"] = {"tile_row": int(r), "tile_col": int(c),
                              "mask": tiles_gray[r, c].astype(int).tolist(), "k": int(k_gray[r, c])}
    report["total_seconds"] = perf_counter() - started
    (res_dir / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
