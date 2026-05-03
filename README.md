# iMac A2115 2019 — Linux Audio Setup

[![Stand With Ukraine](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/badges/StandWithUkraine.svg)](#support-ukraine)

Full audio setup for the **iMac 27" A2115 (2019)** running Linux.  
Covers kernel driver installation + 4-speaker PipeWire DSP with hardware-accurate crossover and EQ derived from Apple's own speaker tuning data.

> Tested on Pop!_OS 22.04. Should work on any Ubuntu 22.04+ or Debian-based distro with systemd + PipeWire.

---

## Disclaimer

**This project comes with no guarantees of correctness, safety, or sound quality on hardware other than the specific machine it was tested on.**

- The author has no formal background in low-level audio engineering, DSP, or kernel driver development. This project was built by reading existing work, extracting Apple's and Cirrus Logic's own calibration data, and applying it with help from [Claude Code](https://claude.ai/code) (model: `claude-sonnet-4-6`).
- All EQ parameters are derived directly from **Apple's macOS speaker tuning files** (AID20 `PressureResponse` FIR) and **Cirrus Logic's official BootCamp Windows driver** (`cs4208_38.inf`). No values were invented or guessed — they reflect Apple's and Cirrus's own factory measurements for this specific hardware.
- Sound quality was **subjectively evaluated** by the author on one iMac A2115 2019. There is no claim of objective accuracy or 100% parity with macOS. What you hear may differ depending on your room, your ears, and your unit's hardware tolerances.
- This has only been tested on **iMac 27" A2115 (2019)**. It will likely not work correctly on other iMac models, and definitely not on unrelated hardware.
- The kernel driver dependency ([davidjo/snd_hda_macbookpro](https://github.com/davidjo/snd_hda_macbookpro)) is an out-of-tree module — it may break with kernel updates.

If you are an audio engineer or DSP developer and spot something wrong, pull requests are very welcome.

---

## The problem

By default, Linux does not produce any sound on this iMac.  
Cause: the upstream kernel driver does not correctly initialise the **Cirrus Logic CS8409** HDA bridge + **CS42L83** DAC codec.

Additionally, the iMac has **4 physical speakers** (2 tweeters + 2 woofers) wired as a 4-channel surround output. Without a proper crossover and per-speaker EQ, even after getting basic sound working, the audio quality is poor — bass goes to tweeters, no crossover, no hardware correction.

This repo solves both problems.

---

## What this does

1. **Installs the out-of-tree kernel driver** (`snd_hda_macbookpro` by davidjo) via DKMS.  
   This is the only driver that correctly initialises CS8409/CS42L83 on iMac A2115.

2. **Configures a PipeWire filter-chain DSP** that:
   - Activates the `analog-surround-40` ALSA profile (exposes all 4 speakers)
   - Applies a 4th-order Linkwitz-Riley crossover at 800 Hz
   - Applies per-speaker parametric EQ: woofer path from Apple's AID20 acoustic tuning data; tweeter path from Cirrus BootCamp driver (`CONF_0911`)
   - Creates a virtual stereo sink `imac_dsp_in` — apps see normal stereo, DSP handles the rest

3. **Sets up a systemd user service** that applies settings automatically on every boot.

### Signal chain (v1.3)

```
App (stereo) → imac_dsp_in (virtual sink)
  → Pre-gain  -12 dB  (headroom for woofer +11.4 dB flow boost)
  → Fan-out ──┬── Woofer L/R:  LPF 800 Hz (4th-order LR) → flow PEQ (6 bands) → RL/RR
              └── Tweeter L/R: +6 dB gain → CONF_0911 PEQ (7 bands) → FL/FR
  → alsa_output ... analog-surround-40 (4-channel hardware output)
```

Channel mapping on `analog-surround-40`:
| ALSA channel | Position | Physical speaker |
|---|---|---|
| 0 | FL | Left tweeter |
| 1 | FR | Right tweeter |
| 2 | RL | Left woofer |
| 3 | RR | Right woofer |

---

## Quick install

```bash
git clone https://github.com/MrHogun/imac-a2115-linux-audio
cd imac-a2115-linux-audio
./install.sh
```

The script will:
- Install build dependencies
- Clone and install the kernel driver via DKMS
- Ask if you want to reboot (needed after driver install)
- After reboot, run `./install.sh` again — it skips the driver step and applies the PipeWire config

---

## Manual install (step by step)

### Step 1 — Kernel driver

```bash
sudo apt install git dkms linux-headers-$(uname -r) build-essential

git clone --depth=1 https://github.com/davidjo/snd_hda_macbookpro
cd snd_hda_macbookpro
sudo ./install.cirrus.driver.sh

sudo reboot
```

After reboot, verify the driver loaded:
```bash
dmesg | grep -i "cs8409\|cs42l83\|APPLE\|cirrus"
# You should see lines like:
# cs8409 ... APPLE (Subsystem ID 0x106b1000) — this is correct, not an error
```

If you see `patch_cs8409 NOT FOUND trying APPLE` — that is **not an error**, it means the driver is using the correct Apple-specific initialisation path.

### Step 2 — PipeWire DSP filter-chain

```bash
mkdir -p ~/.config/pipewire/pipewire.conf.d
cp config/pipewire/99-imac-dsp.conf ~/.config/pipewire/pipewire.conf.d/
```

### Step 3 — WirePlumber profile rule

Forces the `analog-surround-40` profile to activate automatically:

```bash
mkdir -p ~/.config/wireplumber/wireplumber.conf.d
cp config/wireplumber/51-imac-surround.conf ~/.config/wireplumber/wireplumber.conf.d/
```

### Step 4 — Systemd user service

Sets the card profile and default sink on every boot:

```bash
mkdir -p ~/.config/systemd/user
cp config/systemd/imac-audio.service ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable imac-audio.service
```

### Step 5 — Apply now (without reboot)

```bash
pactl set-card-profile alsa_card.pci-0000_00_1f.3 output:analog-surround-40+input:analog-stereo
systemctl --user restart pipewire wireplumber pipewire-pulse
sleep 3
pactl set-default-sink imac_dsp_in
pactl set-sink-volume imac_dsp_in 65536
```

---

## Verification

```bash
# Check that the DSP virtual sink exists
pactl list sinks short
# Should show: imac_dsp_in  ...  IDLE/RUNNING

# Check default sink
pactl info | grep "Default Sink"
# Should show: Default Sink: imac_dsp_in

# Check card profile
pactl list cards | grep -A 20 alsa_card.pci-0000_00_1f.3 | grep "Active Profile"
# Should show: output:analog-surround-40+input:analog-stereo
```

---

## Troubleshooting

**No sound at all after driver install:**
- Check `dmesg | grep -i cs8409` — driver must be loaded
- Check `aplay -l` — you should see the HDA Intel PCH card
- If the card is not listed, the driver did not load: `sudo modprobe snd_hda_intel`

**`imac_dsp_in` sink not appearing:**
- The filter-chain requires the `analog-surround-40` profile to be active first
- Run: `pactl set-card-profile alsa_card.pci-0000_00_1f.3 output:analog-surround-40+input:analog-stereo`
- Then restart PipeWire: `systemctl --user restart pipewire wireplumber pipewire-pulse`

**Sound plays but only from 2 speakers:**
- Check the active profile: `pactl list cards | grep -A 20 alsa_card.pci-0000_00_1f.3`
- If it shows `output:analog-stereo` instead of `surround-40`, force it with pactl (see above)

**Volume seems very quiet after restart:**
- The pre-gain is -12 dB; always set volume to 100% after PipeWire restart:
  `pactl set-sink-volume imac_dsp_in 65536`

**Service not starting on boot:**
- Check: `systemctl --user status imac-audio.service`
- Check: `journalctl --user -u imac-audio.service`
- The service waits 4 seconds for PipeWire to be ready; if your system is slow, increase `ExecStartPre=/bin/sleep 4` to `sleep 8`

---

## Files

```
imac-a2115-linux-audio/
├── install.sh                              — automated install script
├── gen_dsp_conf.py                         — Python script to regenerate the DSP config
├── README.md
└── config/
    ├── pipewire/
    │   └── 99-imac-dsp.conf               — PipeWire filter-chain (crossover + EQ)
    ├── wireplumber/
    │   └── 51-imac-surround.conf          — WirePlumber rule: force surround-40 profile
    └── systemd/
        └── imac-audio.service             — user service: apply settings on boot
```

### Regenerating the DSP config

If you want to modify EQ values or the crossover frequency:

```bash
# Edit gen_dsp_conf.py, then:
python3 gen_dsp_conf.py
# Outputs to ~/.config/pipewire/pipewire.conf.d/99-imac-dsp.conf

systemctl --user restart pipewire pipewire-pulse
pactl set-sink-volume imac_dsp_in 65536
```

---

## Technical notes

### Why this driver?

The upstream `snd_hda_intel` + `snd_hda_codec_cs8409` module in the mainline kernel does not properly configure the CS8409 HDA bridge for the iMac A2115. The [davidjo/snd_hda_macbookpro](https://github.com/davidjo/snd_hda_macbookpro) out-of-tree driver includes the correct firmware and patch tables for Apple hardware including the iMac A2115 (subsystem ID `0x106B1000`).

---

### Woofer EQ: derived from Apple AID20 acoustic tuning data (v1.3)

**AID20** is Apple's internal Acoustic ID for the iMac A2115. Apple ships speaker tuning data at:
```
/System/Library/Audio/Tunings/AID20/DSP/Strips/aid20-aufx-flow-appl.plist
```

This plist is processed by Apple's proprietary `aufx-flow` AudioUnit, which applies an acoustic correction to each speaker. The key field is `ChannelData[n].PressureResponse` — a **1024-tap FIR filter at 48 kHz** representing the measured in-situ acoustic impulse response of each speaker.

**How the correction is derived:**

The `flow` AU computes the minimum-phase inverse of the `PressureResponse` FIR and applies it as a correction filter. Applying the inverse of the measured acoustic response makes each speaker's output flat (equal contribution at every frequency in its operating range).

To approximate this in PipeWire (which uses biquad filters, not FIR), we:

1. Compute the DTFT of the 1024-tap `PressureResponse` FIR to get the measured woofer frequency response
2. Invert it (negate the dB values, normalize to 0 dB at 1 kHz) to get the target correction curve
3. Fit a set of biquad peaking filters to approximate that curve in the 150–800 Hz range (the woofer's operating range below the 800 Hz LPF crossover)

**Target correction curve** (inverse of PR0, normalized to 0 dB @ 1 kHz):

| Frequency | Apple target | Our biquad fit |
|-----------|-------------|----------------|
| 200 Hz    | +1.7 dB     | +1.8 dB        |
| 300 Hz    | +4.4 dB     | +3.9 dB        |
| 400 Hz    | +8.3 dB     | +8.3 dB        |
| 500 Hz    | +14.0 dB    | +12.8 dB       |
| 600 Hz    | +12.8 dB    | +10.9 dB       |
| 700 Hz    | +9.0 dB     | +9.6 dB        |
| 800 Hz    | +6.8 dB     | +5.7 dB        |

The fit is within ±2 dB across 300–700 Hz. The 500–600 Hz region is slightly under-corrected (~1.5 dB) to avoid excessive cone excursion.

**Woofer biquad parameters (v1.3):**

| f0 (Hz) | Q    | Gain (dB) | Purpose                    |
|---------|------|-----------|----------------------------|
| 500     | 1.50 | +12.0     | Main flow correction peak  |
| 720     | 2.50 | +5.0      | 700–800 Hz shoulder        |
| 1050    | 2.50 | −8.0      | Valley at 1 kHz (ref point)|
| 1900    | 1.00 | +9.0      | 2 kHz bump                 |
| 2800    | 0.50 | −5.0      | 2.5–3 kHz cut              |
| 150     | 0.70 | +2.0      | Low shelf (gentle)         |

The `PressureResponse` ThieleSmall parameters from the same plist: `Bl=0.823 N/A`, `Kms=7902 N/m`, `Mms=0.748 g` → free-air resonance **f₀ ≈ 517 Hz**. This explains why the +14 dB correction peaks near 500 Hz — the woofer's acoustic output in the iMac enclosure dips sharply near its resonance frequency.

**Why CONF_0911 ch0 was removed (v1.3):**

`CONF_0911` comes from the Windows BootCamp APO (Audio Processing Object) in `cs4208_38.inf`. It was derived from the same woofer measurements but through a different pipeline and normalisation. Stacking both CONF_0911 and the flow correction would double-correct the same resonances. Since the flow data is directly from Apple's macOS tuning files, it takes priority.

---

### Tweeter EQ: CONF_0911 from Cirrus BootCamp driver

Source: `cs4208_38.inf`, subsystem `HDAUDIO VEN_1013&DEV_8409&SUBSYS_106B1000` (iMac A2115).

These are factory-measured biquad filters for the CS42L83 tweeter codec. The Linux driver does not program the CS42L83 hardware EQ registers (`EQ1S1R7`/`EQ1S2R7`), so those corrections are applied in software.

| f0 (Hz) | Q    | Gain (dB) | Note                        |
|---------|------|-----------|-----------------------------|
| 1031    | 0.36 | −17.67    | Tweeter cone resonance cut  |
| 1890    | 0.29 | +11.48    | Natural tweeter dip         |
| 3440    | 0.54 | −7.81     |                             |
| 1180    | 0.14 | −6.62     |                             |
| 1637    | 0.27 | +5.16     |                             |
| 4883    | 0.32 | +3.41     |                             |
| 9000    | 0.70 | +4.0      | CS42L83 HW EQ compensation (high shelf) |

The last band compensates for the CS42L83 hardware EQ registers that macOS programs but the Linux driver skips — they would add ~+8 dB above 9 kHz if active.

---

### Gain structure

The pre-gain of **−12 dB** is needed because the woofer flow correction peaks at **+11.4 dB** at 501 Hz. Without headroom, a 0 dBFS input would clip the DSP at that frequency.

The tweeter path only needs −6 dB headroom (its max boost is +4.5 dB at 15 kHz). To avoid making the tweeter 6 dB quieter than intended, a **+6 dB compensation node** (`tgL`/`tgR`, implemented as a high shelf at 30 Hz) sits at the start of each tweeter path:

```
pgL (−12 dB) ──┬──> woofer LPF → flow PEQ    (net headroom: −12 + 11.4 = −0.6 dBFS max)
               └──> tgL (+6 dB) → tweeter PEQ (net headroom: −12 + 6 + 4.5 = −1.5 dBFS max)
```

---

### Why no Dolby EQ?

The Dolby DAX3 XML from BootCamp contains a 20-band EQ, but it is one stage of a full Dolby pipeline (DRC, dynamics, virtualiser, volume leveller). Applying the EQ alone without the rest of the pipeline produces wrong tonal balance — primarily excessive brightness. The flow-derived woofer EQ + CONF_0911 tweeter EQ is the correct approach for flat, accurate reproduction.

---

## Acknowledgements

- [davidjo/snd_hda_macbookpro](https://github.com/davidjo/snd_hda_macbookpro) — kernel driver for CS8409/CS42L83 on Apple hardware (GPL-2.0)
- Apple Inc. — AID20 speaker tuning data extracted from macOS
- Cirrus Logic — CONF_0911 EQ parameters from official BootCamp Windows driver (`cs4208_38.inf`)
- [vshymanskyy/StandWithUkraine](https://github.com/vshymanskyy/StandWithUkraine) — Stand With Ukraine badge

---

## Version history

| Version | Change |
|---------|--------|
| v1.0 | Basic crossover only (LPF/HPF at 800 Hz) |
| v1.1 | Tweeter: CONF_0911 ch1 PEQ + CS42L83 HW EQ compensation shelf |
| v1.2 | Woofer: CONF_0911 ch0 + rough +7 dB bass shelf from AID20 PR[0] coefficient |
| v1.3 | Woofer: full biquad fit to AID20 PressureResponse DTFT inverse (Apple flow correction); tweeter gain compensation node added |

---

## 🇺🇦 Support Ukraine

If this project was useful to you, consider donating to one of these international humanitarian organizations operating in Ukraine. All listed organizations have a 4/4 rating on Charity Navigator.

| Organization | Focus | Link |
|---|---|---|
| **Médecins Sans Frontières (MSF)** | Medical care in conflict zones | [msf.org/ukraine](https://www.msf.org/ukraine) |
| **International Rescue Committee (IRC)** | Emergency relief, shelter, healthcare | [rescue.org/ukraine](https://www.rescue.org/ukraine) |
| **UNHCR** (UN Refugee Agency) | Refugees and displaced people | [donate.unhcr.org/ukraine](https://donate.unhcr.org/int/en/ukraine) |
| **Save the Children** | Children affected by conflict | [savethechildren.org](https://www.savethechildren.org/us/where-we-work/europe/ukraine) |

