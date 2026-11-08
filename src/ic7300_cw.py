#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CW Station for the Icom IC-7300  -  CW decoder, keyboard keyer and panadapter
CW Station voor de Icom IC-7300  -  CW-decoder, toetsenbord-keyer en panadapter

Copyright (c) 2026 Richard A. Hendriksen (PD3RAH)
Licensed under the MIT License - see LICENSE.

Not affiliated with or endorsed by Icom Inc. "Icom" and "IC-7300" are
trademarks of Icom Inc. and are used only to describe compatibility.

Requires / Vereist:  pip install pyserial sounddevice numpy
Run / Start:         python ic7300_cw.py
"""

import json
import math
import os
import queue
import threading
import time
import tkinter as tk
import re
import webbrowser
from tkinter import ttk, messagebox
import tkinter.font as tkfont

import numpy as np

try:
    import serial
except ImportError:
    serial = None
try:
    import sounddevice as sd
except (ImportError, OSError):
    sd = None

# ----------------------------------------------------------------- settings / instellingen
APP_NAME = "CW Station"
APP_VERSION = "2.3.0"
SURVEY_URL = "https://www.pd3rah.nl/cwstation/enquete.php"
REPO_URL = "https://github.com/PD3RAH/cw-station"
RELEASE_API = "https://api.github.com/repos/PD3RAH/cw-station/releases/latest"
RADIOS = {0x94: "IC-7300", 0xB6: "IC-7300MK2"}     # standaard CI-V-adressen
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "CWStation")
CONFIG_FILE = os.path.join(DATA_DIR, "settings.json")
LOG_FILE = os.path.join(DATA_DIR, "logbook.adi")
OLD_CONFIGS = [os.path.join(APP_DIR, "ic7300_cw.json"),                      # vorige versies
               os.path.join(os.environ.get("LOCALAPPDATA", ""), "IC7300CW", "ic7300_cw.json"),
               r"C:\IC7300CW\ic7300_cw.json"]
DEFAULT_CONFIG = {
    "port": "COM4",
    "baud": 115200,
    "civ_addr": "auto",
    "mycall": "",
    "myname": "",
    "myqth": "",
    "audio_device": "",
    "wpm": 20,
    "lang": "nl",
    "theme": "Amber",
    "cq_repeat": 8,
    "check_updates": True,
    "macros": {
        "F1": ["CQ", "CQ CQ CQ DE {MYCALL} {MYCALL} {MYCALL} K"],
        "F2": ["Call", "{CALL} DE {MYCALL} {MYCALL} K"],
        "F3": ["Report", "{CALL} DE {MYCALL} TNX FER CALL UR RST {RST} {RST} NAME {MYNAME} QTH {MYQTH} HW? {CALL} DE {MYCALL} K"],
        "F4": ["73", "{CALL} TNX FER QSO 73 <SK> {CALL} DE {MYCALL} TU E E"],
        "F5": ["QRZ?", "QRZ? DE {MYCALL} K"],
        "F6": ["My call", "{MYCALL}"],
        "F7": ["AGN?", "AGN? AGN?"],
        "F8": ["TU", "TU 73 E E"],
    },
}

CTRL_ADDR = 0xE0
MODES = {0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CW", 0x04: "RTTY",
         0x05: "FM", 0x07: "CW-R", 0x08: "RTTY-R"}
BANDS = [("160", 1830000), ("80", 3530000), ("40", 7020000), ("30", 10110000),
         ("20", 14030000), ("17", 18080000), ("15", 21030000), ("12", 24900000),
         ("10", 28030000), ("6", 50090000)]
BAND_RANGES = {"160": (1.8e6, 2.0e6), "80": (3.5e6, 3.8e6), "40": (7.0e6, 7.2e6),
               "30": (10.1e6, 10.15e6), "20": (14.0e6, 14.35e6), "17": (18.068e6, 18.168e6),
               "15": (21.0e6, 21.45e6), "12": (24.89e6, 24.99e6), "10": (28.0e6, 29.7e6),
               "6": (50.0e6, 52.0e6)}

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "/": "-..-.", "-": "-....-",
    "=": "-...-", "+": ".-.-.", ":": "---...", "'": ".----.", "(": "-.--.",
    ")": "-.--.-", '"': ".-..-.", "@": ".--.-.",
}
DECODE = {v: k for k, v in MORSE.items()}
DECODE.update({"...-.-": "<SK>", "-.--.": "<KN>", ".-...": "<AS>",
               "........": "<HH>", "-.-.-": "<KA>", "...-.": "<SN>"})
PROSIGNS = {"<AR>": "^AR", "<SK>": "^SK", "<KN>": "^KN", "<BT>": "^BT",
            "<AS>": "^AS", "<HH>": "^HH"}
TX_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/?.-,:'()=+\"@ ^")


# ----------------------------------------------------------------- BCD helpers
def bcd_byte(b):
    return (b >> 4) * 10 + (b & 0x0F)


def bcd_le_to_int(data):
    val, mult = 0, 1
    for b in data:
        val += bcd_byte(b) * mult
        mult *= 100
    return val


def int_to_bcd_le(v, n):
    out = []
    for _ in range(n):
        two = v % 100
        v //= 100
        out.append(((two // 10) << 4) | (two % 10))
    return bytes(out)


def int_to_bcd_be(v, n):
    return int_to_bcd_le(v, n)[::-1]


# ----------------------------------------------------------------- CI-V
class CIV:
    """Seriële CI-V verbinding met frame-parser in een eigen thread."""

    def __init__(self, port, baud, addr, on_frame):
        # DTR/RTS laag houden: de IC-7300 kan deze lijnen gebruiken voor
        # USB SEND (PTT) en USB Keying (CW). pyserial zet ze standaard hoog,
        # waardoor de radio meteen gaat zenden.
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = baud
        self.ser.timeout = 0.05
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        self.ser.dtr = False
        self.ser.rts = False
        self.addr = addr
        self.on_frame = on_frame
        self.lock = threading.Lock()
        self.running = True
        self.buf = bytearray()
        threading.Thread(target=self._reader, daemon=True).start()

    def send(self, cmd, data=b""):
        self.send_to(self.addr, cmd, data)

    def send_to(self, addr, cmd, data=b""):
        frame = bytes([0xFE, 0xFE, addr, CTRL_ADDR, cmd]) + bytes(data) + b"\xFD"
        with self.lock:
            self.ser.write(frame)

    def close(self):
        self.running = False
        time.sleep(0.1)
        try:
            self.ser.close()
        except Exception:
            pass

    def _reader(self):
        while self.running:
            try:
                chunk = self.ser.read(2048)
            except Exception:
                break
            if not chunk:
                continue
            self.buf += chunk
            while True:
                start = self.buf.find(b"\xFE\xFE")
                if start < 0:
                    keep = self.buf[-1:] if self.buf[-1:] == b"\xFE" else b""
                    self.buf = bytearray(keep)
                    break
                end = self.buf.find(b"\xFD", start)
                if end < 0:
                    if start > 0:
                        del self.buf[:start]
                    break
                payload = bytes(self.buf[start + 2:end])
                del self.buf[:end + 1]
                while payload[:1] == b"\xFE":
                    payload = payload[1:]
                if len(payload) < 3:
                    continue
                to, frm, cmd, data = payload[0], payload[1], payload[2], payload[3:]
                if frm == CTRL_ADDR:            # echo van eigen commando
                    continue
                if to not in (CTRL_ADDR, 0x00):
                    continue
                try:
                    self.on_frame(cmd, data, frm)
                except Exception as e:
                    print("frame-fout:", e)


# ----------------------------------------------------------------- CW decoder
def fir_lowpass(n, fc, fs):
    """Linear-fase FIR laagdoorlaat (windowed sinc, Blackman)."""
    n = int(n) | 1
    k = np.arange(n) - (n - 1) / 2
    h = np.sinc(2 * fc / fs * k) * np.blackman(n)
    return (h / h.sum()).astype(np.float32)


class CWDecoder:
    """
    Twee-traps FIR-filter (anti-alias + smal kanaalfilter) op het complexe
    basisband-signaal, adaptieve drempel met ruis/piek-tracking, en
    adaptieve timing met aparte schattingen voor punt, streep,
    element-, letter- en woordspatie (werkt ook met Farnsworth en
    handseinen/bug met afwijkende verhoudingen).
    """

    FS2 = 2000.0        # tussen-samplerate na decimatie
    ENV_DEC = 4         # envelope-stap = 4 / 2000 = 2 ms

    def __init__(self, fs, on_text, tone=600.0, bw=100.0, wpm=20):
        self.fs = fs
        self.on_text = on_text
        self.D = max(1, int(round(fs / self.FS2)))
        self.fs2 = fs / self.D
        self.dt = self.ENV_DEC / self.fs2
        self.h1 = fir_lowpass(int(4.5 * fs / 700), 330, fs)
        self.st1 = np.zeros(len(self.h1) - 1, dtype=np.complex64)
        self.ph1 = 0                      # decimatie-fase
        self.phase = 0.0
        self.set_tone(tone)
        self.auto_bw = False
        self.bw = None
        self.set_bw(bw)
        self.envbuf = np.zeros(0, dtype=np.float32)
        self.squelch = 2.3
        self.noise = 1e-6
        self.peak = 1e-6
        self.warm = 0
        self.state = False
        self.count = 0
        self.pend = 0
        dit = 1.2 / wpm
        self.dot, self.dash = dit, 3 * dit
        self.ie, self.cg, self.wg = dit, 3 * dit, 7 * dit
        self.code = ""
        self.word_done = True
        self.marks = []
        self.gaps = []
        self.pdecay = 0.001
        self.pend_space = None
        self.saved_count = 0
        self.msm = 0.0
        self.bmin = float("inf")
        self.bcnt = 0
        self.mins = []
        self.markmax = 0.0
        self.muted = False
        self.level = 0.0

    # ---- instellingen
    def set_tone(self, f):
        self.tone = float(f)
        self.w = 2 * math.pi * self.tone / self.fs

    def set_bw(self, bw):
        if isinstance(bw, str) and bw.lower().startswith("auto"):
            self.auto_bw = True
            bw = self._auto_bw_value()
        else:
            self.auto_bw = False
        bw = float(min(max(bw, 25.0), 600.0))
        if self.bw is not None and abs(bw - self.bw) / self.bw < 0.12:
            return
        self.bw = bw
        n = min(int(11 * self.fs2 / bw), 801)
        self.h2 = fir_lowpass(n, bw / 2, self.fs2)
        self.st2 = np.zeros(len(self.h2) - 1, dtype=np.complex64)

    def _auto_bw_value(self):
        d = getattr(self, "dot", 0.06)
        return min(max(3.5 / d, 40.0), 120.0)

    @property
    def dit(self):
        return 0.5 * (self.dot + self.dash / 3.0)

    @property
    def wpm(self):
        return 1.2 / self.dit

    # ---- signaalverwerking
    def process(self, x):
        n = len(x)
        if n == 0:
            return
        t = np.arange(n)
        ph = self.phase + self.w * t
        bb = (x * np.cos(ph) - 1j * (x * np.sin(ph))).astype(np.complex64)
        self.phase = (self.phase + self.w * n) % (2 * math.pi)
        # trap 1: anti-alias FIR + decimatie naar ~2 kHz
        buf = np.concatenate([self.st1, bb])
        self.st1 = buf[-(len(self.h1) - 1):]
        y = np.convolve(buf, self.h1, mode="valid")          # lengte n
        idx = np.arange(self.ph1, len(y), self.D)
        self.ph1 = (idx[-1] + self.D - len(y)) if len(idx) else self.ph1 - len(y)
        y = y[idx]
        if len(y) == 0:
            return
        # trap 2: smal kanaalfilter
        buf = np.concatenate([self.st2, y])
        self.st2 = buf[-(len(self.h2) - 1):]
        z = np.convolve(buf, self.h2, mode="valid")
        env = np.concatenate([self.envbuf, np.abs(z).astype(np.float32)])
        m = (len(env) // self.ENV_DEC) * self.ENV_DEC
        self.envbuf = env[m:]
        for v in env[:m].reshape(-1, self.ENV_DEC).mean(axis=1):
            self._env(float(v))
        if self.auto_bw:
            self.set_bw(self._auto_bw_value())

    def _env(self, mag):
        # piek: langzaam verval; snelle stijging alleen tijdens een geldig teken
        if mag > self.peak:
            self.peak += 0.06 * (mag - self.peak)
        else:
            self.peak -= self.pdecay * (self.peak - self.noise)
        if not self.state:
            self.noise += (0.05 if self.warm < 150 else 0.004) * (mag - self.noise)
        # minimum-statistiek: ruisschatting nooit ver boven het recente minimum
        # (herstelt snel als de decoder midden in een teken is gestart)
        self.msm += 0.1 * (mag - self.msm)
        self.bmin = min(self.bmin, self.msm)
        self.bcnt += 1
        if self.bcnt >= 100:
            self.mins = (self.mins + [self.bmin])[-10:]
            self.bmin, self.bcnt = float("inf"), 0
        if self.mins and self.warm > 150:
            self.noise = min(self.noise, 2.0 * min(min(self.mins), self.bmin))
        self.warm += 1
        if self.peak < self.noise:
            self.peak = self.noise
        span = self.peak - self.noise
        hi = self.noise + 0.5 * span
        lo = self.noise + 0.32 * span
        self.level = mag / (hi + 1e-12)
        sig_ok = self.peak > self.noise * self.squelch
        raw = sig_ok and ((mag > hi) if not self.state else (mag > lo))
        if self.muted:
            raw = False

        # adaptieve debounce: korte gaten in een element overbruggen (QSB/ruis),
        # korte ruispieken in een pauze negeren
        frac = 0.4 if self.state else 0.25
        need = int(min(max(round(frac * self.dot / self.dt), 2), 20))
        if raw != self.state:
            self.pend += 1
            if self.pend >= need:
                dur = self.count * self.dt
                if self.state:
                    if self._valid_mark(dur):
                        if self.pend_space is not None:
                            self._space(self.pend_space)
                        self._mark(dur)
                        self.state = False
                        self.count = self.pend
                    else:
                        # klik/ruispiek: terugvouwen in de lopende spatie
                        self.state = False
                        self.count = self.saved_count + self.count + self.pend
                    self.pend_space = None
                else:
                    self.pend_space = dur
                    self.saved_count = self.count
                    self.state = True
                    self.markmax = 0.0
                    self.count = self.pend
                self.pend = 0
        else:
            self.count += 1 + self.pend
            self.pend = 0

        if not self.state:
            sil = self.count * self.dt
            if self.code and sil > self._thr_char():
                self._flush()
            if not self.word_done and sil > self._thr_word():
                self.on_text(" ")
                self.word_done = True

    def _valid_mark(self, dur):
        return max(0.008, 0.3 * self.dot) <= dur <= 1.5 or dur > 1.5

    # ---- timing
    def _thr_char(self):
        return math.sqrt(self.ie * self.cg)

    def _thr_word(self):
        return math.sqrt(self.cg * self.wg)

    def _mark(self, dur):
        if dur > 1.5:                      # draaggolf / afstemmen
            self.code = ""
            return
        self.marks.append(dur)
        self.marks = self.marks[-24:]
        self.nmarks = getattr(self, "nmarks", 0) + 1
        if len(self.marks) >= 4:
            p10, p90 = np.percentile(self.marks, [10, 90])
            if p90 / max(p10, 1e-3) > 1.8:
                g = 0.6 if self.nmarks < 25 else 0.3
                split = math.sqrt(p10 * p90)
                arr = np.array(self.marks)
                d1, d2 = arr[arr < split], arr[arr >= split]
                if len(d1) and len(d2):
                    self.dot += g * (d1.mean() - self.dot)
                    self.dash += g * (d2.mean() - self.dash)
        thr = math.sqrt(self.dot * self.dash)
        if dur < thr:
            self.code += "."
            self.dot += 0.15 * (dur - self.dot)
        else:
            self.code += "-"
            self.dash += 0.15 * (dur - self.dash)
        # verhoudingen binnen redelijke grenzen houden
        self.dot = min(max(self.dot, 0.018), 0.25)
        self.dash = min(max(self.dash, 2.0 * self.dot), 4.5 * self.dot)
        if len(self.code) > 9:
            self.code = ""

    def _space(self, dur):
        if dur < 0.3 * self.dot or dur > 4.0:
            return
        if dur < self._thr_char():
            self.ie += 0.15 * (dur - self.ie)
        else:
            self.gaps.append(dur)
            self.gaps = self.gaps[-30:]
            if len(self.gaps) >= 8:
                arr = np.array(self.gaps)
                p15, p90 = np.percentile(arr, [15, 90])
                if p90 / p15 > 1.7:            # letter- en woordspaties te onderscheiden
                    split = math.sqrt(p15 * p90)
                    self.cg += 0.3 * (arr[arr < split].mean() - self.cg)
                    self.wg += 0.3 * (arr[arr >= split].mean() - self.wg)
                else:                           # alleen letterspaties gezien
                    self.cg += 0.3 * (np.median(arr) - self.cg)
            if dur < self._thr_word():
                self.cg += 0.1 * (dur - self.cg)
            else:
                self.wg += 0.1 * (dur - self.wg)
        self.ie = min(max(self.ie, 0.5 * self.dot), 2.0 * self.dot)
        self.cg = min(max(self.cg, 1.8 * self.ie, 2.0 * self.dot), 15 * self.dot)
        self.wg = min(max(self.wg, 1.6 * self.cg), 40 * self.dot)

    def _flush(self):
        self.on_text(DECODE.get(self.code, "*"))
        self.code = ""
        self.word_done = False


# ----------------------------------------------------------------- audio
class AudioEngine:
    FFT = 4096

    def __init__(self, device, on_wf_row, decoder_factory, skimmer_factory=None):
        info = sd.query_devices(device, "input")
        fs = 48000
        try:
            sd.check_input_settings(device=device, samplerate=fs, channels=1)
        except Exception:
            fs = int(info["default_samplerate"])
        self.fs = fs
        self.decoder = decoder_factory(fs)
        self.skimmer = skimmer_factory(fs) if skimmer_factory else None
        self.on_wf_row = on_wf_row
        self.q = queue.Queue(maxsize=200)
        self.hop = fs // 20
        self.buf = np.zeros(0, dtype=np.float32)
        self.win = np.hanning(self.FFT).astype(np.float32)
        self.running = True
        self.level_db = -200.0
        self.blocks = 0
        self.error = None
        self.stream = sd.InputStream(device=device, channels=1, samplerate=fs,
                                     blocksize=fs // 100, dtype="float32",
                                     callback=self._cb)
        threading.Thread(target=self._worker, daemon=True).start()
        self.stream.start()

    def _cb(self, indata, frames, t, status):
        try:
            self.q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def _worker(self):
        since = 0
        while self.running:
            try:
                blk = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                rms = float(np.sqrt(np.mean(blk.astype(np.float64) ** 2)))
                self.level_db = 20 * math.log10(rms) if rms > 1e-9 else -200.0
                self.blocks += 1
                self.decoder.process(blk)
                if self.skimmer is not None:
                    self.skimmer.process(blk)
                self.buf = np.concatenate([self.buf, blk])[-self.FFT:]
                since += len(blk)
                if since >= self.hop and len(self.buf) == self.FFT:
                    since = 0
                    spec = np.abs(np.fft.rfft(self.buf * self.win))
                    if self.skimmer is not None:
                        self.skimmer.spectrum(spec)
                    self.on_wf_row(spec, self.fs)
            except Exception as e:                      # nooit stilletjes stoppen
                self.error = f"{type(e).__name__}: {e}"
                log_error("audio", e)

    def close(self):
        self.running = False
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass


# ----------------------------------------------------------------- skimmer
CALL_RE = re.compile(r"\b(?:[A-Z]{1,2}|[0-9][A-Z]|[A-Z][0-9])[0-9]{1,2}[A-Z]{1,4}(?:/[A-Z0-9]{1,4})?\b")
NOT_CALLS = {"5NN", "599", "579", "73", "TU"}


def find_calls(text):
    """Roepnamen in een stuk tekst; voorkeur voor het woord na 'DE'."""
    words = text.split()
    out = []
    for i, w in enumerate(words):
        if CALL_RE.fullmatch(w) and w not in NOT_CALLS:
            out.append((w, i > 0 and words[i - 1] == "DE"))
    return out


class Skimmer:
    """Decodeert tot MAXCH CW-signalen tegelijk in de audio-doorlaat."""

    MAXCH = 8

    def __init__(self, fs, fmin=150, fmax=2900):
        self.fs = fs
        self.fmin, self.fmax = fmin, fmax
        self.ch = {}
        self.nextid = 1
        self.hold = None
        self.enabled = True
        self.lock = threading.Lock()
        self.t_audio = 0.0

    def _new_dec(self, tone, c):
        def on_text(t, c=c):
            c["text"] = (c["text"] + t)[-400:]
            c["last"] = time.time()
        d = CWDecoder(self.fs, on_text, tone=tone, bw="auto", wpm=20)
        return d

    def process(self, blk):
        if not self.enabled:
            return
        self.t_audio += len(blk) / self.fs
        with self.lock:
            chans = list(self.ch.values())
        for c in chans:
            c["dec"].process(blk)

    def spectrum(self, spec):
        if not self.enabled:
            return
        p = 20 * np.log10(spec + 1e-9)
        if self.hold is None or len(self.hold) != len(p):
            self.hold = p.copy()
        self.hold = np.maximum(self.hold - 0.15, p)          # piekhouden, ~3 dB/s verval
        binhz = self.fs / AudioEngine.FFT
        lo, hi = int(self.fmin / binhz), int(self.fmax / binhz)
        seg = self.hold[lo:hi]
        floor = np.median(seg)
        m = (seg[1:-1] > seg[:-2]) & (seg[1:-1] >= seg[2:]) & (seg[1:-1] > floor + 13)
        idx = np.flatnonzero(m) + 1
        idx = idx[np.argsort(-seg[idx])]
        peaks = []
        for i in idx:
            a, b, c3 = seg[i - 1], seg[i], seg[i + 1]
            den = a - 2 * b + c3
            off = 0.5 * (a - c3) / den if den else 0.0
            f = (lo + i + off) * binhz
            if all(abs(f - q) > 60 for q, _ in peaks):
                peaks.append((f, b - floor))
            if len(peaks) >= self.MAXCH:
                break
        now = self.t_audio
        with self.lock:
            for f, lvl in peaks:
                best = None
                for c in self.ch.values():
                    if abs(c["tone"] - f) < 35 and (best is None or abs(c["tone"] - f) < abs(best["tone"] - f)):
                        best = c
                if best is not None:
                    best["seen"] = now
                    best["snr"] = lvl
                    if abs(best["tone"] - f) > 3:
                        best["tone"] += 0.2 * (f - best["tone"])
                        best["dec"].set_tone(best["tone"])
                elif len(self.ch) < self.MAXCH:
                    c = {"id": self.nextid, "tone": f, "text": "", "seen": now, "last": 0.0,
                         "snr": lvl, "created": now}
                    c["dec"] = self._new_dec(f, c)
                    self.ch[self.nextid] = c
                    self.nextid += 1
            cur_floor = np.median(p[lo:hi])
            for c in self.ch.values():
                k = int(round(c["tone"] / binhz))
                if p[max(k - 1, 0):k + 2].max() > cur_floor + 10:
                    c["active"] = now
                c["dec"].muted = now - c.get("active", now) > 1.5   # stil: geen ruis decoderen
            for k in [k for k, c in self.ch.items() if now - c["seen"] > 20]:
                del self.ch[k]

    def snapshot(self):
        with self.lock:
            return [dict(id=c["id"], tone=c["tone"], text=c["text"], wpm=c["dec"].wpm,
                         snr=c["snr"], last=c["last"]) for c in self.ch.values()]


# ----------------------------------------------------------------- hulpfuncties: foutlog en http
def log_error(where, exc):
    try:
        import traceback
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, "error.log"), "a", encoding="utf-8") as f:
            f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {where} (v{APP_VERSION})\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:] + "\n")
    except Exception:
        pass


def _winhttp_get(url, timeout=8, headers=""):
    """HTTP(S) GET via Windows WinHTTP (gebruikt de TLS en proxy-instellingen van Windows)."""
    import ctypes
    from ctypes import wintypes
    from urllib.parse import urlsplit
    w = ctypes.WinDLL("winhttp")
    H = ctypes.c_void_p
    w.WinHttpOpen.restype = H
    w.WinHttpOpen.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    w.WinHttpConnect.restype = H
    w.WinHttpConnect.argtypes = [H, wintypes.LPCWSTR, wintypes.WORD, wintypes.DWORD]
    w.WinHttpOpenRequest.restype = H
    w.WinHttpOpenRequest.argtypes = [H, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                     ctypes.c_void_p, wintypes.DWORD]
    w.WinHttpSendRequest.argtypes = [H, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                     wintypes.DWORD, ctypes.c_size_t]
    w.WinHttpReceiveResponse.argtypes = [H, ctypes.c_void_p]
    w.WinHttpQueryDataAvailable.argtypes = [H, ctypes.POINTER(wintypes.DWORD)]
    w.WinHttpReadData.argtypes = [H, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    w.WinHttpQueryHeaders.argtypes = [H, wintypes.DWORD, wintypes.LPCWSTR, ctypes.c_void_p,
                                      ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    w.WinHttpSetTimeouts.argtypes = [H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    w.WinHttpCloseHandle.argtypes = [H]
    u = urlsplit(url)
    secure = u.scheme == "https"
    port = u.port or (443 if secure else 80)
    path = (u.path or "/") + (("?" + u.query) if u.query else "")
    agent = f"CWStation/{APP_VERSION}"
    hs = w.WinHttpOpen(agent, 4, None, None, 0) or w.WinHttpOpen(agent, 0, None, None, 0)
    hc = hr = None
    try:
        if not hs:
            raise OSError("WinHttpOpen failed")
        ms = int(timeout * 1000)
        w.WinHttpSetTimeouts(hs, ms, ms, ms, ms)
        hc = w.WinHttpConnect(hs, u.hostname, port, 0)
        hr = w.WinHttpOpenRequest(hc, "GET", path, None, None, None, 0x00800000 if secure else 0)
        if not hr:
            raise OSError("WinHttpOpenRequest failed")
        if not w.WinHttpSendRequest(hr, headers or None, 0xFFFFFFFF if headers else 0, None, 0, 0, 0):
            raise OSError(f"WinHttpSendRequest failed ({ctypes.GetLastError()})")
        if not w.WinHttpReceiveResponse(hr, None):
            raise OSError(f"WinHttpReceiveResponse failed ({ctypes.GetLastError()})")
        code, size = wintypes.DWORD(0), wintypes.DWORD(4)
        w.WinHttpQueryHeaders(hr, 19 | 0x20000000, None, ctypes.byref(code), ctypes.byref(size), None)
        data = b""
        while True:
            n = wintypes.DWORD(0)
            if not w.WinHttpQueryDataAvailable(hr, ctypes.byref(n)) or n.value == 0:
                break
            buf = ctypes.create_string_buffer(n.value)
            got = wintypes.DWORD(0)
            w.WinHttpReadData(hr, buf, n.value, ctypes.byref(got))
            data += buf.raw[:got.value]
        if code.value and code.value >= 400:
            raise OSError(f"HTTP {code.value}")
        return data
    finally:
        for hnd in (hr, hc, hs):
            if hnd:
                w.WinHttpCloseHandle(hnd)


def http_get(url, timeout=8):
    hdr = "Accept: application/vnd.github+json\r\n"
    try:
        import ssl  # noqa: F401  (niet aanwezig in de gebundelde runtime)
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": f"CWStation/{APP_VERSION}",
                                                   "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except ImportError:
        return _winhttp_get(url, timeout, hdr)


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


# ----------------------------------------------------------------- CW zender
def tx_clean(text):
    t = text.upper()
    for k, v in PROSIGNS.items():
        t = t.replace(k, v)
    return "".join(c for c in t if c in TX_ALLOWED)


def morse_units(text):
    units, join = 0, 0
    for ch in text:
        if ch == "^":
            join = 2
            continue
        if ch == " ":
            units += 4
            continue
        code = MORSE.get(ch, "")
        units += sum(1 if e == "." else 3 for e in code) + max(len(code) - 1, 0)
        if join == 2:
            units += 1          # aaneengesloten prosign
        else:
            units += 3
        join = max(join - 1, 0)
    return units


def chunks30(text):
    out, cur = [], ""
    for word in text.split(" "):
        if not word:
            continue
        while len(word) > 30:
            if cur:
                out.append(cur)
                cur = ""
            out.append(word[:30])
            word = word[30:]
        cand = (cur + " " + word) if cur else word
        if len(cand) <= 29:
            cur = cand
        else:
            out.append(cur + " ")
            cur = word
    if cur:
        out.append(cur + " ")
    return out


class CWSender:
    def __init__(self, app):
        self.app = app
        self.q = queue.Queue()
        self.abort = threading.Event()
        self.busy = False
        threading.Thread(target=self._run, daemon=True).start()

    def enqueue(self, text):
        t = tx_clean(text)
        if t.strip():
            self.q.put(t)

    def stop(self):
        self.abort.set()
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
        civ = self.app.civ
        if civ:
            civ.send(0x17, b"\xFF")
            civ.send(0x1C, b"\x00\x00")

    def _run(self):
        while True:
            text = self.q.get()
            self.abort.clear()
            for chunk in chunks30(text):
                civ = self.app.civ
                if civ is None or self.abort.is_set():
                    break
                self.busy = True
                self.app.gq.put(("tx", chunk))
                civ.send(0x17, chunk.encode("ascii"))
                dur = morse_units(chunk) * 1.2 / self.app.wpm_var.get() * 1.05 + 0.08
                t_end = time.time() + dur
                while time.time() < t_end and not self.abort.is_set():
                    time.sleep(0.02)
            if self.q.empty():
                self.busy = False
                self.app.gq.put(("txdone", None))


# ----------------------------------------------------------------- waterval-widget
def make_lut():
    pts = [(0.0, (0, 0, 0)), (0.2, (0, 0, 120)), (0.4, (0, 120, 220)),
           (0.6, (0, 220, 120)), (0.75, (240, 230, 0)), (0.9, (255, 60, 0)),
           (1.0, (255, 255, 255))]
    lut = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        x = i / 255
        for (x0, c0), (x1, c1) in zip(pts, pts[1:]):
            if x0 <= x <= x1:
                f = (x - x0) / (x1 - x0)
                lut[i] = [int(c0[k] + f * (c1[k] - c0[k])) for k in range(3)]
                break
    return lut


LUT = make_lut()


class Waterfall:
    def __init__(self, parent, hs, hw, on_click=None, label_fn=None):
        self.hs, self.hw = hs, hw
        self.width = 900
        self.canvas = tk.Canvas(parent, bg="#030a10", height=hs + hw, width=self.width,
                                highlightthickness=0, cursor="crosshair")
        self.arr = np.zeros((hw, self.width, 3), dtype=np.uint8)
        self.row = None
        self.dirty = False
        self.photo = None
        self.img_id = None
        self.markers = []       # (frac, kleur, breedte_frac)
        self.labels = []        # (frac, tekst, kleur)
        self.label_fn = label_fn
        self.on_click = on_click
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<Button-1>", self._click)

    def _resize(self, ev):
        w = max(100, ev.width)
        if w != self.width:
            self.width = w
            self.arr = np.zeros((self.hw, w, 3), dtype=np.uint8)
            self.dirty = True

    def _click(self, ev):
        if self.on_click:
            self.on_click(min(max(ev.x / self.width, 0.0), 1.0))

    def add_row(self, vals):
        vals = np.asarray(vals, dtype=np.float32)
        if len(vals) < 2:
            return
        row = np.interp(np.linspace(0, len(vals) - 1, self.width),
                        np.arange(len(vals)), vals)
        row = np.clip(row, 0, 1)
        self.arr[1:] = self.arr[:-1]
        self.arr[0] = LUT[(row * 255).astype(np.uint8)]
        self.row = row
        self.dirty = True

    def render(self):
        if not self.dirty:
            return
        self.dirty = False
        c = self.canvas
        h, w = self.arr.shape[:2]
        self.photo = tk.PhotoImage(data=b"P6 %d %d 255 " % (w, h) + self.arr.tobytes(), format="PPM")
        if self.img_id is None:
            self.img_id = c.create_image(0, self.hs, anchor="nw", image=self.photo)
        else:
            c.itemconfig(self.img_id, image=self.photo)
        c.delete("ov")
        # schaal
        if self.label_fn:
            for i in range(1, 10):
                x = self.width * i / 10
                c.create_line(x, 0, x, self.hs, fill=_mix(C["scr"], C["border"], 0.6), tags="ov")
                c.create_text(x + 3, 3, anchor="nw", text=self.label_fn(i / 10),
                              fill=C["dim"], font=("Consolas", 8), tags="ov")
        # spectrum: gevulde vorm + lijn
        if self.row is not None:
            step = max(1, self.width // 600)
            xs = np.arange(0, self.width, step)
            ys = self.hs - 2 - self.row[xs] * (self.hs - 16)
            pts = np.column_stack([xs, ys]).ravel().tolist()
            if len(pts) >= 4:
                c.create_polygon([0, self.hs] + pts + [xs[-1], self.hs],
                                 fill=_mix(C["scr"], C["acc"], 0.18), outline="", tags="ov")
                c.create_line(*pts, fill=C["acc"], width=1, tags="ov")
        for frac, color, wfrac in self.markers:
            x = frac * self.width
            if wfrac:
                wx = wfrac * self.width / 2
                c.create_rectangle(x - wx, 0, x + wx, self.hs, outline="",
                                   fill=color, stipple="gray25", tags="ov")
            c.create_line(x, 0, x, self.hs + self.hw, fill=color, tags="ov")
        for frac, text, color in self.labels:
            x = frac * self.width
            tid = c.create_text(x + 4, self.hs + 4, anchor="nw", text=text, fill="#ffffff",
                                font=("Segoe UI", 8, "bold"), tags="ov")
            bb = c.bbox(tid)
            if bb:
                r = c.create_rectangle(bb[0] - 3, bb[1] - 1, bb[2] + 3, bb[3] + 1, fill=color,
                                       outline="", tags="ov")
                c.tag_lower(r, tid)
                c.create_line(x, self.hs, x, self.hs + 4, fill=color, tags="ov")


# ----------------------------------------------------------------- thema & widgets
C = dict(bg="#07121b", panel="#0c1d2b", panel2="#10283b", border="#1a3d55", btn="#132e45",
         btnhi="#1b4160", acc="#ffb02e", acc2="#5cc8ff", text="#d8edf6", dim="#6f93a8",
         red="#ff4d5e", amber="#ff9f43", green="#4be38a", scr="#030a10")
THEMES = {
    "Amber":     dict(acc="#ffb02e", acc2="#5cc8ff"),
    "Turquoise": dict(acc="#2ee6d6", acc2="#ffb43c"),
    "Green":     dict(acc="#63e68a", acc2="#ffb43c"),
    "Ice blue":  dict(acc="#5cb8ff", acc2="#ffb43c"),
    "Copper":    dict(acc="#ff8a4c", acc2="#7fd6ff"),
    "Purple":    dict(acc="#b78cff", acc2="#ffc35c"),
}
THEME_NL = {"Amber": "Amber", "Turquoise": "Turquoise", "Green": "Groen", "Ice blue": "IJsblauw",
            "Copper": "Koper", "Purple": "Paars"}
UI = "Segoe UI"
MONO = "Consolas"
DIGIT = "Bahnschrift"


def _mix(c1, c2, f):
    f = min(max(f, 0.0), 1.0)
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(x + (y - x) * f):02x}" for x, y in zip(a, b))


def trace(widget, var, cb):
    """Variabele volgen; trace wordt opgeruimd als de widget verdwijnt."""
    tid = var.trace_add("write", lambda *a: cb())

    def _rm(ev):
        if ev.widget is widget:
            try:
                var.trace_remove("write", tid)
            except tk.TclError:
                pass
    widget.bind("<Destroy>", _rm, add="+")


def panel(parent, title=None):
    """Kaart met dunne rand; geeft (frame, body, kop) terug."""
    f = tk.Frame(parent, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
    head = None
    if title is not None:
        head = tk.Frame(f, bg=C["panel"])
        head.pack(fill="x", padx=12, pady=(8, 0))
        tk.Frame(head, bg=C["acc"], width=3, height=12).pack(side="left", padx=(0, 7))
        lbl = tk.Label(head, text=title, bg=C["panel"], fg=C["dim"], font=(UI, 9, "bold"))
        lbl.pack(side="left")
        head.title = lbl
    body = tk.Frame(f, bg=C["panel"])
    body.pack(fill="both", expand=True, padx=12, pady=6)
    return f, body, head


def label(parent, text="", fg=None, font=None, bg=None, **kw):
    return tk.Label(parent, text=text, bg=bg or parent.cget("bg"), fg=fg or C["dim"],
                    font=font or (UI, 9), **kw)


def entry(parent, var, width=8, font=None):
    return tk.Entry(parent, textvariable=var, width=width, bg=C["panel2"], fg=C["text"],
                    insertbackground=C["acc"], relief="flat", font=font or (UI, 10),
                    highlightthickness=1, highlightbackground=C["border"], highlightcolor=C["acc"])


class FlatButton(tk.Canvas):
    """Afgeronde knop (canvas). Optioneel gekoppeld aan een BooleanVar (toggle)."""

    def __init__(self, parent, text, command=None, var=None, width=None, font=None,
                 accent=None, padx=12, pady=5, radius=8):
        self.font = tkfont.Font(font=font or (UI, 10, "bold"))
        self._text = text
        self.padx, self.pady, self.radius = padx, pady, radius
        self.minw = (width or 0) * self.font.measure("0")
        w, h = self._size()
        super().__init__(parent, width=w, height=h, bg=parent.cget("bg"),
                         highlightthickness=0, cursor="hand2")
        self.command = command
        self.var = var
        self.accent = accent or C["acc"]
        self.active = False
        self.hover = False
        self.fg_override = None
        self.bind("<Enter>", lambda e: self._h(True))
        self.bind("<Leave>", lambda e: self._h(False))
        self.bind("<Button-1>", self._click)
        self.bind("<Configure>", lambda e: self._paint())
        if var is not None:
            trace(self, var, lambda: self.set_active(bool(var.get())))
            self.active = bool(var.get())
        self._paint()

    def _size(self):
        return (max(self.font.measure(self._text) + 2 * self.padx, self.minw),
                self.font.metrics("linespace") + 2 * self.pady)

    def config(self, cnf=None, **kw):
        if "text" in kw:
            self._text = kw.pop("text")
            w, h = self._size()
            kw.setdefault("width", w)
        if "fg" in kw:
            self.fg_override = kw.pop("fg")
        if kw:
            super().config(cnf, **kw)
        self._paint()
    configure = config

    def _h(self, on):
        self.hover = on
        self._paint()

    def _click(self, ev):
        if self.var is not None:
            self.var.set(not self.var.get())
        if self.command:
            self.command()

    def set_active(self, on, accent=None):
        self.active = bool(on)
        if accent:
            self.accent = accent
        self._paint()

    def _paint(self):
        try:
            w, h = self.winfo_width(), self.winfo_height()
        except tk.TclError:
            return
        if w <= 1:
            w, h = self._size()
        self.delete("all")
        r = min(self.radius, h / 2)
        if self.active:
            bg, fg, ol = self.accent, "#03131b", self.accent
        else:
            bg = C["btnhi"] if self.hover else C["btn"]
            fg = self.fg_override or C["text"]
            ol = _mix(C["border"], C["acc"], 0.35) if self.hover else C["border"]
        x1, y1, x2, y2 = 1, 1, w - 1, h - 1
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        self.create_polygon(pts, smooth=True, fill=bg, outline=ol)
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=self.font)


class Slider(tk.Canvas):
    def __init__(self, parent, var, lo, hi, command=None, width=200, height=22):
        super().__init__(parent, width=width, height=height, bg=parent.cget("bg"),
                         highlightthickness=0, cursor="hand2")
        self.var, self.lo, self.hi, self.command = var, lo, hi, command
        self.w, self.h = width, height
        self.bind("<Button-1>", self._set)
        self.bind("<B1-Motion>", self._set)
        self.bind("<ButtonRelease-1>", lambda e: self.command and self.command(True))
        self.bind("<MouseWheel>", lambda e: self._step(1 if e.delta > 0 else -1))
        self.bind("<Configure>", lambda e: self._resize(e.width))
        trace(self, var, self.draw)
        self.draw()

    def _resize(self, w):
        self.w = w
        self.draw()

    def _set(self, ev):
        f = min(max((ev.x - 8) / max(self.w - 16, 1), 0), 1)
        self.var.set(round(self.lo + f * (self.hi - self.lo), 2))
        if self.command:
            self.command(False)

    def _step(self, d):
        v = self.var.get() + d * (self.hi - self.lo) / 50
        self.var.set(round(min(max(v, self.lo), self.hi), 2))
        if self.command:
            self.command(True)

    def draw(self):
        self.delete("all")
        try:
            v = float(self.var.get())
        except (ValueError, tk.TclError):
            return
        f = (v - self.lo) / (self.hi - self.lo)
        y = self.h // 2
        x = 8 + f * (self.w - 16)
        self.create_line(8, y, self.w - 8, y, fill=C["btn"], width=4, capstyle="round")
        self.create_line(8, y, x, y, fill=C["acc"], width=4, capstyle="round")
        self.create_oval(x - 7, y - 7, x + 7, y + 7, fill=C["text"], outline=C["acc"], width=2)


class Knob(tk.Canvas):
    """VFO-knop met rubberen kartelrand, vingerkuil en geborstelde kap."""

    RIDGES = 64

    def __init__(self, parent, size, on_step):
        super().__init__(parent, width=size, height=size, bg=C["panel"],
                         highlightthickness=0, cursor="hand2")
        self.size, self.on_step = size, on_step
        self.angle = 90.0
        self.acc_deg = 0.0
        self.last = None
        c = size / 2
        R = c - 3
        self.c = c
        for i in range(40):
            a = math.radians(i * 9)
            big = i % 5 == 0
            d = 2.2 if big else 1.2
            x, y = c + (R - 1) * math.cos(a), c - (R - 1) * math.sin(a)
            self.create_oval(x - d, y - d, x + d, y + d, outline="",
                             fill=C["acc"] if big else C["dim"])
        self.Rk = R - 10
        self.Rs = self.Rk - 11
        self.Rc = self.Rs - 7
        self.create_oval(c - self.Rk + 4, c - self.Rk + 6, c + self.Rk + 4, c + self.Rk + 6,
                         fill="#02070b", outline="")
        self.create_oval(c - self.Rk - 2, c - self.Rk - 2, c + self.Rk + 2, c + self.Rk + 2,
                         outline=_mix(C["acc"], C["panel"], 0.45), width=2)
        self.create_oval(c - self.Rk, c - self.Rk, c + self.Rk, c + self.Rk, fill="#16191c", outline="#000")
        for k in range(8):
            r = self.Rs - k
            self.create_oval(c - r, c - r, c + r, c + r, outline="", fill=_mix("#1e2328", "#2b3238", k / 8))
        for k in range(26):
            r = self.Rc - k * self.Rc / 26
            g = 0.25 + 0.5 * (0.5 + 0.5 * math.sin(k * 1.7)) * 0.25 + 0.35 * (k / 26)
            self.create_oval(c - r, c - r, c + r, c + r, outline="", fill=_mix("#3a434b", "#8d98a2", g))
        self.create_arc(c - self.Rc + 6, c - self.Rc + 6, c + self.Rc - 6, c + self.Rc - 6,
                        start=100, extent=70, style="arc", outline="#c9d2d9", width=2)
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<MouseWheel>", lambda e: self._turn(1 if e.delta > 0 else -1))
        self.bind("<Button-4>", lambda e: self._turn(1))
        self.bind("<Button-5>", lambda e: self._turn(-1))
        self._draw_rot()

    def _draw_rot(self):
        self.delete("rot")
        c, Rk, Rs, Rc = self.c, self.Rk, self.Rs, self.Rc
        n = self.RIDGES
        for i in range(n):
            a0 = math.radians(self.angle + i * 360 / n)
            a1 = a0 + math.radians(360 / n * 0.55)
            light = 0.5 + 0.5 * math.cos(a0 - math.radians(135))
            col = _mix("#1b1f23", "#59626b", light * 0.9)
            pts = []
            for a, r in ((a0, Rk - 1), (a1, Rk - 1), (a1, Rs + 1), (a0, Rs + 1)):
                pts += [c + r * math.cos(a), c - r * math.sin(a)]
            self.create_polygon(pts, fill=col, outline="", tags="rot")
        a = math.radians(self.angle + 200)
        rd = Rc * 0.30
        dx, dy = c + Rc * 0.50 * math.cos(a), c - Rc * 0.50 * math.sin(a)
        self.create_oval(dx - rd, dy - rd, dx + rd, dy + rd, fill="#2a3138", outline="#1a1f24", width=2, tags="rot")
        self.create_oval(dx - rd * .75, dy - rd * .75 + 2, dx + rd * .75, dy + rd * .75 + 2, fill="#4a545d",
                         outline="", tags="rot")
        self.create_oval(dx - rd * .7, dy - rd * .7, dx + rd * .7, dy + rd * .7, fill="#373f46", outline="", tags="rot")
        a = math.radians(self.angle)
        r1, r2 = Rc - 4, Rc - 16
        self.create_line(c + r1 * math.cos(a), c - r1 * math.sin(a), c + r2 * math.cos(a), c - r2 * math.sin(a),
                         fill=C["acc"], width=4, capstyle="round", tags="rot")

    def _ang(self, ev):
        return math.degrees(math.atan2(self.c - ev.y, ev.x - self.c))

    def _press(self, ev):
        self.last = self._ang(ev)

    def _drag(self, ev):
        a = self._ang(ev)
        d = a - self.last
        if d > 180:
            d -= 360
        if d < -180:
            d += 360
        self.last = a
        self.acc_deg += -d
        while abs(self.acc_deg) >= 10:
            s = 1 if self.acc_deg > 0 else -1
            self.acc_deg -= 10 * s
            self._turn(s)

    def _turn(self, s):
        self.angle -= 10 * s
        self._draw_rot()
        self.on_step(s)


class BarMeter(tk.Canvas):
    """Digitale staafmeters (PO, SWR, ALC, Id) met piekwaarde en getal."""

    ROWS = [("PO", 0, 100, (25, 50, 75, 100), "W"),
            ("SWR", 1.0, 3.0, (1.5, 2.0, 2.5, 3.0), ""),
            ("ALC", 0, 120, (60, 120), ""),
            ("Id", 0, 25, (5, 10, 15, 20, 25), "A")]

    def __init__(self, parent, w=360):
        self.rh = 21
        super().__init__(parent, width=w, height=self.rh * len(self.ROWS) + 4,
                         bg=_mix(C["scr"], C["panel"], 0.5), highlightthickness=0)
        self.w = w
        self.vals = {r[0]: None for r in self.ROWS}
        self.peak = {r[0]: 0.0 for r in self.ROWS}
        self.x0, self.x1 = 44, w - 74
        for i, (name, lo, hi, ticks, unit) in enumerate(self.ROWS):
            y = 4 + i * self.rh
            self.create_text(10, y + 11, text=name, anchor="w", fill=C["acc"], font=(UI, 9, "bold"))
            self.create_rectangle(self.x0, y + 5, self.x1, y + 17, fill=C["scr"], outline=C["border"])
            for tk_ in ticks:
                x = self.x0 + (tk_ - lo) / (hi - lo) * (self.x1 - self.x0)
                self.create_line(x, y + 17, x, y + 21, fill=C["dim"])


    def set(self, name, v):
        self.vals[name] = v

    def draw(self):
        self.delete("dyn")
        for i, (name, lo, hi, ticks, unit) in enumerate(self.ROWS):
            y = 4 + i * self.rh
            v = self.vals[name]
            pk = self.peak[name]
            if v is not None:
                pk = max(v, pk - (hi - lo) * 0.01)
            else:
                pk = max(lo, pk - (hi - lo) * 0.03)
            self.peak[name] = pk
            if v is not None:
                f = min(max((v - lo) / (hi - lo), 0), 1)
                col = C["acc"]
                if name == "SWR" and v >= 2.0:
                    col = C["red"]
                elif name == "SWR" and v >= 1.5:
                    col = C["amber"]
                elif name == "ALC" and v > 120 * 0.9:
                    col = C["red"]
                self.create_rectangle(self.x0 + 1, y + 6, self.x0 + 1 + f * (self.x1 - self.x0 - 2), y + 16,
                                      fill=col, outline="", tags="dyn")
            fp = min(max((pk - lo) / (hi - lo), 0), 1)
            if fp > 0.005:
                xp = self.x0 + fp * (self.x1 - self.x0)
                self.create_line(xp, y + 5, xp, y + 17, fill="#ffffff", width=2, tags="dyn")
            if v is None:
                txt = "--"
            elif name == "SWR":
                txt = f"{v:.1f}"
            elif name == "ALC":
                txt = f"{v / 1.2:.0f}%"
            elif name == "Id":
                txt = f"{v:.1f} A"
            else:
                txt = f"{v:.0f} {unit}"
            self.create_text(self.w - 10, y + 11, text=txt, anchor="e", fill=C["text"],
                             font=(DIGIT, 12, "bold"), tags="dyn")


def _interp(v, pts):
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if v <= x1:
            return y0 + (v - x0) * (y1 - y0) / (x1 - x0)
    return pts[-1][1]


# kalibratie volgens de CI-V-referentie van de IC-7300 (waarden bij benadering)
def po_from_raw(v):        # 15 11: 0000=0%, 0143=50%, 0213=100%  (100 W)
    return _interp(v, [(0, 0.0), (143, 50.0), (213, 100.0), (255, 120.0)])


def id_from_raw(v):        # 15 16: 0000=0A, 0097=10A, 0146=15A, 0241=25A
    return _interp(v, [(0, 0.0), (97, 10.0), (146, 15.0), (241, 25.0), (255, 26.5)])


def vd_from_raw(v):        # 15 15: 0000=0V, 0013=10V, 0241=16V
    return _interp(v, [(0, 0.0), (13, 10.0), (241, 16.0), (255, 16.4)])


class SMeter(tk.Canvas):
    def __init__(self, parent, w=360, h=160, title="SIGNAL"):
        super().__init__(parent, width=w, height=h, bg=_mix(C["scr"], C["panel"], 0.5), highlightthickness=0)
        self.w, self.h = w, h
        self.cx, self.cy, self.r = w / 2, h - 10, min(w / 2 - 40, h - 20)
        self.val = 0.0
        self.target = 0.0
        self.title = title
        self._static()

    def _xy(self, raw, r):
        a = math.radians(150 - min(max(raw, 0), 241) / 241 * 120)
        return self.cx + r * math.cos(a), self.cy - r * math.sin(a)

    def _static(self):
        r = self.r
        for raw in range(0, 241, 3):
            x1, y1 = self._xy(raw, r)
            x2, y2 = self._xy(raw + 3, r)
            col = _mix(C["dim"], C["acc"], raw / 120) if raw < 120 else _mix("#ff7a4d", C["red"], (raw - 120) / 121)
            self.create_line(x1, y1, x2, y2, fill=col, width=5)
        marks = [(i * 120 / 9, str(i)) for i in (1, 3, 5, 7, 9)] + [(160, "+20"), (201, "+40"), (241, "+60")]
        for raw, t in marks:
            x1, y1 = self._xy(raw, r - 4)
            x2, y2 = self._xy(raw, r - 12)
            self.create_line(x1, y1, x2, y2, fill=C["text"], width=2)
            tx, ty = self._xy(raw, r - 23)
            self.create_text(tx, ty, text=t, fill=C["red"] if "+" in t else C["text"], font=(UI, 8))
        self.create_text(12, 10, text=self.title, anchor="nw", fill=C["acc"], font=(UI, 9, "bold"))

    @staticmethod
    def s_text(raw):
        if raw <= 120:
            return f"S{int(round(raw / (120 / 9)))}"
        return f"S9+{int(round((raw - 120) / 121 * 60 / 5) * 5)}"

    def set(self, raw):
        self.target = raw

    def animate(self, swr_text=""):
        self.val += 0.35 * (self.target - self.val)
        self.delete("dyn")
        x, y = self._xy(self.val, self.r + 6)
        self.create_line(self.cx, self.cy, x, y, fill="#f2f6f8", width=2, tags="dyn")
        self.create_oval(self.cx - 6, self.cy - 6, self.cx + 6, self.cy + 6, fill=C["btn"],
                         outline=C["acc"], tags="dyn")
        self.create_text(self.w - 12, 10, text=self.s_text(self.target), anchor="ne",
                         fill=C["text"], font=(UI, 13, "bold"), tags="dyn")
        if swr_text:
            self.create_text(self.w - 12, 32, text=swr_text, anchor="ne", fill=C["acc2"],
                             font=(UI, 10, "bold"), tags="dyn")


def swr_from_raw(v):
    pts = [(0, 1.0), (48, 1.5), (80, 2.0), (120, 3.0), (255, 6.0)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if v <= x1:
            return y0 + (v - x0) * (y1 - y0) / (x1 - x0)
    return 6.0


# ----------------------------------------------------------------- logboek (ADIF)
def adif_field(name, val):
    val = str(val or "").strip()
    return f"<{name}:{len(val)}>{val} " if val else ""


def append_qso(path, rec):
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write(f"{APP_NAME} logbook\n" + adif_field("ADIF_VER", "3.1.4") +
                    adif_field("PROGRAMID", "CWStation") + adif_field("PROGRAMVERSION", APP_VERSION) + "<EOH>\n")
        f.write("".join(adif_field(k, v) for k, v in rec.items()) + "<EOR>\n")


def read_adif(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = f.read()
    except FileNotFoundError:
        return []
    i = data.upper().find("<EOH>")
    if i >= 0:
        data = data[i + 5:]
    out, rec, pos = [], {}, 0
    tag = re.compile(r"<(\w+)(?::(\d+))?(?::\w)?>", re.I)
    while True:
        m = tag.search(data, pos)
        if not m:
            break
        name = m.group(1).upper()
        if name == "EOR":
            out.append(rec)
            rec = {}
            pos = m.end()
            continue
        n = int(m.group(2) or 0)
        rec[name] = data[m.end():m.end() + n]
        pos = m.end() + n
    return out


# ----------------------------------------------------------------- hoofdapplicatie
class App:
    AUDIO_FMAX = 3000.0
    STEPS = [10, 50, 100, 500, 1000, 5000]

    def __init__(self, root):
        self.root = root
        self.cfg = self._load_cfg()
        self.lang = self.cfg.get("lang", "nl")
        C.update(THEMES.get(self.cfg.get("theme", "Amber"), THEMES["Amber"]))
        self.civ = None
        self.audio = None
        self.gq = queue.Queue()
        self.freq = 0
        self.mode = ""
        self.mode_code = 0x03
        self.filt = 1
        self.ifw = None
        self.tx = False
        self.smeter = 0
        self.swr = None
        self.scope = {"start": 0, "end": 0, "data": bytearray()}
        self.wf_floor = None
        self.tone_anchor = 600
        self.scope_frames = 0
        self.poll_n = 0
        self.func_state = {"nb": 0, "nr": 0, "pamp": 0, "att": 0, "atu": 0}
        self.radio_addr = None
        self.radio_name = "IC-7300"
        self.detecting = False
        self.tx_meters = {"PO": None, "SWR": None, "ALC": None, "Id": None}
        self.vd = None
        self.update_info = None
        self._silent_since = None
        self.tool_tab = "dec"
        self.cq_active = False
        self._word_start = None
        self._skim_t = 0
        self.sender = CWSender(self)
        st_cfg = self.cfg.get("step", 10)
        self.step_idx = self.STEPS.index(st_cfg) if st_cfg in self.STEPS else 0
        self._init_vars()
        self._style()
        self._build()
        self.root.after(40, self._tick)
        self.root.after(250, self._poll)
        self.root.after(500, self._clock)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

    def t(self, nl, en):
        return nl if self.lang == "nl" else en

    # ---------- config
    def _load_cfg(self):
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
        except OSError:
            pass
        src = CONFIG_FILE if os.path.exists(CONFIG_FILE) else next(
            (p for p in OLD_CONFIGS if os.path.exists(p)), None)
        if src:
            try:
                with open(src, encoding="utf-8") as f:
                    user = json.load(f)
                cfg.update({k: v for k, v in user.items() if k != "macros"})
                cfg["macros"].update(user.get("macros", {}))
            except Exception as e:
                print("config:", e)
        old = {v: k for k, v in THEME_NL.items()}
        cfg["theme"] = old.get(cfg.get("theme"), cfg.get("theme"))
        if cfg["theme"] not in THEMES:
            cfg["theme"] = "Amber"
        return cfg

    def _save_cfg(self):
        try:
            self.cfg.update(port=self.port_var.get(), baud=int(self.baud_var.get()),
                            civ_addr=self.addr_var.get(), audio_device=self.dev_var.get(),
                            wpm=self.wpm_var.get(), step=self.STEPS[self.step_idx], lang=self.lang)
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print("config save:", e)

    # ---------- variabelen & stijl
    def _init_vars(self):
        self.port_var = tk.StringVar(value=self.cfg["port"])
        self.baud_var = tk.StringVar(value=str(self.cfg["baud"]))
        self.addr_var = tk.StringVar(value=self.cfg["civ_addr"])
        self.dev_var = tk.StringVar()
        self.wpm_var = tk.IntVar(value=int(self.cfg["wpm"]))
        self.bkin_var = tk.BooleanVar(value=True)
        self.scope_var = tk.BooleanVar(value=True)
        self.tone_var = tk.IntVar(value=600)
        self.bw_var = tk.StringVar(value="AUTO")
        self.afc_var = tk.BooleanVar(value=True)
        self.sq_var = tk.DoubleVar(value=2.3)
        self.range_var = tk.DoubleVar(value=45)
        self.ref_var = tk.DoubleVar(value=3)
        self.mute_var = tk.BooleanVar(value=True)
        self.live_var = tk.BooleanVar(value=False)
        self.cqrep_var = tk.BooleanVar(value=False)
        self.skim_var = tk.BooleanVar(value=True)
        self.af_var = tk.DoubleVar(value=0)
        self.rf_var = tk.DoubleVar(value=255)
        self.pwr_var = tk.DoubleVar(value=255)
        self.upd_var = tk.BooleanVar(value=bool(self.cfg.get("check_updates", True)))
        self.fentry = tk.StringVar()
        self.call_var = tk.StringVar()
        self.rst_var = tk.StringVar(value="599")
        self.rstr_var = tk.StringVar(value="599")
        self.hisname_var = tk.StringVar()
        self.tx_var = tk.StringVar()

    def _style(self):
        r = self.root
        r.configure(bg=C["bg"])
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TCombobox", fieldbackground=C["panel2"], background=C["btn"], foreground=C["text"],
                     arrowcolor=C["acc"], bordercolor=C["border"], lightcolor=C["panel2"],
                     darkcolor=C["panel2"], selectbackground=C["panel2"], selectforeground=C["text"])
        st.map("TCombobox", fieldbackground=[("readonly", C["panel2"])], foreground=[("readonly", C["text"])])
        st.configure("Vertical.TScrollbar", background=C["btn"], troughcolor=C["panel"],
                     bordercolor=C["panel"], arrowcolor=C["acc"])
        st.configure("Treeview", background=C["scr"], fieldbackground=C["scr"], foreground=C["text"],
                     rowheight=24, borderwidth=0, font=(UI, 10))
        st.map("Treeview", background=[("selected", C["btnhi"])], foreground=[("selected", C["acc"])])
        st.configure("Treeview.Heading", background=C["panel2"], foreground=C["dim"], borderwidth=0,
                     font=(UI, 9, "bold"), relief="flat")
        st.map("Treeview.Heading", background=[("active", C["btn"])])
        r.option_add("*TCombobox*Listbox.background", C["panel2"])
        r.option_add("*TCombobox*Listbox.foreground", C["text"])
        r.option_add("*TCombobox*Listbox.selectBackground", C["acc"])
        r.option_add("*TCombobox*Listbox.selectForeground", "#03141c")

    # ---------- UI
    def _build(self):
        r = self.root
        t = self.t
        r.title(f"{APP_NAME} - Icom IC-7300" + (f" - {self.cfg['mycall']}" if self.cfg.get("mycall") else ""))

        # ===== kopbalk
        hdr = tk.Frame(r, bg=C["bg"])
        hdr.pack(fill="x", padx=14, pady=(10, 6))
        logo = tk.Canvas(hdr, width=54, height=54, bg=C["bg"], highlightthickness=0)
        logo.pack(side="left")
        logo.create_oval(2, 2, 52, 52, outline=C["acc"], width=2, fill=C["panel"])
        logo.create_text(27, 22, text="CW", fill=C["acc"], font=(UI, 14, "bold"))
        for x0, x1 in ((12, 17), (21, 32), (36, 41)):
            logo.create_rectangle(x0, 36, x1, 40, fill=C["acc2"], outline="")
        tt = tk.Frame(hdr, bg=C["bg"])
        tt.pack(side="left", padx=10)
        tk.Label(tt, text=APP_NAME, bg=C["bg"], fg=C["text"], font=(UI, 22, "bold")).pack(anchor="w")
        sub = t("voor Icom IC-7300 / IC-7300MK2  ·  decoder & keyer",
                "for Icom IC-7300 / IC-7300MK2  ·  decoder & keyer")
        if self.cfg.get("mycall"):
            sub += "  ·  " + self.cfg["mycall"].upper()
        tk.Label(tt, text=sub, bg=C["bg"], fg=C["dim"], font=(UI, 10)).pack(anchor="w")
        srow = tk.Frame(tt, bg=C["bg"])
        srow.pack(anchor="w")
        self.status = label(srow, "", fg=C["amber"], font=(UI, 9), bg=C["bg"])
        self.status.pack(side="left")
        self.status.bind("<Button-1>", self._status_click)
        self.upd_btn = FlatButton(srow, "", command=self._open_update, padx=10, pady=1,
                                  font=(UI, 9, "bold"), accent=C["acc2"])
        if self.update_info:
            self._show_update_button()

        con = tk.Frame(hdr, bg=C["bg"])
        con.pack(side="right")
        row = tk.Frame(con, bg=C["bg"])
        row.pack(anchor="e")
        label(row, t("Poort", "Port")).pack(side="left")
        entry(row, self.port_var, 6).pack(side="left", padx=(3, 8))
        label(row, "Baud").pack(side="left")
        ttk.Combobox(row, textvariable=self.baud_var, width=7, state="readonly",
                     values=["115200", "57600", "38400", "19200", "9600"]).pack(side="left", padx=(3, 8))
        label(row, "CI-V").pack(side="left")
        ttk.Combobox(row, textvariable=self.addr_var, width=5, values=["auto", "94", "B6"]).pack(side="left", padx=(3, 8))
        self.btn_conn = FlatButton(row, "", command=self.toggle_civ, padx=16, pady=6)
        self.btn_conn.pack(side="left")
        row2 = tk.Frame(con, bg=C["bg"])
        row2.pack(anchor="e", pady=(6, 0))
        label(row2, "Audio").pack(side="left")
        self.dev_box = ttk.Combobox(row2, textvariable=self.dev_var, width=34, state="readonly",
                                    values=self._audio_devices())
        self.dev_box.pack(side="left", padx=(3, 8))
        self._preselect_device()
        self.btn_audio = FlatButton(row2, "", command=self.toggle_audio, padx=14, pady=4)
        self.btn_audio.pack(side="left")
        FlatButton(row2, t("Logboek", "Logbook"), command=self.show_log, padx=12, pady=4).pack(side="left", padx=(8, 0))
        FlatButton(row2, t("Enquête", "Survey"), command=self.open_survey, padx=12, pady=4).pack(side="left", padx=(6, 0))
        FlatButton(row2, t("Handleiding", "Manual"), command=self.open_manual, padx=12, pady=4).pack(side="left", padx=(6, 0))
        FlatButton(row2, "⚙ " + t("Instellingen", "Settings"), command=self.show_settings,
                   padx=12, pady=4).pack(side="left", padx=(6, 0))
        clk = tk.Frame(hdr, bg=C["bg"])
        clk.pack(side="left", padx=(30, 0))
        for name, attr in ((t("LOKAAL", "LOCAL"), "clk_loc"), ("UTC", "clk_utc")):
            col = tk.Frame(clk, bg=C["bg"])
            col.pack(side="left", padx=10)
            label(col, name, fg=C["acc"], font=(UI, 8, "bold")).pack()
            lb = tk.Label(col, text="--:--:--", bg=C["bg"], fg=C["text"], font=(DIGIT, 17, "bold"))
            lb.pack()
            setattr(self, attr, lb)


        # ===== hoofdgedeelte
        main = tk.Frame(r, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=14)
        left = tk.Frame(main, bg=C["bg"])
        left.pack(side="left", fill="y")
        right = tk.Frame(main, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        # --- frequentie
        f, b, _ = panel(left)
        f.pack(fill="x")
        self.freq_lbl = tk.Label(b, text=self._freq_text(), bg=C["panel"], fg="#f4fbff",
                                 font=(DIGIT, 32, "bold"), cursor="sb_v_double_arrow")
        self.freq_lbl.pack()
        self.freq_lbl.bind("<MouseWheel>", lambda e: self._step_tune(1 if e.delta > 0 else -1))
        fr = tk.Frame(b, bg=C["panel"])
        fr.pack(fill="x", pady=(2, 0))
        self.mode_lbl = label(fr, "--", fg=C["acc"], font=(UI, 13, "bold"))
        self.mode_lbl.pack(side="left")
        self.band_lbl = label(fr, "", fg=C["dim"], font=(UI, 11))
        self.band_lbl.pack(side="left", padx=10)
        FlatButton(fr, t("Zet", "Set"), command=self.set_freq_khz, padx=8, pady=2, font=(UI, 9, "bold")).pack(side="right")
        e = entry(fr, self.fentry, 9)
        e.pack(side="right", padx=4)
        e.bind("<Return>", lambda ev: self.set_freq_khz())
        label(fr, "kHz").pack(side="right")

        # --- knop + stap
        f, b, _ = panel(left)
        f.pack(fill="x", pady=6)
        self.knob = Knob(b, 124, self._step_tune)
        self.knob.pack(side="left")
        side = tk.Frame(b, bg=C["panel"])
        side.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.tx_lbl = tk.Label(side, text="RX", bg=C["green"], fg="#03141c", font=(UI, 14, "bold"), width=5, pady=1)
        self.tx_lbl.pack(pady=(2, 6))
        label(side, t("Afstemstap", "Tuning step")).pack()
        sr = tk.Frame(side, bg=C["panel"])
        sr.pack(pady=2)
        FlatButton(sr, "‹", command=lambda: self._chg_step(-1), padx=9, pady=2).pack(side="left")
        self.step_lbl = label(sr, "", fg=C["text"], font=(UI, 13, "bold"), width=7)
        self.step_lbl.pack(side="left")
        FlatButton(sr, "›", command=lambda: self._chg_step(1), padx=9, pady=2).pack(side="left")
        self._chg_step(0)
        label(side, t("slepen of scrollen", "drag or scroll"), font=(UI, 8)).pack(pady=(4, 0))

        # --- S-meter
        f, b, _ = panel(left)
        f.pack(fill="x")
        self.meter = SMeter(b, 360, 112, t("SIGNAAL", "SIGNAL"))
        self.meter.pack()
        self.bars = BarMeter(b, 360)
        self.bars.pack(pady=(6, 0))
        self.vd_lbl = label(b, "", fg=C["dim"], font=(UI, 8))
        self.vd_lbl.pack(anchor="e")

        # --- AF / RF
        f, b, _ = panel(left)
        f.pack(fill="x", pady=6)
        for name, var, cmd in (("AF", self.af_var, self._send_af), ("RF", self.rf_var, self._send_rf),
                               ("PWR", self.pwr_var, self._send_pwr)):
            rw = tk.Frame(b, bg=C["panel"])
            rw.pack(fill="x", pady=0)
            label(rw, name, fg=C["acc"], font=(UI, 10, "bold"), width=4).pack(side="left")
            Slider(rw, var, 0, 255, command=cmd, width=240, height=20).pack(side="left", fill="x", expand=True)
            vl = label(rw, "", fg=C["text"], width=6)
            vl.pack(side="left")
            if name == "PWR":
                upd = (lambda v=var, l=vl: l.config(text=f"{v.get() / 2.55:.0f} W"))
            else:
                upd = (lambda v=var, l=vl: l.config(text=f"{int(v.get() / 2.55)}%"))
            trace(vl, var, upd)
            upd()

        # --- decoder-hulp: statistiek, morsetabel, afkortingen
        f, b, head = panel(left, "")
        f.pack(fill="both", expand=True)
        head.title.config(text=t("DECODER-HULP", "DECODER TOOLS"))
        self.tool_btns = {}
        for key, txt in (("abbr", t("Afkortingen", "Abbrev.")), ("morse", "Morse"), ("dec", "Decoder")):
            bt = FlatButton(head, txt, command=lambda k=key: self._tool_tab(k), padx=8, pady=1, font=(UI, 8, "bold"))
            bt.pack(side="right", padx=1)
            self.tool_btns[key] = bt
        self.tool_body = b
        self._tool_tab(self.tool_tab)

        # ===== rechterkolom
        f, b, _ = panel(right)
        f.pack(fill="x")
        self.fil_btns = {}
        for i in (1, 2, 3):
            bt = FlatButton(b, f"FIL{i}", command=lambda i=i: self.set_filter(i), width=5, pady=6)
            bt.pack(side="left", padx=2)
            self.fil_btns[i] = bt
        tk.Frame(b, bg=C["border"], width=2, height=28).pack(side="left", padx=9)
        label(b, "IF").pack(side="left", padx=(0, 4))
        self.ifw_btns = {}
        for w in (50, 100, 250, 500, 1200, 2400):
            bt = FlatButton(b, f"{w}" if w < 1000 else f"{w / 1000:.1f}k",
                            command=lambda w=w: self.set_ifw(w), width=3, pady=6, padx=8, font=(UI, 9, "bold"))
            bt.pack(side="left", padx=2)
            self.ifw_btns[w] = bt
        self.ifw_lbl = label(b, "", fg=C["text"], font=(UI, 10, "bold"), width=7)
        self.ifw_lbl.pack(side="left", padx=4)
        tk.Frame(b, bg=C["border"], width=2, height=28).pack(side="left", padx=9)
        self.func_btns = {}
        for key, txt in (("nb", "NB"), ("nr", "NR"), ("pamp", "P.AMP"), ("att", "ATT")):
            bt = FlatButton(b, txt, command=lambda k=key: self.toggle_func(k), width=5, pady=6)
            bt.pack(side="left", padx=2)
            self.func_btns[key] = bt
        FlatButton(b, "SCOPE", var=self.scope_var, command=self.apply_scope, width=5, pady=6).pack(side="right", padx=2)
        tk.Frame(b, bg=C["border"], width=2, height=28).pack(side="right", padx=9)
        FlatButton(b, "TUNE", command=self.atu_tune, width=5, pady=6, accent=C["red"]).pack(side="right", padx=2)
        bt = FlatButton(b, "ATU", command=lambda: self.toggle_func("atu"), width=4, pady=6)
        bt.pack(side="right", padx=2)
        self.func_btns["atu"] = bt

        # --- radio-scope
        f, b, head = panel(right, "")
        f.pack(fill="x", pady=8)
        self.scope_title = head.title
        self.wf_scope = Waterfall(b, 66, 112, on_click=self._scope_click, label_fn=self._scope_label)
        self.wf_scope.canvas.pack(fill="x")

        # --- audio
        f, b, head = panel(right, t("AUDIO 0–3 kHz  ·  klik = decodeertoon", "AUDIO 0–3 kHz  ·  click = decode tone"))
        f.pack(fill="x")
        self.dwpm_lbl = label(head, "-- wpm", fg=C["acc"], font=(MONO, 11, "bold"))
        self.dwpm_lbl.pack(side="right")
        self.lvl = tk.Canvas(head, width=90, height=10, bg=C["scr"], highlightthickness=0)
        self.lvl.pack(side="right", padx=10)
        self.wf_audio = Waterfall(b, 52, 104, on_click=self._audio_click,
                                  label_fn=lambda fr: f"{fr * self.AUDIO_FMAX:.0f}")
        self.wf_audio.canvas.pack(fill="x")
        ctl = tk.Frame(b, bg=C["panel"])
        ctl.pack(fill="x", pady=(8, 0))
        label(ctl, t("Toon", "Tone")).pack(side="left")
        FlatButton(ctl, "−", command=lambda: self._tone_step(-10), padx=7, pady=1).pack(side="left", padx=(4, 0))
        tk.Label(ctl, textvariable=self.tone_var, bg=C["panel"], fg=C["text"], font=(UI, 11, "bold"),
                 width=5).pack(side="left")
        FlatButton(ctl, "+", command=lambda: self._tone_step(10), padx=7, pady=1).pack(side="left")
        label(ctl, "Hz   BW").pack(side="left", padx=(4, 4))
        self.bw_btns = {}
        for bw in ("AUTO", "50", "100", "200", "400"):
            bt = FlatButton(ctl, bw, command=lambda bw=bw: self._set_bw(bw), padx=7, pady=1, font=(UI, 9, "bold"))
            bt.pack(side="left", padx=1)
            self.bw_btns[bw] = bt
        self._set_bw(self.bw_var.get())
        FlatButton(ctl, "AFC", var=self.afc_var, padx=9, pady=1, font=(UI, 9, "bold")).pack(side="left", padx=(10, 2))
        FlatButton(ctl, t("Stil bij TX", "Mute on TX"), var=self.mute_var, padx=9, pady=1,
                   font=(UI, 9, "bold")).pack(side="left", padx=2)
        for name, var, lo, hi, cmd in ((t("Squelch", "Squelch"), self.sq_var, 1.5, 5.0, lambda fin: self.apply_dec(False)),
                                       ("Contrast", self.range_var, 15, 80, None),
                                       ("Ref", self.ref_var, -20, 30, None)):
            label(ctl, name).pack(side="left", padx=(12, 2))
            Slider(ctl, var, lo, hi, command=cmd, width=84, height=18).pack(side="left")

        # --- decodeertekst + skimmer
        low = tk.Frame(right, bg=C["bg"])
        low.pack(fill="both", expand=True, pady=8)
        f, b, head = panel(low, t("SIGNALEN (skimmer)", "SIGNALS (skimmer)"))
        f.pack(side="right", fill="both", padx=(8, 0))
        FlatButton(head, t("Aan", "On"), var=self.skim_var, command=self._skim_toggle, padx=10, pady=1,
                   font=(UI, 9, "bold")).pack(side="right")
        cols = ("hz", "wpm", "call", "text")
        self.tree = ttk.Treeview(b, columns=cols, show="headings", height=6, selectmode="browse")
        for c_, w_, txt_ in (("hz", 50, "Hz"), ("wpm", 44, "WPM"), ("call", 90, "Call"),
                             ("text", 250, t("Tekst", "Text"))):
            self.tree.heading(c_, text=txt_, anchor="w")
            self.tree.column(c_, width=w_, anchor="w", stretch=(c_ == "text"))
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._skim_select)
        self.tree.bind("<Double-Button-1>", self._skim_call)
        label(b, t("klik = decoderen  ·  dubbelklik = call overnemen",
                   "click = decode  ·  double-click = take call"), font=(UI, 8)).pack(anchor="w", pady=(4, 0))

        f, b, head = panel(low, t("ONTVANGEN  ·  klik op een call = naar Call-veld",
                                  "RECEIVED  ·  click a call = to Call field"))
        f.pack(side="left", fill="both", expand=True)
        FlatButton(head, t("Wis", "Clear"), command=lambda: self.txt.delete("1.0", "end"), padx=10, pady=1,
                   font=(UI, 9, "bold")).pack(side="right")
        tf = tk.Frame(b, bg=C["scr"])
        tf.pack(fill="both", expand=True)
        self.txt = tk.Text(tf, height=5, bg=C["scr"], fg="#e6f4fa", insertbackground=C["acc"],
                           font=(MONO, 15), wrap="word", relief="flat", padx=10, pady=8,
                           selectbackground=C["btnhi"], spacing1=2, spacing3=2)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.txt.yview)
        self.txt.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt.tag_config("tx", foreground=C["acc2"])
        self.txt.tag_config("call", foreground=C["acc"], underline=True)
        self.txt.tag_bind("call", "<Button-1>", self._click_call)
        self.txt.tag_bind("call", "<Enter>", lambda e: self.txt.config(cursor="hand2"))
        self.txt.tag_bind("call", "<Leave>", lambda e: self.txt.config(cursor="xterm"))
        self.txt.bind("<Double-Button-1>", self._grab_call)

        # ===== onderbalk
        bot = tk.Frame(r, bg=C["bg"])
        # onderbalk krijgt altijd voorrang: eerst onderaan plaatsen, dan pas het hoofdgedeelte
        main.pack_forget()
        bot.pack(side="bottom", fill="x", padx=14, pady=(0, 12))
        main.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        f, b, _ = panel(bot)
        f.pack(side="left", fill="y")
        mr = tk.Frame(b, bg=C["panel"])
        mr.pack(fill="x")
        self.mode_btns = {}
        for name, code in (("CW", 0x03), ("CW-R", 0x07), ("LSB", 0x00), ("USB", 0x01),
                           ("RTTY", 0x04), ("AM", 0x02), ("FM", 0x05)):
            bt = FlatButton(mr, name, command=lambda c=code: self.set_mode(c), width=4, pady=6, font=(UI, 11, "bold"))
            bt.pack(side="left", padx=2)
            self.mode_btns[name] = bt
        br = tk.Frame(b, bg=C["panel"])
        br.pack(fill="x", pady=(6, 0))
        self.band_btns = {}
        for name, fq in BANDS:
            bt = FlatButton(br, name, command=lambda fq=fq: self.set_freq(fq), width=3, pady=6, padx=9,
                            font=(UI, 11, "bold"))
            bt.pack(side="left", padx=2)
            self.band_btns[name] = bt

        f, b, _ = panel(bot)
        f.pack(side="left", fill="both", expand=True, padx=(10, 0))
        r1 = tk.Frame(b, bg=C["panel"])
        r1.pack(fill="x")
        label(r1, "Call").pack(side="left")
        ce = entry(r1, self.call_var, 11, font=(UI, 11, "bold"))
        ce.pack(side="left", padx=(3, 3))
        FlatButton(r1, "QRZ", command=self.qrz_lookup, padx=7, pady=1, font=(UI, 8, "bold")).pack(side="left", padx=(0, 10))
        label(r1, "RST snt").pack(side="left")
        entry(r1, self.rst_var, 4).pack(side="left", padx=(3, 8))
        label(r1, "RST rcv").pack(side="left")
        entry(r1, self.rstr_var, 4).pack(side="left", padx=(3, 8))
        label(r1, t("Naam", "Name")).pack(side="left")
        entry(r1, self.hisname_var, 10).pack(side="left", padx=(3, 8))
        FlatButton(r1, t("LOG QSO", "LOG QSO") + "  Ctrl+L", command=self.log_qso, padx=10, pady=2,
                   font=(UI, 9, "bold"), accent=C["green"]).pack(side="left")
        FlatButton(r1, "+", command=lambda: self._wpm_step(1), padx=7, pady=0).pack(side="right")
        tk.Label(r1, textvariable=self.wpm_var, bg=C["panel"], fg=C["text"], font=(UI, 13, "bold"),
                 width=3).pack(side="right")
        FlatButton(r1, "−", command=lambda: self._wpm_step(-1), padx=7, pady=0).pack(side="right")
        label(r1, "WPM").pack(side="right", padx=(0, 4))
        r2 = tk.Frame(b, bg=C["panel"])
        r2.pack(fill="x", pady=6)
        for key in sorted(self.cfg["macros"], key=lambda k: int(k[1:])):
            lbl, _ = self.cfg["macros"][key]
            FlatButton(r2, f"{key}  {lbl}", command=lambda k=key: self.macro(k), padx=6, pady=3,
                       font=(UI, 9, "bold")).pack(side="left", padx=2, fill="x", expand=True)
            r.bind(f"<{key}>", lambda ev, k=key: self.macro(k))
        r3 = tk.Frame(b, bg=C["panel"])
        r3.pack(fill="x")
        self.tx_entry = entry(r3, self.tx_var, 20, font=(MONO, 14))
        self.tx_entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.tx_entry.bind("<Return>", lambda ev: self.send_line())
        self.tx_entry.bind("<space>", self._space_key)
        FlatButton(r3, t("ZEND", "SEND") + "  ⏎", command=self.send_line, padx=14, pady=4).pack(side="left", padx=(8, 2))
        FlatButton(r3, "STOP  Esc", command=self.stop_tx, accent=C["red"], padx=14, pady=4).pack(side="left", padx=2)
        FlatButton(r3, "BK-IN", var=self.bkin_var, command=self._send_bkin, padx=9, pady=4,
                   font=(UI, 9, "bold")).pack(side="left", padx=(10, 2))
        FlatButton(r3, t("Per woord", "Per word"), var=self.live_var, padx=9, pady=4,
                   font=(UI, 9, "bold")).pack(side="left", padx=2)
        FlatButton(r3, "CQ ↻", var=self.cqrep_var, padx=9, pady=4, font=(UI, 9, "bold")).pack(side="left", padx=2)
        r.bind("<Escape>", lambda ev: self.stop_tx())
        r.bind("<Control-l>", lambda ev: self.log_qso())
        r.bind("<Control-L>", lambda ev: self.log_qso())

        self.apply_dec()
        self._update_highlights()
        if not self.status.cget("text"):
            self._set_status(t("niet verbonden", "not connected"), C["amber"])

    def rebuild(self):
        """UI opnieuw opbouwen (taal/thema/macro's), zonder verbinding te verbreken."""
        text = self.txt.get("1.0", "end-1c")
        for w in self.root.winfo_children():
            w.destroy()
        C.update(THEMES.get(self.cfg.get("theme", "Amber"), THEMES["Amber"]))
        self.status = None
        self._style()
        self._build()
        self.txt.insert("1.0", text)
        self.txt.see("end")
        self._set_status(self.t("verbonden", "connected") if self.civ else self.t("niet verbonden", "not connected"),
                         C["green"] if self.civ else C["amber"])

    # ---------- kleine UI-helpers
    def _freq_text(self):
        f = self.freq
        if not f:
            return "--.---.---"
        return f"{f // 1000000:d}.{(f // 1000) % 1000:03d}.{f % 1000:03d}"

    def _chg_step(self, d):
        self.step_idx = min(max(self.step_idx + d, 0), len(self.STEPS) - 1)
        s = self.STEPS[self.step_idx]
        self.step_lbl.config(text=f"{s} Hz" if s < 1000 else f"{s // 1000} kHz")

    def _step_tune(self, d):
        if self.freq:
            st = self.STEPS[self.step_idx]
            f = self.freq
            self.set_freq((f // st + 1) * st if d > 0 else ((f - 1) // st) * st)

    def _tone_step(self, d):
        self.tone_var.set(self.tone_var.get() + d)
        self.apply_dec()

    def _wpm_step(self, d):
        self.wpm_var.set(min(max(self.wpm_var.get() + d, 6), 48))
        self.send_wpm()

    def _set_bw(self, bw):
        self.bw_var.set(bw)
        for k, bt in self.bw_btns.items():
            bt.set_active(k == bw)
        self.apply_dec()

    def _update_highlights(self):
        t = self.t
        for k, bt in self.mode_btns.items():
            bt.set_active(k == self.mode)
        band = ""
        for k, (lo, hi) in BAND_RANGES.items():
            if lo <= self.freq <= hi:
                band = k
        for k, bt in self.band_btns.items():
            bt.set_active(k == band)
        self.band_lbl.config(text=f"{band} m" if band else "")
        for i, bt in self.fil_btns.items():
            bt.set_active(self.civ is not None and i == self.filt)
        for k, bt in self.func_btns.items():
            bt.set_active(bool(self.func_state.get(k)))
        for w, bt in self.ifw_btns.items():
            bt.set_active(self.civ is not None and w == self.ifw)
        self.ifw_lbl.config(text=f"{self.ifw} Hz" if (self.civ and self.ifw) else "")
        if self.civ:
            if self.detecting:
                self.btn_conn.config(text="●  " + t("zoeken…", "searching…"))
                self.btn_conn.set_active(True, C["amber"])
            else:
                self.btn_conn.config(text="●  " + t(f"{self.radio_name} verbonden", f"{self.radio_name} connected"))
                self.btn_conn.set_active(True, C["green"])
        else:
            self.btn_conn.set_active(False)
            self.btn_conn.config(text="●  " + t("Verbind radio", "Connect radio"), fg=C["red"])
        self.btn_audio.set_active(self.audio is not None)
        self.btn_audio.config(text=t("Audio aan", "Audio on") if self.audio else t("Start audio", "Start audio"))
        if self.mode:
            self.mode_lbl.config(text=f"{self.mode}   FIL{self.filt}")
        self.freq_lbl.config(text=self._freq_text())

    def _clock(self):
        try:
            self.clk_loc.config(text=time.strftime("%H:%M:%S"))
            self.clk_utc.config(text=time.strftime("%H:%M:%S", time.gmtime()))
        except tk.TclError:
            pass
        self.root.after(1000 - int(time.time() * 1000) % 1000 + 5, self._clock)

    def _set_status(self, text, color=None):
        if self.status is not None:
            self.status.config(text=text, fg=color or C["dim"])

    # ---------- audio-apparaten
    def _audio_devices(self):
        if sd is None:
            return []
        out = []
        try:
            apis = sd.query_hostapis()
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    out.append(f"{i}: {d['name']} [{apis[d['hostapi']]['name']}]")
        except Exception as e:
            print("audio:", e)
        return out

    def _preselect_device(self):
        devs = self.dev_box["values"]
        want = self.cfg.get("audio_device", "")
        if self.dev_var.get() in devs:
            return
        if want in devs:
            self.dev_var.set(want)
            return
        for d in devs:
            if "CODEC" in d.upper():
                self.dev_var.set(d)
                return
        if devs:
            self.dev_var.set(devs[0])

    # ---------- verbinding
    def toggle_civ(self):
        if self.civ:
            self._disconnect()
            return
        if serial is None:
            messagebox.showerror("Error", "pyserial missing:  pip install pyserial")
            return
        txt = self.addr_var.get().strip().lower().replace("h", "")
        auto = txt in ("", "auto")
        try:
            addr = 0x94 if auto else int(txt, 16)
            self.civ = CIV(self.port_var.get().strip(), int(self.baud_var.get()), addr, self._on_frame)
        except Exception as e:
            self.civ = None
            messagebox.showerror(self.t("Seriële poort", "Serial port"),
                                 self.t(f"Kan {self.port_var.get()} niet openen:\n{e}",
                                        f"Cannot open {self.port_var.get()}:\n{e}"))
            return
        self.civ.send_to(addr, 0x1C, b"\x00\x00")           # zeker weten: ontvangen (TX uit)
        if auto:
            self.civ.send_to(0xB6, 0x1C, b"\x00\x00")
            self.detecting = True
            self._probe()
            self._set_status(self.t("radio zoeken (94h / B6h)…", "looking for radio (94h / B6h)…"), C["amber"])
        else:
            self._radio_found(addr)
        self._update_highlights()

    def _probe(self):
        """Vraag het transceiver-ID op bij de bekende adressen; het antwoord verraadt model en adres."""
        if self.civ and self.detecting:
            for a in RADIOS:
                self.civ.send_to(a, 0x19, b"\x00")
            self.root.after(2000, self._probe_timeout)

    def _probe_timeout(self):
        if self.civ and self.detecting:
            self._set_status(self.t("geen antwoord van de radio – controleer COM-poort, baud en CI-V-adres",
                                    "no answer from the radio – check COM port, baud rate and CI-V address"),
                             C["red"])
            self._probe()

    def _radio_found(self, addr):
        self.detecting = False
        self.radio_addr = addr
        self.radio_name = RADIOS.get(addr, f"Icom {addr:02X}h")
        self.civ.addr = addr
        self._set_status(self.t(f"{self.radio_name} via {self.port_var.get()} (CI-V {addr:02X}h)",
                                f"{self.radio_name} via {self.port_var.get()} (CI-V {addr:02X}h)"), C["green"])
        c = self.civ
        c.send(0x1C, b"\x00\x00")
        for cmd, data in ((0x03, b""), (0x04, b""), (0x1A, b"\x03"), (0x14, b"\x09"), (0x14, b"\x01"),
                          (0x14, b"\x02"), (0x14, b"\x0A"), (0x16, b"\x22"), (0x16, b"\x40"),
                          (0x16, b"\x02"), (0x11, b""), (0x1C, b"\x01"), (0x15, b"\x15")):
            c.send(cmd, data)
        self.send_wpm()
        self._send_bkin()
        self.apply_scope()
        self._update_highlights()

    def _disconnect(self):
        if self.civ:
            try:
                self.civ.send(0x1C, b"\x00\x00")
                self.civ.send(0x27, b"\x11\x00")
            except Exception:
                pass
            self.civ.close()
        self.civ = None
        self._set_status(self.t("niet verbonden", "not connected"), C["amber"])
        self._update_highlights()

    def apply_scope(self):
        if self.civ:
            if self.scope_var.get():
                self.civ.send(0x27, b"\x10\x01")
                self.civ.send(0x27, b"\x11\x01")
            else:
                self.civ.send(0x27, b"\x11\x00")

    def toggle_audio(self):
        if self.audio:
            self.audio.close()
            self.audio = None
            self._update_highlights()
            return
        if sd is None:
            messagebox.showerror("Error", "sounddevice missing:  pip install sounddevice")
            return
        try:
            idx = int(self.dev_var.get().split(":")[0])
            self.audio = AudioEngine(idx, self._on_wf_row, self._make_decoder, Skimmer)
            self.audio.skimmer.enabled = self.skim_var.get()
        except Exception as e:
            self.audio = None
            messagebox.showerror("Audio", self.t(f"Kan audio niet starten:\n{e}", f"Cannot start audio:\n{e}"))
            return
        self.apply_dec()
        self._update_highlights()

    def _make_decoder(self, fs):
        return CWDecoder(fs, lambda s: self.gq.put(("rx", s)), tone=self.tone_var.get(),
                         bw=self._bw_value(), wpm=self.wpm_var.get())

    # ---------- CI-V ontvangst (reader-thread)
    def _on_frame(self, cmd, data, frm=None):
        if self.detecting and frm is not None and frm != CTRL_ADDR:
            self.gq.put(("found", frm))
            if cmd == 0x19:
                return
        if cmd in (0x00, 0x03) and len(data) >= 5:
            self.gq.put(("freq", bcd_le_to_int(data[:5])))
        elif cmd in (0x01, 0x04) and len(data) >= 1:
            self.gq.put(("mode", data[0], data[1] if len(data) > 1 else None))
        elif cmd == 0x14 and len(data) >= 3:
            v = bcd_byte(data[1]) * 100 + bcd_byte(data[2])
            if data[0] == 0x09:
                self.gq.put(("pitch", int(round((300 + v * 600 / 255) / 5) * 5)))
            elif data[0] == 0x01:
                self.gq.put(("af", v))
            elif data[0] == 0x02:
                self.gq.put(("rf", v))
            elif data[0] == 0x0A:
                self.gq.put(("pwr", v))
        elif cmd == 0x15 and len(data) >= 3:
            v = bcd_byte(data[1]) * 100 + bcd_byte(data[2])
            if data[0] == 0x02:
                self.smeter = v
            elif data[0] == 0x11:
                self.tx_meters["PO"] = po_from_raw(v)
            elif data[0] == 0x12:
                self.swr = swr_from_raw(v)
                self.tx_meters["SWR"] = self.swr
            elif data[0] == 0x13:
                self.tx_meters["ALC"] = float(v)
            elif data[0] == 0x15:
                self.vd = vd_from_raw(v)
            elif data[0] == 0x16:
                self.tx_meters["Id"] = id_from_raw(v)
        elif cmd == 0x16 and len(data) >= 2:
            key = {0x22: "nb", 0x40: "nr", 0x02: "pamp"}.get(data[0])
            if key:
                self.gq.put(("func", key, data[1]))
        elif cmd == 0x11 and len(data) >= 1:
            self.gq.put(("func", "att", 1 if data[0] else 0))
        elif cmd == 0x1A and len(data) >= 2 and data[0] == 0x03:
            idx = bcd_byte(data[1])
            self.gq.put(("ifw", (idx + 1) * 50 if idx <= 9 else 500 + (idx - 9) * 100))
        elif cmd == 0x1C and len(data) >= 2 and data[0] == 0x00:
            self.gq.put(("txstate", bool(data[1])))
        elif cmd == 0x1C and len(data) >= 2 and data[0] == 0x01:
            self.gq.put(("func", "atu", 1 if data[1] else 0))
        elif cmd == 0x27 and len(data) >= 4 and data[0] == 0x00:
            self._scope_frame(data)
        elif cmd == 0xFA:
            self.gq.put(("ng", None))

    def _scope_frame(self, data):
        self.scope_frames += 1

        def ok(i):
            if len(data) <= i + 1:
                return False
            q, m = bcd_byte(data[i]), bcd_byte(data[i + 1])
            return 1 <= q <= m <= 20
        o = 2 if ok(2) else (1 if ok(1) else None)
        if o is None:
            return
        seq, smax = bcd_byte(data[o]), bcd_byte(data[o + 1])
        h = o + 2
        s = self.scope
        if seq == 1:
            s["data"] = bytearray()
            if len(data) >= h + 11:
                fmode = data[h]
                f1 = bcd_le_to_int(data[h + 1:h + 6])
                f2 = bcd_le_to_int(data[h + 6:h + 11])
                if fmode == 0x00:
                    s["start"], s["end"] = f1 - f2, f1 + f2
                else:
                    s["start"], s["end"] = f1, f2
                s["data"] += data[h + 12:]
        else:
            s["data"] += data[h:]
        if seq == smax and len(s["data"]) > 10:
            arr = np.frombuffer(bytes(s["data"]), dtype=np.uint8).astype(np.float32) / 160.0
            self.gq.put(("scope", arr))

    def _on_wf_row(self, spec, fs):
        nb = int(self.AUDIO_FMAX / (fs / AudioEngine.FFT))
        self.gq.put(("awf", 20 * np.log10(spec[:nb] + 1e-9), fs))

    # ---------- GUI-tick
    def _set_tx(self, on):
        if on == self.tx:
            return
        self.tx = on
        self.tx_lbl.config(text="TX" if on else "RX", bg=C["red"] if on else C["green"])
        if not on:
            self.swr = None
            self.tx_meters = {k: None for k in self.tx_meters}

    def _rx_char(self, ch):
        if ch == " ":
            if self._word_start is not None:
                word = self.txt.get(self._word_start, "end-1c")
                if find_calls(word):
                    self.txt.tag_add("call", self._word_start, "end-1c")
            self._word_start = None
            self.txt.insert("end", ch)
        else:
            if self._word_start is None:
                self._word_start = self.txt.index("end-1c")
            self.txt.insert("end", ch)
        self.txt.see("end")

    def _tick(self):
        try:
            self._tick_body()
        except tk.TclError as e:
            if "invalid command name" in str(e) or "application has been destroyed" in str(e):
                return                               # venster wordt gesloten
            log_error("gui", e)
        except Exception as e:                       # de GUI-lus mag nooit stoppen
            if not getattr(self, "_tick_err", False):
                self._tick_err = True
                log_error("gui", e)
                self._set_status(self.t(f"interne fout: {e} (zie error.log)", f"internal error: {e} (see error.log)"),
                                 C["red"])
        self.root.after(40, self._tick)

    def _tick_body(self):
        hl = False
        t = self.t
        try:
            while True:
                item = self.gq.get_nowait()
                kind = item[0]
                if kind == "rx":
                    self._rx_char(item[1])
                elif kind == "tx":
                    self._word_start = None
                    self.txt.insert("end", item[1], "tx")
                    self.txt.see("end")
                    self._set_tx(True)
                    if self.audio and self.mute_var.get():
                        self.audio.decoder.muted = True
                elif kind == "txdone":
                    self._set_tx(False)
                    if self.audio:
                        self.root.after(300, lambda: setattr(self.audio.decoder, "muted", False) if self.audio else None)
                    if self.cq_active and self.cqrep_var.get():
                        self.root.after(int(self.cfg.get("cq_repeat", 8) * 1000), self._cq_again)
                elif kind == "txstate":
                    if not self.sender.busy:
                        self._set_tx(item[1])
                elif kind == "freq":
                    self.freq = item[1]
                    hl = True
                elif kind == "mode":
                    self.mode_code = item[1]
                    self.mode = MODES.get(item[1], f"{item[1]:02X}")
                    if item[2] in (1, 2, 3):
                        self.filt = item[2]
                    hl = True
                elif kind == "pitch":
                    self.tone_var.set(item[1])
                    self.apply_dec()
                elif kind == "af":
                    self.af_var.set(item[1])
                elif kind == "rf":
                    self.rf_var.set(item[1])
                elif kind == "pwr":
                    self.pwr_var.set(item[1])
                elif kind == "update":
                    self.update_info = item[1]
                    self._show_update_button()
                    self._ask_update()
                elif kind == "found":
                    if self.detecting and self.civ:
                        self._radio_found(item[1])
                elif kind == "ifw":
                    self.ifw = item[1]
                    hl = True
                elif kind == "func":
                    self.func_state[item[1]] = item[2]
                    if item[1] == "pamp":
                        self.func_btns["pamp"].config(text=("P.AMP", "P.AMP1", "P.AMP2")[min(item[2], 2)])
                    hl = True
                elif kind == "scope":
                    self.wf_scope.add_row(item[1])
                elif kind == "awf":
                    self._audio_row(item[1], item[2])
                elif kind == "ng":
                    self._set_status(t("radio: NG (commando geweigerd)", "radio: NG (command rejected)"), C["red"])
                    self.root.after(3000, lambda: self._set_status(
                        t("verbonden", "connected") if self.civ else t("niet verbonden", "not connected"),
                        C["green"] if self.civ else C["amber"]))
        except queue.Empty:
            pass
        if hl:
            self._update_highlights()

        bwv = self.audio.decoder.bw if self.audio else (60.0 if self.bw_var.get() == "AUTO" else float(self.bw_var.get()))
        self.wf_audio.markers = [(self.tone_var.get() / self.AUDIO_FMAX, C["red"], bwv / self.AUDIO_FMAX)]
        s = self.scope
        if s["end"] > s["start"] and self.freq:
            self.wf_scope.markers = [((self.freq - s["start"]) / (s["end"] - s["start"]), C["red"], 0)]
        now = time.time()
        if now - self._skim_t > 0.5:
            self._skim_t = now
            self._skim_refresh()
        self.wf_scope.render()
        self.wf_audio.render()
        self.meter.set(self.smeter if not self.tx else 0)
        self.meter.animate(f"SWR {self.swr:.1f}" if (self.tx and self.swr) else "")
        for k, v in self.tx_meters.items():
            self.bars.set(k, v if self.tx else None)
        self.bars.draw()
        self.vd_lbl.config(text=f"Vd {self.vd:.1f} V" if self.vd else "")
        if now - getattr(self, "_lf_t", 0) > 1.0:
            self._lf_t = now
            n = self.scope_frames - getattr(self, "_lf_n", 0)
            self._lf_n = self.scope_frames
            base = t(f"SPECTRUMSCOPE {self.radio_name}  ·  klik = afstemmen", f"SPECTRUM SCOPE {self.radio_name}  ·  click = tune")
            if self.civ and self.scope_var.get():
                if n:
                    self.scope_title.config(text=f"{base}  ·  {n} frames/s", fg=C["dim"])
                else:
                    if self.radio_addr == 0xB6:
                        hint = t("SPECTRUMSCOPE  ·  GEEN scope-data: kies COM-poort A (CI-V), 115200 baud, scope aan op de radio",
                                 "SPECTRUM SCOPE  ·  NO scope data: use COM port A (CI-V), 115200 baud, scope on at the radio")
                    else:
                        hint = t("SPECTRUMSCOPE  ·  GEEN scope-data: zet CI-V USB Port = Unlink from [REMOTE] en 115200 baud",
                                 "SPECTRUM SCOPE  ·  NO scope data: set CI-V USB Port = Unlink from [REMOTE] and 115200 baud")
                    self.scope_title.config(text=hint, fg=C["amber"])
            else:
                self.scope_title.config(text=base, fg=C["dim"])
        self._audio_check(now)
        self._tool_refresh(now)
        if self.audio:
            d = self.audio.decoder
            lv = min(1.0, d.level / 2)
            self.lvl.delete("all")
            self.lvl.create_rectangle(0, 0, 90 * lv, 10, fill=C["acc"] if d.state else C["btnhi"], outline="")
            self.lvl.create_line(45, 0, 45, 10, fill=C["dim"])
            self.dwpm_lbl.config(text=f"{d.wpm:4.1f} wpm  ·  {d.bw:.0f} Hz")

    def _skim_refresh(self):
        sk = self.audio.skimmer if self.audio else None
        if sk is None or not self.skim_var.get():
            if self.tree.get_children():
                self.tree.delete(*self.tree.get_children())
            self.wf_audio.labels = []
            return
        rows = sorted(sk.snapshot(), key=lambda c: c["tone"])
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        labels = []
        for c in rows:
            calls = find_calls(c["text"])
            de = [w for w, after_de in calls if after_de]
            call = (de or [w for w, _ in calls] or [""])[-1]
            tail = " ".join(c["text"].split())[-40:]
            iid = str(c["id"])
            self.tree.insert("", "end", iid=iid, values=(f"{c['tone']:.0f}", f"{c['wpm']:.0f}", call, tail))
            active = time.time() - c["last"] < 4
            labels.append((c["tone"] / self.AUDIO_FMAX, call or f"{c['wpm']:.0f}",
                           _mix(C["acc2"], C["scr"], 0.1 if active else 0.55)))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])
        self.wf_audio.labels = labels

    def _skim_toggle(self):
        if self.audio and self.audio.skimmer:
            self.audio.skimmer.enabled = self.skim_var.get()

    def _skim_select(self, ev=None):
        sel = self.tree.selection()
        if not sel:
            return
        try:
            hz = float(self.tree.item(sel[0], "values")[0])
        except (IndexError, ValueError):
            return
        self.tone_var.set(int(round(hz)))
        self.tone_anchor = self.tone_var.get()
        self.apply_dec()

    def _skim_call(self, ev=None):
        sel = self.tree.selection()
        if sel:
            call = self.tree.item(sel[0], "values")[2]
            if call:
                self.call_var.set(call)

    def _audio_row(self, db, fs):
        p = np.percentile(db, 75) - 10
        self.wf_floor = p if self.wf_floor is None else 0.9 * self.wf_floor + 0.1 * p
        self.wf_audio.add_row((db - self.wf_floor - self.ref_var.get()) / self.range_var.get())
        if self.afc_var.get() and self.audio and not self.audio.decoder.muted:
            binhz = fs / AudioEngine.FFT
            anchor = self.tone_anchor
            lo, hi = int((anchor - 50) / binhz), int((anchor + 50) / binhz) + 1
            lo, hi = max(lo, 2), min(hi, len(db) - 2)
            if hi > lo:
                k = lo + int(np.argmax(db[lo:hi]))
                local = np.median(db[max(k - 40, 0):k + 40])
                if db[k] - local > 12:
                    a, b, c = db[k - 1], db[k], db[k + 1]
                    den = a - 2 * b + c
                    off = 0.5 * (a - c) / den if den != 0 else 0
                    fpk = (k + off) * binhz
                    tt = self.tone_var.get()
                    newt = int(round(tt + 0.3 * (fpk - tt)))
                    newt = min(max(newt, anchor - 50, 150), anchor + 50, 2950)
                    if newt != tt:
                        self.tone_var.set(newt)
                        self.audio.decoder.set_tone(newt)

    def _poll(self):
        if self.civ:
            try:
                self.poll_n += 1
                if self.detecting:
                    self.root.after(200, self._poll)
                    return
                if self.tx:
                    for sub in (b"\x11", b"\x12", b"\x13", b"\x16"):   # PO, SWR, ALC, Id
                        self.civ.send(0x15, sub)
                else:
                    self.civ.send(0x15, b"\x02")
                if self.poll_n % 10 == 0:
                    self.civ.send(0x15, b"\x15")                         # Vd
                if self.poll_n % 3 == 0:
                    self.civ.send(0x1C, b"\x00")
                if self.poll_n % 5 == 0:
                    self.civ.send(0x03)
                    self.civ.send(0x04)
            except Exception:
                self._set_status(self.t("seriële fout", "serial error"), C["red"])
        self.root.after(200, self._poll)

    # ---------- acties
    def apply_dec(self, user=True):
        try:
            tt = min(max(int(self.tone_var.get()), 150), 2950)
        except (ValueError, tk.TclError):
            tt = 600
        self.tone_var.set(tt)
        if user:
            self.tone_anchor = tt
        if self.audio:
            d = self.audio.decoder
            d.set_tone(tt)
            d.set_bw(self._bw_value())
            d.squelch = self.sq_var.get()

    def _bw_value(self):
        v = self.bw_var.get()
        return "auto" if v == "AUTO" else float(v)

    def _audio_click(self, frac):
        tt = int(round(frac * self.AUDIO_FMAX / 5) * 5)
        self.tone_var.set(min(max(tt, 150), 2950))
        self.tone_anchor = self.tone_var.get()
        self.apply_dec()

    def _scope_label(self, frac):
        s = self.scope
        if s["end"] <= s["start"]:
            return ""
        return f"{(s['start'] + frac * (s['end'] - s['start'])) / 1000:.1f}"

    def _scope_click(self, frac):
        s = self.scope
        if s["end"] > s["start"]:
            self.set_freq(int(round((s["start"] + frac * (s["end"] - s["start"])) / 10) * 10))

    def set_freq(self, hz):
        if not self.civ:
            return
        self.civ.send(0x05, int_to_bcd_le(int(hz), 5))
        self.gq.put(("freq", int(hz)))

    def set_freq_khz(self):
        try:
            self.set_freq(int(round(float(self.fentry.get().replace(",", ".")) * 1000)))
        except ValueError:
            pass

    def set_mode(self, m):
        if self.civ:
            self.civ.send(0x06, bytes([m, self.filt]))
            self.mode_code = m
            self.mode = MODES.get(m, self.mode)
            self._update_highlights()
            self.civ.send(0x04)
            self.civ.send(0x1A, b"\x03")
            self.root.after(400, lambda: self.civ and self.civ.send(0x04))

    def set_filter(self, i):
        if self.civ:
            self.filt = i
            self.civ.send(0x06, bytes([self.mode_code, i]))
            self.civ.send(0x04)
            self.civ.send(0x1A, b"\x03")
            self._update_highlights()

    def set_ifw(self, w):
        if not self.civ:
            return
        if self.mode not in ("CW", "CW-R", "LSB", "USB", "RTTY", "RTTY-R"):
            self._set_status(self.t("IF-breedte alleen in CW/SSB/RTTY", "IF width only in CW/SSB/RTTY"), C["amber"])
            return
        idx = w // 50 - 1 if w <= 500 else 9 + (w - 500) // 100
        self.civ.send(0x1A, b"\x03" + int_to_bcd_be(int(idx), 1))
        self.civ.send(0x1A, b"\x03")

    def toggle_func(self, key):
        if not self.civ:
            return
        v = self.func_state.get(key, 0)
        if key == "pamp":
            v = (v + 1) % 3
            self.civ.send(0x16, bytes([0x02, v]))
            self.civ.send(0x16, b"\x02")
        elif key == "att":
            v = 0 if v else 1
            self.civ.send(0x11, bytes([0x20 if v else 0x00]))
            self.civ.send(0x11)
        elif key == "atu":
            self.civ.send(0x1C, bytes([0x01, 0 if v else 1]))
            self.civ.send(0x1C, b"\x01")
        else:
            sub = {"nb": 0x22, "nr": 0x40}[key]
            self.civ.send(0x16, bytes([sub, 0 if v else 1]))
            self.civ.send(0x16, bytes([sub]))

    def _send_level(self, sub, var):
        if self.civ:
            self.civ.send(0x14, bytes([sub]) + int_to_bcd_be(int(min(max(var.get(), 0), 255)), 2))

    def _send_af(self, final):
        self._send_level(0x01, self.af_var)

    def _send_rf(self, final):
        self._send_level(0x02, self.rf_var)

    def _send_pwr(self, final):
        self._send_level(0x0A, self.pwr_var)

    def atu_tune(self):
        """Start het afstemmen van de ingebouwde tuner (zendt kort een draaggolf)."""
        if self.civ and not self.detecting:
            self.civ.send(0x1C, b"\x01\x02")
            self._set_status(self.t("tuner stemt af…", "tuner tuning…"), C["amber"])
            self.root.after(800, lambda: self.civ and self.civ.send(0x1C, b"\x01"))

    def open_manual(self):
        fn = "HANDLEIDING.html" if self.lang == "nl" else "MANUAL.html"
        for base in (os.path.join(APP_DIR, "docs"), os.path.join(os.path.dirname(APP_DIR), "docs")):
            p = os.path.join(base, fn)
            if os.path.exists(p):
                webbrowser.open("file:///" + p.replace(os.sep, "/"))
                return
        webbrowser.open(f"{REPO_URL}/blob/main/docs/{fn.replace('.html', '.md')}")

    def _send_bkin(self):
        if self.civ:
            self.civ.send(0x16, b"\x47" + (b"\x01" if self.bkin_var.get() else b"\x00"))

    def send_wpm(self):
        try:
            w = min(max(int(self.wpm_var.get()), 6), 48)
        except (ValueError, tk.TclError):
            return
        if self.civ:
            self.civ.send(0x14, b"\x0C" + int_to_bcd_be(int(round((w - 6) * 255 / 42)), 2))

    def _expand(self, text):
        c = self.cfg
        return (text.replace("{MYCALL}", c.get("mycall", "").upper())
                    .replace("{MYNAME}", c.get("myname", "").upper())
                    .replace("{MYQTH}", c.get("myqth", "").upper())
                    .replace("{CALL}", self.call_var.get().upper())
                    .replace("{NAME}", self.hisname_var.get().upper())
                    .replace("{RST}", self.rst_var.get().upper()))

    def _check_tx(self):
        if not self.civ or self.detecting:
            self._set_status(self.t("eerst radio verbinden", "connect the radio first"), C["red"])
            return False
        if not self.cfg.get("mycall"):
            self._set_status(self.t("vul eerst je call in bij Instellingen", "enter your call in Settings first"), C["red"])
            return False
        if self.mode and not self.mode.startswith("CW"):
            self.set_mode(0x03)
        return True

    def macro(self, key):
        if self._check_tx():
            self.cq_active = (key == "F1")
            self.sender.enqueue(self._expand(self.cfg["macros"][key][1]))
        return "break"

    def _cq_again(self):
        if self.cq_active and self.cqrep_var.get() and not self.sender.busy and self.civ:
            self.sender.enqueue(self._expand(self.cfg["macros"]["F1"][1]))

    def send_line(self):
        tx = self.tx_var.get()
        self.tx_var.set("")
        if tx.strip() and self._check_tx():
            self.cq_active = False
            self.sender.enqueue(self._expand(tx))

    def _space_key(self, ev):
        if self.live_var.get():
            self.root.after(1, self.send_line)

    def stop_tx(self):
        self.cq_active = False
        self.sender.stop()
        self._set_tx(False)
        if self.audio:
            self.audio.decoder.muted = False

    def _click_call(self, ev):
        idx = self.txt.index(f"@{ev.x},{ev.y}")
        rng = self.txt.tag_prevrange("call", idx + "+1c")
        if rng:
            self.call_var.set(self.txt.get(*rng).strip().upper())
        return "break"

    def _grab_call(self, ev):
        idx = f"@{ev.x},{ev.y}"
        a = self.txt.index(f"{idx} wordstart")
        line = self.txt.get(f"{a} linestart", f"{a} lineend")
        col = int(a.split(".")[1])
        s_, e_ = col, col
        while s_ > 0 and (line[s_ - 1].isalnum() or line[s_ - 1] == "/"):
            s_ -= 1
        while e_ < len(line) and (line[e_].isalnum() or line[e_] == "/"):
            e_ += 1
        if line[s_:e_]:
            self.call_var.set(line[s_:e_].upper())
        return "break"

    def qrz_lookup(self):
        call = self.call_var.get().strip().upper()
        if call:
            webbrowser.open(f"https://www.qrz.com/db/{call}")

    # ---------- update-controle
    def check_update_async(self):
        if not self.cfg.get("check_updates", True):
            return

        def work():
            try:
                info = json.loads(http_get(RELEASE_API).decode("utf-8"))
                tag = info.get("tag_name", "")
                if tag and version_tuple(tag) > version_tuple(APP_VERSION):
                    self.gq.put(("update", {"version": tag.lstrip("vV"),
                                            "url": info.get("html_url") or f"{REPO_URL}/releases/latest"}))
            except Exception as e:
                log_error("update-check", e)
        threading.Thread(target=work, daemon=True).start()

    def _show_update_button(self):
        if self.update_info and self.upd_btn.winfo_exists():
            self.upd_btn.config(text="⬆ " + self.t(f"Nieuwe versie {self.update_info['version']}",
                                                  f"New version {self.update_info['version']}"))
            self.upd_btn.set_active(True, C["acc2"])
            self.upd_btn.pack(side="left", padx=(8, 0))

    def _ask_update(self):
        v = self.update_info["version"]
        if self.cfg.get("update_asked") == v:
            return
        self.cfg["update_asked"] = v
        self._save_cfg()
        if messagebox.askyesno(self.t("Update beschikbaar", "Update available"), self.t(
                f"Er is een nieuwe versie van CW Station beschikbaar: {v}\n(jij hebt {APP_VERSION}).\n\n"
                "Wil je de downloadpagina openen?",
                f"A new version of CW Station is available: {v}\n(you have {APP_VERSION}).\n\n"
                "Open the download page?"), parent=self.root):
            self._open_update()

    def _open_update(self):
        if self.update_info:
            webbrowser.open(self.update_info["url"])

    # ---------- audio-diagnose
    def _audio_check(self, now):
        a = self.audio
        if not a:
            self._silent_since = None
            return
        if a.error and not getattr(self, "_err_shown", False):
            self._err_shown = True
            self._set_status(self.t(f"audiofout: {a.error} (zie error.log)", f"audio error: {a.error} (see error.log)"),
                             C["red"])
        if a.blocks == 0 or a.level_db < -100:
            if self._silent_since is None:
                self._silent_since = now
            elif now - self._silent_since > 3 and not getattr(self, "_silence_shown", False):
                self._silence_shown = True
                self._set_status(self.t(
                    "Audio: geen geluid ontvangen – klik hier voor Windows-microfoontoegang",
                    "Audio: no sound received – click here for Windows microphone access"), C["red"])
                self._status_action = "mic"
        else:
            self._silent_since = None
            if getattr(self, "_silence_shown", False):
                self._silence_shown = False
                self._status_action = None
                self._set_status(self.t("Audio ontvangen", "Audio received"), C["green"])

    def _status_click(self, ev=None):
        if getattr(self, "_status_action", None) == "mic":
            webbrowser.open("ms-settings:privacy-microphone")

    # ---------- decoder-hulp (linksonder)
    ABBR = [("73", "groeten", "best regards"), ("88", "liefs", "love and kisses"), ("AGN", "nog eens", "again"),
            ("ANT", "antenne", "antenna"), ("BK", "onderbreken", "break"), ("CFM", "bevestig", "confirm"),
            ("CQ", "algemene oproep", "calling any station"), ("CUL", "tot later", "see you later"),
            ("DE", "van", "from"), ("DR", "beste", "dear"), ("ES", "en", "and"), ("FB", "prima", "fine business"),
            ("FER", "voor", "for"), ("GA", "goedemiddag", "good afternoon"), ("GE", "goedenavond", "good evening"),
            ("GM", "goedemorgen", "good morning"), ("GL", "succes", "good luck"), ("HI", "lach", "laughter"),
            ("HR", "hier", "here"), ("HW?", "hoe ontvangen?", "how copy?"), ("K", "ga je gang", "over"),
            ("KN", "alleen jij", "over, only you"), ("NR", "nummer", "number"), ("OM", "beste man", "old man"),
            ("OP", "operator", "operator"), ("PSE", "alsjeblieft", "please"), ("PWR", "vermogen", "power"),
            ("QRL?", "is de frequentie vrij?", "is the frequency busy?"), ("QRM", "storing (station)", "interference"),
            ("QRN", "atmosferische ruis", "static"), ("QRP", "laag vermogen", "low power"),
            ("QRQ", "sneller seinen", "send faster"), ("QRS", "langzamer seinen", "send slower"),
            ("QRZ?", "wie roept mij?", "who is calling me?"), ("QSB", "fading", "fading"),
            ("QSL", "bevestiging", "confirmation"), ("QSO", "verbinding", "contact"),
            ("QSY", "andere frequentie", "change frequency"), ("QTH", "locatie", "location"),
            ("R", "ontvangen", "received"), ("RIG", "apparatuur", "equipment"), ("RST", "rapport", "report"),
            ("SK", "einde verbinding", "end of contact"), ("TNX/TU", "bedankt", "thanks"),
            ("UR", "je / jouw", "your / you're"), ("VY", "zeer", "very"), ("WX", "weer", "weather"),
            ("5NN", "599", "599")]

    def _tool_tab(self, key):
        self.tool_tab = key
        for k, bt in self.tool_btns.items():
            bt.set_active(k == key)
        for w in self.tool_body.winfo_children():
            w.destroy()
        b = self.tool_body
        t = self.t
        if key == "dec":
            top = tk.Frame(b, bg=C["panel"])
            top.pack(fill="x")
            self.td_wpm = tk.Label(top, text="--", bg=C["panel"], fg=C["acc"], font=(DIGIT, 22, "bold"), width=3)
            self.td_wpm.pack(side="left")
            label(top, "WPM", font=(UI, 9, "bold")).pack(side="left", anchor="s", pady=(0, 6))
            self.td_code = tk.Label(top, text="", bg=C["panel"], fg=C["text"], font=(MONO, 16, "bold"), width=7,
                                    anchor="e")
            self.td_code.pack(side="right")
            grid = tk.Frame(b, bg=C["panel"])
            grid.pack(fill="x", pady=(0, 4))
            self.td = {}
            for i, (k, nl, en) in enumerate((("snr", "Signaal/ruis", "SNR"), ("dot", "Punt / streep", "Dit / dah"),
                                             ("wt", "Verhouding", "Weight"), ("gap", "Letter- / woordspatie", "Char / word gap"))):
                label(grid, t(nl, en), font=(UI, 8)).grid(row=i, column=0, sticky="w")
                v = label(grid, "--", fg=C["text"], font=(UI, 9, "bold"))
                v.grid(row=i, column=1, sticky="e", padx=(10, 0))
                self.td[k] = v
            grid.columnconfigure(1, weight=1)
            bar = tk.Frame(b, bg=C["panel"])
            bar.pack(fill="x")
            FlatButton(bar, t("Neem snelheid over", "Match speed"), command=self._match_speed, padx=8, pady=3,
                       font=(UI, 9, "bold")).pack(side="left")
            FlatButton(bar, t("Reset decoder", "Reset decoder"), command=self._reset_decoder, padx=8, pady=3,
                       font=(UI, 9, "bold")).pack(side="left", padx=6)
        elif key == "morse":
            items = [(c, MORSE[c]) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"] + \
                    [(c, MORSE[c]) for c in "./?=,"] + [("AR", ".-.-."), ("SK", "...-.-"), ("KN", "-.--.")]
            g = tk.Frame(b, bg=C["panel"])
            g.pack(fill="both", expand=True)
            cols = 6
            rows = (len(items) + cols - 1) // cols
            for i, (ch, code) in enumerate(items):
                r_, c_ = i % rows, i // rows
                cell = tk.Frame(g, bg=C["panel"])
                cell.grid(row=r_, column=c_, sticky="w", padx=(0, 6))
                tk.Label(cell, text=ch, bg=C["panel"], fg=C["acc"], font=(MONO, 9, "bold"), width=2,
                         anchor="w").pack(side="left")
                tk.Label(cell, text=code.replace(".", "·").replace("-", "–"), bg=C["panel"], fg=C["text"],
                         font=(MONO, 9), anchor="w").pack(side="left")
        else:
            tf = tk.Frame(b, bg=C["panel"])
            tf.pack(fill="both", expand=True)
            txt = tk.Text(tf, bg=C["panel"], fg=C["text"], relief="flat", font=(UI, 9), wrap="none",
                          height=8, highlightthickness=0, padx=2)
            sb = ttk.Scrollbar(tf, orient="vertical", command=txt.yview)
            txt.config(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            txt.pack(side="left", fill="both", expand=True)
            txt.tag_config("k", foreground=C["acc"], font=(MONO, 9, "bold"))
            for ab, nl, en in self.ABBR:
                txt.insert("end", f"{ab:<7}", "k")
                txt.insert("end", (nl if self.lang == "nl" else en) + "\n")
            txt.config(state="disabled")
        b.update_idletasks()

    def _tool_refresh(self, now):
        if self.tool_tab != "dec" or now - getattr(self, "_td_t", 0) < 0.3:
            return
        self._td_t = now
        if not getattr(self, "td_wpm", None) or not self.td_wpm.winfo_exists():
            return
        if not self.audio:
            self.td_wpm.config(text="--")
            return
        d = self.audio.decoder
        self.td_wpm.config(text=f"{d.wpm:.0f}")
        self.td_code.config(text=(d.code or "").replace(".", "·").replace("-", "–"))
        if d.noise > 1e-7 and d.peak > d.noise:
            snr = min(20 * math.log10(d.peak / d.noise), 60)
            self.td["snr"].config(text=f"{snr:.0f} dB")
        else:
            self.td["snr"].config(text="--")
        self.td["dot"].config(text=f"{d.dot * 1000:.0f} / {d.dash * 1000:.0f} ms")
        self.td["wt"].config(text=f"1 : {d.dash / max(d.dot, 1e-3):.1f}")
        self.td["gap"].config(text=f"{d.cg / max(d.dot, 1e-3):.1f} / {d.wg / max(d.dot, 1e-3):.1f} " +
                              self.t("punten", "dits"))

    def _match_speed(self):
        if self.audio:
            self.wpm_var.set(int(min(max(round(self.audio.decoder.wpm), 6), 48)))
            self.send_wpm()

    def _reset_decoder(self):
        if self.audio:
            d = self.audio.decoder
            dit = 1.2 / max(self.wpm_var.get(), 6)
            d.dot, d.dash, d.ie, d.cg, d.wg = dit, 3 * dit, dit, 3 * dit, 7 * dit
            d.marks, d.gaps, d.code = [], [], ""

    # ---------- enquête
    def open_survey(self):
        self.cfg["survey_asked"] = True
        webbrowser.open(f"{SURVEY_URL}?lang={self.lang}&v={APP_VERSION}")

    def maybe_ask_survey(self):
        """Na de 5e start één keer vriendelijk vragen om de enquête in te vullen."""
        self.cfg["starts"] = int(self.cfg.get("starts", 0)) + 1
        self._save_cfg()
        if self.cfg["starts"] >= 5 and not self.cfg.get("survey_asked"):
            self.cfg["survey_asked"] = True
            self._save_cfg()
            if messagebox.askyesno(self.t("Enquête", "Survey"), self.t(
                    "Je gebruikt CW Station nu een tijdje. Wil je een korte enquête invullen (ca. 2 minuten)?\n\n"
                    "Je bevindingen helpen om het programma te verbeteren. "
                    "Later kan het ook via de knop 'Enquête'.",
                    "You have been using CW Station for a while. Would you like to fill in a short survey "
                    "(about 2 minutes)?\n\nYour findings help to improve the program. "
                    "You can also use the 'Survey' button later."), parent=self.root):
                self.open_survey()

    # ---------- logboek
    def log_qso(self):
        call = self.call_var.get().strip().upper()
        if not call:
            self._set_status(self.t("geen call ingevuld", "no call entered"), C["amber"])
            return "break"
        band = ""
        for k, (lo, hi) in BAND_RANGES.items():
            if lo <= self.freq <= hi:
                band = f"{k}m"
        now = time.gmtime()
        rec = {"CALL": call, "QSO_DATE": time.strftime("%Y%m%d", now), "TIME_ON": time.strftime("%H%M%S", now),
               "BAND": band, "FREQ": f"{self.freq / 1e6:.6f}" if self.freq else "", "MODE": "CW",
               "RST_SENT": self.rst_var.get(), "RST_RCVD": self.rstr_var.get(),
               "NAME": self.hisname_var.get().strip(), "STATION_CALLSIGN": self.cfg.get("mycall", "").upper()}
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            append_qso(LOG_FILE, rec)
        except OSError as e:
            messagebox.showerror(self.t("Logboek", "Logbook"), str(e))
            return "break"
        self.call_var.set("")
        self.hisname_var.set("")
        self.rstr_var.set("599")
        self._set_status(self.t(f"QSO met {call} gelogd", f"QSO with {call} logged"), C["green"])
        return "break"

    def show_log(self):
        t = self.t
        w = tk.Toplevel(self.root)
        w.title(t("Logboek", "Logbook"))
        w.configure(bg=C["bg"])
        w.geometry("900x520")
        f, b, head = panel(w, t("LOGBOEK", "LOGBOOK") + f"  ·  {LOG_FILE}")
        f.pack(fill="both", expand=True, padx=10, pady=10)
        cols = ("date", "time", "call", "band", "freq", "rsts", "rstr", "name")
        tree = ttk.Treeview(b, columns=cols, show="headings")
        for c_, w_, h_ in (("date", 90, t("Datum", "Date")), ("time", 70, "UTC"), ("call", 110, "Call"),
                           ("band", 60, "Band"), ("freq", 100, "MHz"), ("rsts", 60, "RST snt"),
                           ("rstr", 60, "RST rcv"), ("name", 160, t("Naam", "Name"))):
            tree.heading(c_, text=h_, anchor="w")
            tree.column(c_, width=w_, anchor="w")
        sb = ttk.Scrollbar(b, orient="vertical", command=tree.yview)
        tree.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        recs = read_adif(LOG_FILE)
        for q in reversed(recs):
            d = q.get("QSO_DATE", "")
            tm = q.get("TIME_ON", "")
            tree.insert("", "end", values=(f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d,
                                           f"{tm[:2]}:{tm[2:4]}" if len(tm) >= 4 else tm, q.get("CALL", ""),
                                           q.get("BAND", ""), q.get("FREQ", ""), q.get("RST_SENT", ""),
                                           q.get("RST_RCVD", ""), q.get("NAME", "")))
        bar = tk.Frame(w, bg=C["bg"])
        bar.pack(fill="x", padx=10, pady=(0, 10))
        label(bar, t(f"{len(recs)} QSO's", f"{len(recs)} QSOs"), font=(UI, 10)).pack(side="left")

        def export():
            from tkinter import filedialog
            p = filedialog.asksaveasfilename(parent=w, defaultextension=".adi", initialfile="cwstation_log.adi",
                                             filetypes=[("ADIF", "*.adi *.adif")])
            if p:
                import shutil
                shutil.copyfile(LOG_FILE, p)

        def open_dir():
            try:
                os.startfile(DATA_DIR)
            except Exception:
                webbrowser.open("file://" + DATA_DIR)
        FlatButton(bar, t("Sluiten", "Close"), command=w.destroy).pack(side="right")
        if recs:
            FlatButton(bar, t("Exporteer ADIF…", "Export ADIF…"), command=export).pack(side="right", padx=6)
        FlatButton(bar, t("Open map", "Open folder"), command=open_dir).pack(side="right")

    # ---------- instellingen
    def show_settings(self):
        t = self.t
        w = tk.Toplevel(self.root)
        w.title(t("Instellingen", "Settings"))
        w.configure(bg=C["bg"])
        w.transient(self.root)
        f, b, _ = panel(w, t("ALGEMEEN", "GENERAL"))
        f.pack(fill="x", padx=12, pady=(12, 6))
        lang_v = tk.StringVar(value="Nederlands" if self.lang == "nl" else "English")
        tname = (lambda k: THEME_NL[k]) if self.lang == "nl" else (lambda k: k)
        theme_v = tk.StringVar(value=tname(self.cfg.get("theme", "Amber")))
        call_v = tk.StringVar(value=self.cfg.get("mycall", ""))
        name_v = tk.StringVar(value=self.cfg.get("myname", ""))
        qth_v = tk.StringVar(value=self.cfg.get("myqth", ""))
        cq_v = tk.StringVar(value=str(self.cfg.get("cq_repeat", 8)))
        grid = [(t("Taal", "Language"), ttk.Combobox(b, textvariable=lang_v, state="readonly", width=14,
                                                    values=["Nederlands", "English"])),
                (t("Kleur", "Colour"), ttk.Combobox(b, textvariable=theme_v, state="readonly", width=14,
                                                    values=[tname(k) for k in THEMES])),
                (t("Mijn call", "My call"), entry(b, call_v, 14)),
                (t("Mijn naam", "My name"), entry(b, name_v, 14)),
                (t("Mijn QTH", "My QTH"), entry(b, qth_v, 14)),
                (t("CQ-herhaling (s)", "CQ repeat (s)"), entry(b, cq_v, 5)),
                (t("Updates", "Updates"), FlatButton(b, t("Automatisch controleren", "Check automatically"),
                                                     var=self.upd_var, padx=8, pady=2, font=(UI, 9, "bold")))]
        for i, (txt_, wd) in enumerate(grid):
            label(b, txt_, font=(UI, 10)).grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 8), pady=4)
            wd.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 24), pady=4)

        f, b, _ = panel(w, t("MACRO'S  ·  {MYCALL} {CALL} {RST} {NAME} {MYNAME} {MYQTH}  ·  prosigns <AR> <SK> <KN> <BT>",
                             "MACROS  ·  {MYCALL} {CALL} {RST} {NAME} {MYNAME} {MYQTH}  ·  prosigns <AR> <SK> <KN> <BT>"))
        f.pack(fill="both", expand=True, padx=12, pady=6)
        mvars = {}
        for i, key in enumerate(sorted(self.cfg["macros"], key=lambda k: int(k[1:]))):
            lbl_, txt_ = self.cfg["macros"][key]
            lv, tv = tk.StringVar(value=lbl_), tk.StringVar(value=txt_)
            mvars[key] = (lv, tv)
            label(b, key, fg=C["acc"], font=(UI, 10, "bold")).grid(row=i, column=0, sticky="w", pady=3)
            entry(b, lv, 9).grid(row=i, column=1, sticky="w", padx=6, pady=3)
            entry(b, tv, 70, font=(MONO, 10)).grid(row=i, column=2, sticky="we", pady=3)
        b.columnconfigure(2, weight=1)

        bar = tk.Frame(w, bg=C["bg"])
        bar.pack(fill="x", padx=12, pady=(6, 12))

        def save():
            self.lang = "nl" if lang_v.get() == "Nederlands" else "en"
            try:
                cq = max(2, int(float(cq_v.get())))
            except ValueError:
                cq = 8
            theme = next((k for k in THEMES if tname(k) == theme_v.get()), "Amber")
            self.cfg["check_updates"] = bool(self.upd_var.get())
            self.cfg.update(theme=theme, mycall=call_v.get().strip().upper(),
                            myname=name_v.get().strip(), myqth=qth_v.get().strip(), cq_repeat=cq, lang=self.lang)
            for k, (lv, tv) in mvars.items():
                self.cfg["macros"][k] = [lv.get().strip() or k, tv.get()]
            self._save_cfg()
            w.destroy()
            self.rebuild()
        FlatButton(bar, t("Opslaan", "Save"), command=save, accent=C["acc"]).pack(side="right")
        FlatButton(bar, t("Annuleren", "Cancel"), command=w.destroy).pack(side="right", padx=6)
        label(bar, f"{APP_NAME} {APP_VERSION}  ·  MIT License  ·  " +
              t("niet gelieerd aan Icom Inc.", "not affiliated with Icom Inc."), font=(UI, 8), bg=C["bg"]).pack(side="left")
        w.grab_set()

    def _quit(self):
        self._save_cfg()
        self.sender.stop()
        if self.audio:
            self.audio.close()
        self._disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    root.geometry("1560x1000")
    try:
        root.state("zoomed")
    except tk.TclError:
        pass
    root.minsize(1280, 860)
    app = App(root)
    if not app.cfg.get("mycall"):
        root.after(600, app.show_settings)
    else:
        root.after(4000, app.maybe_ask_survey)
    root.after(3000, app.check_update_async)
    root.mainloop()


if __name__ == "__main__":
    main()
