import subprocess, sys
import numpy as np

SR = 16000
HOP = 320  # 20 ms


def audio(ruta, pista=0):
    cmd = ["ffmpeg", "-v", "error", "-i", ruta, "-map", f"0:a:{pista}", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, dtype=np.float32)


def env(x):
    n = len(x) // HOP
    e = np.log1p(1000 * np.sqrt((x[: n * HOP].reshape(n, HOP) ** 2).mean(1)))
    return e - e.mean()


def xcorr_z(a, b, max_lag_s):
    n = 1
    while n < len(a) + len(b):
        n *= 2
    cc = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    m = int(max_lag_s * SR / HOP)
    cc = np.concatenate((cc[-m:], cc[: m + 1]))
    cc /= (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)
    i = int(np.argmax(cc))
    z = (cc[i] - cc.mean()) / (cc.std() + 1e-9)
    return (i - m) * HOP / SR, float(cc[i]), float(z)


ref, *otras = sys.argv[1:]
a = audio(ref)
print("niveles por minuto (dB RMS) de", ref.split("\\")[-1], [round(20 * np.log10(np.sqrt((a[i:i + 60 * SR] ** 2).mean()) + 1e-9)) for i in range(0, min(len(a), 10 * 60 * SR), 60 * SR)])
ea = env(a)
for o in otras:
    for p in range(2):
        try:
            b = audio(o, p)
        except Exception:
            continue
        if np.abs(b).max() < 1e-4:
            continue
        print(o.split("\\")[-1], "pista", p, "niveles dB", [round(20 * np.log10(np.sqrt((b[i:i + 60 * SR] ** 2).mean()) + 1e-9)) for i in range(0, min(len(b), 10 * 60 * SR), 60 * SR)])
        lag, r, z = xcorr_z(ea, env(b), 900)
        print(f"   envolvente: desfase {lag:+.2f} s, correlación {r:.2f}, z={z:.1f}  (z > 8 = pico claro)")
