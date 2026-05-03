#!/usr/bin/env python3
"""Generate minimum-phase inverse FIR correction filters from AID20 data.

Outputs (all: N_TAPS-tap mono float32 WAV at 48 kHz):
  ~/.config/pipewire/woofer_ir_L.wav   — inverse of avg(PR_ch0, PR_ch1)  [woofer Left]
  ~/.config/pipewire/woofer_ir_R.wav   — same (PR ch0≈ch1, share one IR)
  ~/.config/pipewire/tweeter_ir_L.wav  — inverse of TweeterResponse[ch0]
  ~/.config/pipewire/tweeter_ir_R.wav  — inverse of TweeterResponse[ch1]

Minimum-phase → group delay ≈ 0 → no timing mismatch between woofer / tweeter paths.

Key fix: normalise to 0 dB at ref_hz BEFORE clamping ±max_boost_db.
"""

import json, os
import numpy as np
from scipy.io import wavfile

SR      = 48000
N_TAPS  = 4096
AID20   = "/media/mrhogun/JustDisk/aid20_full.json"
OUT_DIR = os.path.expanduser("~/.config/pipewire")


def target_mag_db(h_measured: np.ndarray,
                  max_boost_db: float,
                  hp_hz: float,
                  ref_hz: float = 1000.0) -> np.ndarray:
    N_est   = max(N_TAPS * 8, len(h_measured) * 8)
    H_est   = np.fft.rfft(h_measured, n=N_est)
    f_est   = np.fft.rfftfreq(N_est, 1.0 / SR)
    f_des   = np.fft.rfftfreq(N_TAPS, 1.0 / SR)
    mag     = np.interp(f_des, f_est, np.abs(H_est))

    mag_inv  = 1.0 / np.maximum(mag, 1e-12)
    ramp     = np.clip(f_des / hp_hz, 0.0, 1.0) ** 2
    mag_inv *= ramp

    ref_idx  = np.argmin(np.abs(f_des - ref_hz))
    mag_inv /= max(mag_inv[ref_idx], 1e-12)

    return np.clip(20.0 * np.log10(np.maximum(mag_inv, 1e-12)),
                   -max_boost_db, max_boost_db)


def min_phase_fir(mag_db: np.ndarray) -> np.ndarray:
    """Minimum-phase FIR from half-spectrum magnitude (dB, N_TAPS//2+1 values)."""
    mag_lin  = 10.0 ** (mag_db / 20.0)
    log_mag  = np.log(np.maximum(mag_lin, 1e-12))
    log_full = np.concatenate([log_mag, log_mag[-2:0:-1]])   # N_TAPS points
    cep      = np.fft.ifft(log_full).real

    win               = np.zeros(N_TAPS)
    win[0]            = 1.0
    win[1:N_TAPS // 2] = 2.0
    win[N_TAPS // 2]  = 1.0

    H_min = np.exp(np.fft.fft(cep * win))
    return np.fft.irfft(H_min[: N_TAPS // 2 + 1]).astype(np.float32)


def print_response(label: str, h: np.ndarray,
                   ideal_db: dict | None = None, ref_hz: float = 1000.0):
    H   = np.fft.rfft(h)
    f   = np.fft.rfftfreq(N_TAPS, 1.0 / SR)
    ref = np.abs(H[np.argmin(np.abs(f - ref_hz))])
    print(f"{label}:")
    for freq in [200, 500, 700, 800, 1000, 1500, 2000, 3000, 5000, 10000, 16000]:
        idx  = np.argmin(np.abs(f - freq))
        db   = 20.0 * np.log10(max(np.abs(H[idx]), 1e-12) / ref)
        note = ""
        if ideal_db and freq in ideal_db:
            exp  = ideal_db[freq]
            note = f"  (ideal {exp:+.1f}  err {db-exp:+.1f})"
        print(f"  {freq:6d} Hz  {db:+6.1f} dB{note}")
    print()


with open(AID20) as f:
    aid20 = json.load(f)
ch0, ch1 = aid20["ChannelData"][0], aid20["ChannelData"][1]

# --- Woofer: average ch0 + ch1 PressureResponse ---
pr_avg = (np.array(ch0["PressureResponse"]) + np.array(ch1["PressureResponse"])) / 2
woofer_mag = target_mag_db(pr_avg, max_boost_db=14.0, hp_hz=60.0)
h_woofer   = min_phase_fir(woofer_mag)

# Ideal: inverse of PressureResponse at key frequencies (re 1 kHz)
SR_N = SR; N_E = N_TAPS * 8
H_pr = np.fft.rfft(pr_avg, n=N_E); f_e = np.fft.rfftfreq(N_E, 1/SR_N)
ref_pr = np.abs(H_pr[np.argmin(np.abs(f_e - 1000))])
woofer_ideal = {}
for freq in [200, 500, 700, 800, 1000]:
    i = np.argmin(np.abs(f_e - freq))
    db = 20*np.log10(max(np.abs(H_pr[i]), 1e-12) / ref_pr)
    woofer_ideal[freq] = -db

print_response("Woofer FIR (avg ch0+ch1, min-phase, cap +14 dB)", h_woofer, woofer_ideal)

# --- Tweeter: separate ch0 (L) and ch1 (R) ---
tweeter_irs = {}
for chname, tr_data in [("L", ch0["TweeterResponse"]), ("R", ch1["TweeterResponse"])]:
    tr_arr      = np.array(tr_data)
    tween_mag   = target_mag_db(tr_arr, max_boost_db=18.0, hp_hz=800.0)
    h_tw        = min_phase_fir(tween_mag)
    tweeter_irs[chname] = h_tw

    # Ideal correction
    H_tr = np.fft.rfft(tr_arr, n=N_E)
    ref_tr = np.abs(H_tr[np.argmin(np.abs(f_e - 1000))])
    tw_ideal = {}
    for freq in [800, 1000, 1500, 2000, 3000, 5000, 10000, 16000]:
        i = np.argmin(np.abs(f_e - freq))
        db = 20*np.log10(max(np.abs(H_tr[i]), 1e-12) / ref_tr)
        tw_ideal[freq] = -db

    print_response(f"Tweeter FIR ch{chname} (min-phase, cap +18 dB)", h_tw, tw_ideal)

os.makedirs(OUT_DIR, exist_ok=True)
wavfile.write(f"{OUT_DIR}/woofer_ir_L.wav", SR, h_woofer)
wavfile.write(f"{OUT_DIR}/woofer_ir_R.wav", SR, h_woofer)
wavfile.write(f"{OUT_DIR}/tweeter_ir_L.wav", SR, tweeter_irs["L"])
wavfile.write(f"{OUT_DIR}/tweeter_ir_R.wav", SR, tweeter_irs["R"])
print("→ Written: woofer_ir_L.wav  woofer_ir_R.wav  tweeter_ir_L.wav  tweeter_ir_R.wav")
