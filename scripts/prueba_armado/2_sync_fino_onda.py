"""Afina el desfase entre cámaras (ms) con audio filtrado a la voz, en tres tramos, para ver precisión y deriva.
Uso: python sync_fino.py <ref> <otra> <pista_otra> <desfase_grueso_s>"""
import subprocess, sys
import numpy as np

SR = 16000


def audio(ruta, pista=0):
    cmd = ["ffmpeg", "-v", "error", "-i", ruta, "-map", f"0:a:{pista}", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, dtype=np.float32).astype(np.float64)


def banda(x, lo=300, hi=3400):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X[(f < lo) | (f > hi)] = 0
    y = np.fft.irfft(X, len(x))
    return y / (y.std() + 1e-12)


def pico(a, b, max_lag_s):
    n = 1
    while n < len(a) + len(b):
        n *= 2
    cc = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n) / min(len(a), len(b))
    m = int(max_lag_s * SR)
    cc = np.concatenate((cc[-m:], cc[: m + 1]))
    i = int(np.argmax(cc))
    z = (cc[i] - cc.mean()) / (cc.std() + 1e-12)
    return (i - m) / SR, float(cc[i]), float(z)


ref, otra, pista, grueso = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
a, b = audio(ref), audio(otra, pista)
print(f"{otra.split(chr(92))[-1]} pista {pista} vs {ref.split(chr(92))[-1]}; desfase grueso {grueso:+.2f} s")
res = []
for ini in (120, len(a) / SR / 2 - 60, len(a) / SR - 300):
    ia, ib = int(ini * SR), int((ini - grueso) * SR)
    n = 120 * SR
    if ib < 0 or ib + n > len(b) or ia + n > len(a):
        continue
    l, c, z = pico(banda(a[ia: ia + n]), banda(b[ib: ib + n]), 0.6)
    res.append(grueso + l)
    print(f"  tramo en {ini/60:5.1f} min: desfase {grueso + l:+.4f} s  (ajuste {l*1000:+6.1f} ms, correlación {c:.2f}, z={z:.1f})")
if res:
    print(f"  deriva entre tramos: {(max(res) - min(res)) * 1000:.1f} ms  (un cuadro a 24 fps = 41.7 ms)")
