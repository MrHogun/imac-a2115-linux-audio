# iMac A2115 2019 — Linux Audio Setup

Full audio setup for the **iMac 27" A2115 (2019)** running Linux.  
Covers kernel driver installation + 4-speaker PipeWire DSP with hardware-accurate crossover and EQ.

> Tested on Pop!_OS 22.04. Should work on any Ubuntu 22.04+ or Debian-based distro with systemd + PipeWire.

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
   - Applies per-speaker parametric EQ correction (`CONF_0911` from the official Cirrus BootCamp Windows driver `cs4208_38.inf`, subsystem `106B1000` = iMac A2115)
   - Creates a virtual stereo sink `imac_dsp_in` — apps see normal stereo, DSP handles the rest

3. **Sets up a systemd user service** that applies settings automatically on every boot.

### Signal chain

```
App (stereo) → imac_dsp_in (virtual sink)
  → Pre-gain  -6 dB  (headroom for PEQ boosts)
  → Fan-out ──┬── Woofer L/R:  LPF 800 Hz (4th-order) → 6-band PEQ → RL/RR
              └── Tweeter L/R: HPF 800 Hz (4th-order) → 6-band PEQ → FL/FR
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
git clone https://github.com/YOUR_USERNAME/imac-a2115-linux-audio
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

# Play test audio
paplay /usr/share/sounds/freedesktop/stereo/audio-channel-front-left.oga
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

systemctl --user restart pipewire wireplumber pipewire-pulse
```

---

## Technical notes

### Why this driver?

The upstream `snd_hda_intel` + `snd_hda_codec_cs8409` module in the mainline kernel does not properly configure the CS8409 HDA bridge for the iMac A2115. The [davidjo/snd_hda_macbookpro](https://github.com/davidjo/snd_hda_macbookpro) out-of-tree driver includes the correct firmware and patch tables for Apple hardware including the iMac A2115 (subsystem ID `0x106B1000`).

### Where do the EQ values come from?

The PEQ values (`CONF_0911`) come from `cs4208_38.inf` — the official Cirrus Logic Windows driver shipped with Apple BootCamp. This INF file contains factory-measured per-speaker biquad correction filters for the exact speakers used in this iMac. The subsystem ID `HDAUDIO VEN_1013&DEV_8409&SUBSYS_106B1000` uniquely identifies the iMac A2115 2019.

### Why no Dolby EQ?

The Dolby DAX3 XML file from BootCamp contains a 20-band EQ, but that is only one stage of a full Dolby pipeline (dynamics, DRC, virtualiser, volume leveller). Applying the EQ alone without the rest produces wrong tonal balance. The CONF_0911 hardware correction filters are sufficient for accurate reproduction.

### Why -6 dB pre-gain?

The tweeter PEQ has a +11.48 dB boost at 1890 Hz (compensating a natural dip in the tweeter response). Without headroom, a near-0 dBFS signal at that frequency would clip the DAC output. The -6 dB pre-gain ensures clean reproduction at all volumes.
