#!/usr/bin/env bash
# iMac A2115 2019 — full audio setup for Linux
# Tested on: Pop!_OS 22.04 / Ubuntu 22.04+
# Run as normal user (NOT root). Will ask for sudo when needed.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
die()   { echo "[ERROR] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 0. Checks
# ---------------------------------------------------------------------------
[[ $EUID -eq 0 ]] && die "Do not run as root. Run as your normal user."

command -v pactl   >/dev/null || die "PipeWire/pulseaudio utils not found. Install pipewire-pulse."
command -v systemctl >/dev/null || die "systemd not found."

# ---------------------------------------------------------------------------
# 1. Install kernel driver (snd_hda_macbookpro by davidjo)
#    Needed because the upstream kernel driver does not initialise
#    the Cirrus CS8409 + CS42L83 codec correctly — no sound by default.
# ---------------------------------------------------------------------------
install_driver() {
    info "=== Step 1: kernel driver ==="

    if lsmod | grep -q snd_hda_cs_dsp_ctrlr 2>/dev/null; then
        info "Driver already loaded (snd_hda_cs_dsp_ctrlr). Skipping."
        return
    fi

    # Check if DKMS module is already installed
    if dkms status 2>/dev/null | grep -q "snd-hda-codec-cs8409"; then
        info "DKMS module already installed. Skipping driver build."
        return
    fi

    info "Installing build dependencies..."
    sudo apt-get update -qq
    sudo apt-get install -y git dkms linux-headers-"$(uname -r)" build-essential

    TMP=$(mktemp -d)
    info "Cloning davidjo/snd_hda_macbookpro into $TMP ..."
    git clone --depth=1 https://github.com/davidjo/snd_hda_macbookpro "$TMP/snd_hda_macbookpro"

    info "Running driver install script..."
    cd "$TMP/snd_hda_macbookpro"
    # The script handles DKMS registration + initramfs update
    sudo ./install.cirrus.driver.sh

    cd "$REPO_DIR"
    rm -rf "$TMP"

    info "Driver installed. A reboot may be required for the module to load."
    info "After reboot, re-run this script to continue with audio setup."

    read -rp "Reboot now? [y/N] " ans
    if [[ ${ans,,} == "y" ]]; then
        sudo reboot
    else
        warn "Skipping reboot. Continue at your own risk — driver may not be active yet."
    fi
}

# ---------------------------------------------------------------------------
# 2. Install PipeWire config files
# ---------------------------------------------------------------------------
install_pipewire_dsp() {
    info "=== Step 2: PipeWire DSP filter-chain ==="

    mkdir -p "$HOME/.config/pipewire/pipewire.conf.d"
    cp -v "$REPO_DIR/config/pipewire/99-imac-dsp.conf" \
          "$HOME/.config/pipewire/pipewire.conf.d/99-imac-dsp.conf"

    info "PipeWire DSP config installed."
}

# ---------------------------------------------------------------------------
# 3. Install WirePlumber rule (auto-sets surround-40 profile)
# ---------------------------------------------------------------------------
install_wireplumber() {
    info "=== Step 3: WirePlumber profile rule ==="

    mkdir -p "$HOME/.config/wireplumber/wireplumber.conf.d"
    cp -v "$REPO_DIR/config/wireplumber/51-imac-surround.conf" \
          "$HOME/.config/wireplumber/wireplumber.conf.d/51-imac-surround.conf"

    info "WirePlumber rule installed."
}

# ---------------------------------------------------------------------------
# 4. Install and enable systemd user service
# ---------------------------------------------------------------------------
install_service() {
    info "=== Step 4: systemd user service ==="

    mkdir -p "$HOME/.config/systemd/user"
    cp -v "$REPO_DIR/config/systemd/imac-audio.service" \
          "$HOME/.config/systemd/user/imac-audio.service"

    systemctl --user daemon-reload
    systemctl --user enable imac-audio.service
    info "Service enabled."
}

# ---------------------------------------------------------------------------
# 5. Apply settings immediately (no reboot needed after first time)
# ---------------------------------------------------------------------------
apply_now() {
    info "=== Step 5: applying settings ==="

    # Set surround-40 profile
    pactl set-card-profile alsa_card.pci-0000_00_1f.3 \
        output:analog-surround-40+input:analog-stereo 2>/dev/null || \
        warn "Could not set card profile — driver may not be loaded yet."

    # Restart audio stack so the new filter-chain config is loaded
    systemctl --user restart pipewire.service wireplumber.service pipewire-pulse.service
    sleep 3

    # Set DSP virtual sink as default
    pactl set-default-sink imac_dsp_in 2>/dev/null || \
        warn "DSP sink not found — check 'pactl list sinks short'"

    info "Done."
}

# ---------------------------------------------------------------------------
# Run all steps
# ---------------------------------------------------------------------------
install_driver
install_pipewire_dsp
install_wireplumber
install_service
apply_now

echo ""
echo "======================================================"
echo " iMac A2115 audio setup complete!"
echo " Default sink: imac_dsp_in (4-speaker DSP)"
echo " Test with: paplay /usr/share/sounds/freedesktop/stereo/audio-channel-front-left.oga"
echo "======================================================"
