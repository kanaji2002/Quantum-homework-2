"""Step 1: shopping.webp (408x530) を 512x512 のピクセル格子に変換し、
QSS (Quantum Supersampling, 本書 11 章) の入力となる画像を用意する。

出力 (data/):
  mona_512_rgb.png      : 正方形にクロップして 512x512 にリサイズしたカラー画像
  mona_512_gray.png     : 同グレースケール
  mona_512_pad_rgb.png  : 参考) クロップせず余白を足して 512x512 にしたもの
  mona_512_1bit.png     : グレースケールを 4x4 Bayer ディザで 1bit 化 (白 = 位相 π)
  mona_512_rgb_1bit.png : R,G,B 各ビットプレーンを 1bit 化したもの (本書 "Adding Color")
  mona_512_fs_1bit.png  : 参考) Floyd-Steinberg 誤差拡散で 1bit 化したもの

Bayer 行列をタイル (4x4) に揃えて使うと、一様な濃さ v のタイルの白サブピクセル数が
k ≈ 16 v となり、「タイル内の白の数 = そのピクセルの明るさ」という QSS の前提がきれいに成り立つ。
  mona_512.npz          : 上記を numpy 配列でまとめたもの
出力 (figures/):
  step1_overview.png    : 元画像 / 512x512 / 1bit / 4x4 タイル分割の拡大図
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
N = 512          # 高解像度画像 (サブピクセル) の一辺
TILE = 4         # タイル一辺 (4x4 = 16 サブピクセル -> qx,qy 各 2 qubit)
CROP_TOP = 20    # 縦長画像を正方形に切るときの上端 (顔が切れないよう上寄り)


BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]])


def bayer(gray: np.ndarray) -> np.ndarray:
    """[0,1] の濃淡画像を 4x4 Bayer 閾値 (タイル境界に揃える) で 0/1 にする。"""
    h, w = gray.shape
    thr = np.tile((BAYER + 0.5) / 16, (h // TILE, w // TILE))
    return (gray >= thr).astype(np.uint8)


def floyd_steinberg(gray: np.ndarray) -> np.ndarray:
    """[0,1] の濃淡画像を 0/1 の 2 値画像にする (誤差拡散)。"""
    img = gray.astype(np.float64).copy()
    h, w = img.shape
    out = np.zeros_like(img, dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            old = img[y, x]
            new = 1.0 if old >= 0.5 else 0.0
            out[y, x] = int(new)
            err = old - new
            if x + 1 < w:
                img[y, x + 1] += err * 7 / 16
            if y + 1 < h:
                if x > 0:
                    img[y + 1, x - 1] += err * 3 / 16
                img[y + 1, x] += err * 5 / 16
                if x + 1 < w:
                    img[y + 1, x + 1] += err * 1 / 16
    return out


def main():
    src = Image.open(ROOT / "shopping.webp").convert("RGB")
    w, h = src.size  # 408 x 530

    # 1) 正方形クロップ -> 512x512
    side = min(w, h)
    crop = src.crop((0, CROP_TOP, side, CROP_TOP + side))
    rgb = crop.resize((N, N), Image.LANCZOS)

    # 参考: パディング版 (絵全体を残す)
    scale = N / max(w, h)
    fit = src.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    pad = Image.new("RGB", (N, N), (0, 0, 0))
    pad.paste(fit, ((N - fit.width) // 2, (N - fit.height) // 2))

    gray = rgb.convert("L")
    rgb_a = np.asarray(rgb, dtype=np.float64) / 255.0
    gray_a = np.asarray(gray, dtype=np.float64) / 255.0

    bit = bayer(gray_a)
    rgb_bits = np.stack([bayer(rgb_a[..., c]) for c in range(3)], axis=-1)
    fs_bit = floyd_steinberg(gray_a)

    d = ROOT / "data"
    rgb.save(d / "mona_512_rgb.png")
    gray.save(d / "mona_512_gray.png")
    pad.save(d / "mona_512_pad_rgb.png")
    Image.fromarray(bit * 255).save(d / "mona_512_1bit.png")
    Image.fromarray(rgb_bits * 255).save(d / "mona_512_rgb_1bit.png")
    Image.fromarray(fs_bit * 255).save(d / "mona_512_fs_1bit.png")
    np.savez_compressed(d / "mona_512.npz", rgb=rgb_a, gray=gray_a, bit=bit, rgb_bits=rgb_bits)

    # 2) 概要図: 元画像 / 512 / 1bit / タイル分割拡大
    panel = 384
    fig = Image.new("RGB", (panel * 4 + 50, panel + 40), "white")
    draw = ImageDraw.Draw(fig)
    items = [
        (src.resize((round(w * panel / h), panel)), "original 408x530"),
        (rgb.resize((panel, panel)), "512x512 RGB"),
        (Image.fromarray(bit * 255).resize((panel, panel), Image.NEAREST), "512x512 1-bit Bayer (white = phase pi)"),
    ]
    # 顔付近 32x32 サブピクセルを拡大し 4x4 タイル境界を描く
    y0, x0, z = 120, 220, 32
    zoom = Image.fromarray(bit[y0:y0 + z, x0:x0 + z] * 255).convert("RGB").resize((panel, panel), Image.NEAREST)
    zd = ImageDraw.Draw(zoom)
    step = panel // (z // TILE)
    for k in range(0, panel + 1, step):
        zd.line([(k, 0), (k, panel)], fill=(220, 30, 30), width=2)
        zd.line([(0, k), (panel, k)], fill=(220, 30, 30), width=2)
    items.append((zoom, f"zoom {z}x{z}: 4x4 tiles"))
    x = 10
    for im, label in items:
        fig.paste(im, (x, 30))
        draw.text((x, 8), label, fill="black")
        x += panel + 10
    fig.save(ROOT / "figures" / "step1_overview.png")

    n_tiles = (N // TILE) ** 2
    print(f"512x512 -> {N // TILE}x{N // TILE} = {n_tiles} tiles of {TILE}x{TILE}")
    print(f"white ratio (1bit): {bit.mean():.3f}, mean gray: {gray_a.mean():.3f}")
    # タイル内白サブピクセル数 k の分布 (QSS が推定する量)
    k = bit.reshape(N // TILE, TILE, N // TILE, TILE).sum(axis=(1, 3))
    print("k histogram (0..16):", np.bincount(k.ravel(), minlength=17).tolist())


if __name__ == "__main__":
    main()
