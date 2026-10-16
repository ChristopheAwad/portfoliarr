#!/usr/bin/env python3
"""Render the Portfoliarr teaser: capture animation.html frame-by-frame with
Playwright, synthesize a soundtrack with numpy, and encode a 10 s mp4 with the
ffmpeg binary that ships inside imageio-ffmpeg."""

import math
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "animation.html")
FRAMES = os.path.join(HERE, "frames")
PREVIEW = os.path.join(HERE, "preview")
OUT = os.path.join(HERE, "portfoliarr-teaser.mp4")
AUDIO = os.path.join(HERE, "soundtrack.wav")

DURATION = 10.0
FPS = 30
W, H = 1920, 1080
SR = 48000

PREVIEW_TIMES = [0.7, 1.5, 2.35, 4.5, 5.6, 6.6, 7.4, 8.2, 9.5]


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


# --------------------------------------------------------------------------
# frames
# --------------------------------------------------------------------------
def capture(preview: bool) -> None:
    from playwright.sync_api import sync_playwright

    outdir = PREVIEW if preview else FRAMES
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)

    times = PREVIEW_TIMES if preview else [i / FPS for i in range(int(DURATION * FPS))]

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb",
                                          "--disable-lcd-text"])
        page = browser.new_page(viewport={"width": W, "height": H},
                                device_scale_factor=1)
        page.goto("file://" + HTML)
        page.wait_for_load_state("networkidle")
        try:
            page.wait_for_function("document.fonts.status === 'loaded'", timeout=15000)
        except Exception:
            pass
        try:
            page.evaluate("Promise.all(Array.from(document.images).map(i => i.decode().catch(()=>{})))")
        except Exception:
            pass
        page.wait_for_timeout(600)
        fonts = page.evaluate(
            "({fraunces: document.fonts.check('600 100px Fraunces'),"
            " sans: document.fonts.check('600 30px \"Instrument Sans\"')})")
        print("fonts loaded:", fonts)

        page.evaluate(
            "() => { document.querySelectorAll('.chip').forEach(c =>"
            " c.style.backdropFilter='none'); }")
        for idx, t in enumerate(times):
            page.evaluate("t => window.seek(t)", t)
            if preview:
                name = f"t{t:05.2f}.png"
                page.screenshot(path=os.path.join(outdir, name))
            else:
                name = f"f{idx:04d}.jpg"
                page.screenshot(path=os.path.join(outdir, name),
                                type="jpeg", quality=90)
            if idx % 60 == 0:
                print(f"  frame {idx}/{len(times)}  t={t:.2f}s", flush=True)
        browser.close()
    print(f"captured {len(times)} frames -> {outdir}")


# --------------------------------------------------------------------------
# soundtrack
# --------------------------------------------------------------------------
def synth_audio() -> None:
    n = int(DURATION * SR)
    t = np.arange(n) / SR
    mono = np.zeros(n)
    rng = np.random.default_rng(7)

    def add(sig, at):
        i = int(at * SR)
        j = min(n, i + len(sig))
        if i < n:
            mono[i:j] += sig[: j - i]

    def env(attack, decay, length):
        a = max(1, int(attack * SR))
        d = max(1, int(decay * SR))
        L = max(1, int(length * SR))
        e = np.zeros(L)
        ai = min(a, L)
        e[:ai] = np.linspace(0, 1, ai)
        di = min(d, L - ai)
        if di > 0:
            e[ai:ai + di] = np.exp(-np.linspace(0, 5, di))
        return e

    def lowpass(x, alpha):
        y = np.empty_like(x)
        acc = 0.0
        for i in range(len(x)):
            acc += alpha * (x[i] - acc)
            y[i] = acc
        return y

    # ---- kick ----
    beat = 0.5
    k = 0
    while k * beat < DURATION - 0.01:
        t0 = k * beat
        L = int(0.22 * SR)
        tt = np.arange(L) / SR
        f = 110 * np.exp(-tt * 22) + 47
        e = np.exp(-np.linspace(0, 6.2, L))
        kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * e
        acc = 0.55 if (k % 4 == 0) else 0.36
        add(kick * acc, t0)
        k += 1

    # ---- hats (eighths) ----
    for m in range(int(DURATION / 0.25)):
        t0 = m * 0.25
        L = int(0.045 * SR)
        noise = rng.standard_normal(L)
        noise = np.diff(noise, prepend=0)  # crude high-pass
        e = np.exp(-np.linspace(0, 9, L))
        amp = 0.05 if m % 2 == 0 else 0.03
        add(noise * e * amp, t0)

    # ---- pad chord progression ----
    def note(freq, dur, amp):
        L = int(dur * SR)
        tt = np.arange(L) / SR
        e = np.minimum(tt / 1.4, 1) * np.minimum((dur - tt) / 1.4, 1)
        e = np.clip(e, 0, 1)
        sig = (np.sin(2 * np.pi * freq * tt)
               + 0.5 * np.sin(2 * np.pi * freq * 1.005 * tt)
               + 0.25 * np.sin(2 * np.pi * freq * 2 * tt) * 0.4)
        return sig * e * amp

    chords = [
        (0.0, 2.6, [220.00, 261.63, 329.63, 392.00]),   # Am7
        (2.4, 2.8, [174.61, 220.00, 261.63, 349.23]),   # Fmaj
        (5.0, 2.8, [196.00, 246.94, 293.66, 392.00]),   # G
        (7.6, 2.4, [261.63, 329.63, 392.00, 523.25]),   # C
    ]
    for start, dur, freqs in chords:
        for f in freqs:
            add(note(f, dur, 0.028), start)

    # ---- risers ----
    def riser(start, dur, amp):
        L = int(dur * SR)
        tt = np.arange(L) / SR
        x = (np.sin(2 * np.pi * np.cumsum(np.linspace(180, 1400, L)) / SR)
             + 0.6 * rng.standard_normal(L))
        e = np.linspace(0, 1, L) ** 2
        add(x * e * amp, start)

    riser(1.35, 0.62, 0.20)   # into logo slam
    riser(8.15, 0.78, 0.18)   # into endcard

    # ---- whooshes on cuts ----
    def whoosh(at, amp=0.16):
        L = int(0.5 * SR)
        tt = np.arange(L) / SR
        x = rng.standard_normal(L)
        # moving lowpass: open then close
        cut = int(0.22 * SR)
        y = np.empty(L)
        acc = 0.0
        for i in range(L):
            a = 0.02 if i < cut else 0.02 + 0.9 * (1 - (i - cut) / max(1, L - cut))
            a = min(a, 0.98)
            acc += a * (x[i] - acc)
            y[i] = acc
        e = np.sin(np.linspace(0, math.pi, L))
        add(y * e * amp, at)

    for cut in (2.0, 3.42, 6.2, 7.0, 7.8, 8.95):
        whoosh(cut, 0.22 if cut in (2.0, 8.95) else 0.15)

    # ---- impacts ----
    def impact(at, amp):
        L = int(0.7 * SR)
        tt = np.arange(L) / SR
        f = 90 * np.exp(-tt * 9) + 38
        e = np.exp(-np.linspace(0, 4.5, L))
        add(np.sin(2 * np.pi * np.cumsum(f) / SR) * e * amp, at)

    impact(2.0, 0.5)
    impact(8.95, 0.45)

    # ---- mild soft-clip, global fades, normalize ----
    mono = np.tanh(mono * 1.1)
    fade = np.ones(n)
    fi = int(0.25 * SR)
    fade[:fi] = np.linspace(0, 1, fi)
    fo = int(0.9 * SR)
    fade[-fo:] = np.linspace(1, 0, fo)
    mono *= fade
    peak = np.max(np.abs(mono)) or 1.0
    mono = mono / peak * 0.78

    stereo = np.stack([mono, np.roll(mono, 8) * 0.999], axis=1)
    pcm = (stereo * 32767).astype(np.int16)
    with wave.open(AUDIO, "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print("wrote soundtrack:", AUDIO)


# --------------------------------------------------------------------------
# encode
# --------------------------------------------------------------------------
def encode() -> None:
    ff = ffmpeg_exe()
    cmd = [
        ff, "-y",
        "-framerate", str(FPS), "-i", os.path.join(FRAMES, "f%04d.jpg"),
        "-i", AUDIO,
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", OUT,
    ]
    print("encoding with", ff)
    subprocess.run(cmd, check=True)
    size = os.path.getsize(OUT) / 1e6
    print(f"done: {OUT}  ({size:.1f} MB)")


if __name__ == "__main__":
    args = set(sys.argv[1:])
    if "--preview" in args:
        capture(preview=True)
    else:
        if args and args <= {"--frames", "--audio", "--encode"}:
            if "--frames" in args:
                capture(preview=False)
            if "--audio" in args:
                synth_audio()
            if "--encode" in args:
                encode()
        else:
            capture(preview=False)
            synth_audio()
            encode()
