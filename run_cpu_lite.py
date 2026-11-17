"""Photo -> Illustration on CPU — TurboLite

Turn any photo into a beautiful cartoon/illustration in ~16 seconds on a
regular CPU. No GPU required, no cloud API, no subscription.

    python run_cpu_lite.py --input photo.jpg
    python run_cpu_lite.py --input folder_of_photos --out results --threads 6 --compare

Needs only: openvino, numpy, pillow.

For weights and commercial licensing visit https://www.thearifoffice.com
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    import openvino as ov
except ImportError:  # use the copy next to this folder if openvino is not installed
    sys.path.insert(0, os.path.join(HERE, "..", "_ov_lib"))
    import openvino as ov
import numpy as np
from PIL import Image, ImageOps

W = os.path.join(HERE, "weights")
EXTS = (".png", ".jpg", ".jpeg", ".webp")


def prepare(photo, long_side=1024):
    """Respect phone rotation, bring the longer side to `long_side`, make both sides a multiple of 8."""
    photo = ImageOps.exif_transpose(photo).convert("RGB")
    k = long_side / max(photo.size) if long_side else 1
    w, h = max(8, int(photo.width * k) // 8 * 8), max(8, int(photo.height * k) // 8 * 8)
    return photo.resize((w, h), Image.LANCZOS)


class LiteCartoonifier:
    """Load once, call on many photos. The model is prepared for each new
    picture size the first time that size is seen, then reused."""

    def __init__(self, threads=4, long_side=1024):
        self.core = ov.Core()
        self.cfg = {"INFERENCE_NUM_THREADS": threads, "PERFORMANCE_HINT": "LATENCY"}
        self.long_side = long_side
        self.cache = {}
        self.times = [0.0, 0.0, 0.0]

    def _models(self, H, Wd):
        if (H, Wd) not in self.cache:
            self.cache.clear()  # keep only one picture size in memory
            h, w = H // 8, Wd // 8
            e = self.core.read_model(os.path.join(W, "small_encoder.xml")); e.reshape([1, 3, H, Wd])
            u = self.core.read_model(os.path.join(W, "unet.xml")); u.reshape([1, 4, h, w])
            d = self.core.read_model(os.path.join(W, "small_decoder.xml")); d.reshape({0: [1, 4, h, w], 1: [1, 3, H, Wd]})
            self.cache[(H, Wd)] = tuple(self.core.compile_model(m, "CPU", self.cfg) for m in (e, u, d))
        return self.cache[(H, Wd)]

    def __call__(self, photo):
        photo = prepare(photo, self.long_side)
        x = (np.asarray(photo, np.float32) / 255).transpose(2, 0, 1)[None]
        E, U, D = self._models(*x.shape[2:])
        t0 = time.time(); z = E(x)[0]             # photo -> latent
        t1 = time.time(); z = U(z)[0]             # one diffusion step
        t2 = time.time(); y = D([z, x])[0]        # latent + photo -> picture
        self.times = [t1 - t0, t2 - t1, time.time() - t2]
        return Image.fromarray(((y[0].clip(-1, 1) + 1) * 127.5).transpose(1, 2, 0).round().astype(np.uint8))


def main():
    p = argparse.ArgumentParser(description="Turn photos into illustrations on CPU (light version).")
    p.add_argument("--input", required=True, help="one image file, or a folder of images")
    p.add_argument("--out", default="results", help="folder for the results")
    p.add_argument("--long_side", type=int, default=1024, help="longer side of the result in px. Smaller is faster")
    p.add_argument("--threads", type=int, default=4, help="CPU threads. Use the number of real cores for top speed")
    p.add_argument("--compare", action="store_true", help="also save photo and result side by side")
    opt = p.parse_args()
    os.makedirs(opt.out, exist_ok=True)
    c = LiteCartoonifier(opt.threads, opt.long_side)
    files = ([os.path.join(opt.input, f) for f in sorted(os.listdir(opt.input))]
             if os.path.isdir(opt.input) else [opt.input])
    files = [f for f in files if f.lower().endswith(EXTS)]
    if not files:
        raise SystemExit(f"No images found in {opt.input}")
    print(f"Running on CPU with OpenVINO, {opt.threads} threads", flush=True)
    for path in files:
        photo = Image.open(path)
        t = time.time()
        result = c(photo)
        dt = time.time() - t
        stem = os.path.splitext(os.path.basename(path))[0]
        result.save(os.path.join(opt.out, f"{stem}.jpg"), quality=93)
        if opt.compare:
            src = prepare(photo, opt.long_side)
            both = Image.new("RGB", (src.width * 2, src.height))
            both.paste(src, (0, 0)); both.paste(result, (src.width, 0))
            both.save(os.path.join(opt.out, f"{stem}_compare.jpg"), quality=90)
        e, u, d = c.times
        print(f"{stem}: {result.width}x{result.height}, {dt:.1f}s (encoder {e:.1f}, unet {u:.1f}, decoder {d:.1f})", flush=True)
    print(f"Done. {len(files)} photo(s) saved in {opt.out}")


if __name__ == "__main__":
    main()
