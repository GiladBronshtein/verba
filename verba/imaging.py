"""Screenshot processing: deterministic auto-crop and robust fingerprinting.

auto_crop() reproduces the cropping the legacy generators applied before
embedding, so a library file and its embedded copy compare byte-for-byte in
shape and near-zero in fingerprint distance.
"""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

CORNER = 60
MODAL_DARK = 80
BRIGHT = 200
WHITE = 245


def auto_crop_image(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    data = np.array(img)
    h, w = data.shape[:2]
    if h < CORNER * 2 or w < CORNER * 2:
        return img
    corners = [
        data[:CORNER, :CORNER], data[:CORNER, -CORNER:],
        data[-CORNER:, :CORNER], data[-CORNER:, -CORNER:],
    ]
    if all(np.mean(c) < MODAL_DARK for c in corners):
        gray = np.mean(data, axis=2)
        rows = np.where(np.max(gray, axis=1) > BRIGHT)[0]
        cols = np.where(np.max(gray, axis=0) > BRIGHT)[0]
        if len(rows) > 20 and len(cols) > 20:
            pad = 30
            return img.crop((max(0, int(cols[0]) - pad), max(0, int(rows[0]) - pad),
                             min(w, int(cols[-1]) + pad), min(h, int(rows[-1]) + pad)))
        return img
    non_white = np.where(~np.all(data > WHITE, axis=(1, 2)))[0]
    if len(non_white):
        return img.crop((0, 0, w, min(int(non_white[-1]) + 30, h)))
    return img


def auto_crop_to_temp(path: str | Path) -> str:
    img = auto_crop_image(Image.open(str(path)))
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp.name, "PNG")
    tmp.close()
    return tmp.name


def fingerprint(img: Image.Image, n: int = 48) -> np.ndarray:
    """Contrast-normalised low-res luminance grid. Discriminates screenshots
    that share large white regions, which a plain average hash cannot."""
    g = np.asarray(img.convert("L").resize((n, n), Image.BILINEAR), dtype=np.float64)
    g -= g.mean()
    s = g.std()
    return g / s if s > 1e-6 else g


def distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def fingerprint_file(path: str | Path, crop: bool = True) -> np.ndarray:
    img = Image.open(str(path))
    return fingerprint(auto_crop_image(img) if crop else img)


def fingerprint_blob(blob: bytes) -> np.ndarray:
    return fingerprint(Image.open(io.BytesIO(blob)))


def aspect(img: Image.Image) -> float:
    return img.size[0] / max(img.size[1], 1)


def crop_by_rect(img: Image.Image, rect) -> Image.Image:
    """Crop by per-edge inset percentages (left, top, right, bottom).

    Matches Word's srcRect semantics, so a crop authored in Word survives the
    round trip and can be re-cut against a freshly captured screenshot.
    """
    lum, t, r, b = [float(x) / 100.0 for x in rect]
    w, h = img.size
    box = (int(round(w * lum)), int(round(h * t)),
           int(round(w * (1 - r))), int(round(h * (1 - b))))
    if box[2] <= box[0] or box[3] <= box[1]:
        return img
    return img.crop(box)
