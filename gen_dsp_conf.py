#!/usr/bin/env python3
"""Generate PipeWire filter-chain config for iMac A2115 2019 4-speaker DSP.

Signal chain:
  Input stereo (L, R)
  -> Pre-gain -12 dB (headroom; woofer flow path peaks at +11.4 dB)
  -> Fan-out: woofer path + tweeter path (PipeWire handles fan-out natively)
     Woofer  L/R: 2x LPF @800 Hz (4th-order Linkwitz-Riley)
               -> AID20 'flow' PEQ (5 peaking + 1 lowshelf, fit to PR0 inverse)
     Tweeter L/R: CONF_0911 ch1 PEQ (7 bands incl. CS42L83 HW EQ compensation)
  -> Output 4ch surround-40
       FL = tweeter_L,  FR = tweeter_R,  RL = woofer_L,  RR = woofer_R

CONF_0911 from cs4208_38.inf, subsystem HDAUDIO VEN_1013&DEV_8409&SUBSYS_106B1000
(Cirrus CS8409+CS42L83, iMac A2115 2019).  AID20 = iMac A2115 in Apple's tuning DB.

Woofer PEQ (v1.3): biquad fit to inverse of AID20 PressureResponse (1024-tap FIR,
48 kHz). DTFT gives measured woofer response; inverse = Apple 'flow' correction.
Key corrections: +12 dB at 500 Hz, +5 dB at 720 Hz, -8 dB valley at 1 kHz,
+9 dB at 1900 Hz, -5 dB at 2800 Hz. Fit within ±2 dB at 200-800 Hz.
CONF_0911 ch0 removed (those resonance bands are inappropriate with flow EQ).

Dolby DAX3 EQ is intentionally omitted: it is one part of a multi-stage
perceptual pipeline (DRC, dynamics, virtualiser); applying the 20-band section
alone produces wrong tonal balance.
"""

# ---------------------------------------------------------------------------
# DSP parameters
# ---------------------------------------------------------------------------

XOVER_HZ = 800.0
XOVER_Q  = 0.70   # Butterworth 2nd-order (two cascaded = 4th-order Linkwitz-Riley)

TWEETER_HPF_HZ = None   # no software HPF; HW CS42L83 provides DC blocking

WOOFER_PEQ = [
    # AID20 'flow' correction: biquad fit to inverse of PressureResponse[ch0].
    # Target: DTFT of 1024-tap FIR, inverted, normalized to 0 dB at 1 kHz.
    # Fit within ±2 dB at 200-800 Hz (woofer operating range with LPF at 800 Hz).
    {"f0":  500.0, "Q": 1.50, "gain": +12.0},   # main peak (+14 dB target at 500 Hz)
    {"f0":  720.0, "Q": 2.50, "gain":  +5.0},   # 700-800 Hz shoulder
    {"f0": 1050.0, "Q": 2.50, "gain":  -8.0},   # valley at 1 kHz
    {"f0": 1900.0, "Q": 1.00, "gain":  +9.0},   # 2 kHz bump
    {"f0": 2800.0, "Q": 0.50, "gain":  -5.0},   # 2.5-3 kHz cut
    {"type": "lowshelf", "f0": 150.0, "Q": 0.70, "gain": +2.0},
]
TWEETER_PEQ = [
    {"f0": 1031.0, "Q": 0.36, "gain": -17.67},
    {"f0": 1890.0, "Q": 0.29, "gain":  11.48},
    {"f0": 3440.0, "Q": 0.54, "gain":  -7.81},
    {"f0": 1180.0, "Q": 0.14, "gain":  -6.62},
    {"f0": 1637.0, "Q": 0.27, "gain":   5.16},
    {"f0": 4883.0, "Q": 0.32, "gain":   3.41},
    # CS42L83 HW EQ (EQ1S1R7+EQ1S2R7) compensation: driver doesn't program these regs,
    # they would add ~+8dB shelf above ~9kHz. Approximate with high-shelf.
    {"type": "highshelf", "f0": 9000.0, "Q": 0.7, "gain": 4.0},
]

# Pre-gain: woofer flow path peaks at +11.4 dB at 501 Hz.
# -12 dB ensures 0-dBFS input cannot clip after maximum PEQ boost.
PRE_GAIN_DB = -12.0

# ---------------------------------------------------------------------------
# Build node / link lists
# ---------------------------------------------------------------------------

nodes = []
links = []


def node(name, label, **ctrl):
    ctrl_str = "  ".join(f'"{k}" = {v}' for k, v in ctrl.items())
    nodes.append(
        f'          {{ type = builtin  name = {name}  label = {label}'
        + (f'  control = {{ {ctrl_str} }}' if ctrl else "")
        + " }"
    )


def link(out_node, in_node):
    links.append(f'          {{ output = "{out_node}:Out"  input = "{in_node}:In" }}')


def chain(node_list):
    for a, b in zip(node_list[:-1], node_list[1:]):
        link(a, b)


# --- Pre-gain (high-shelf at 30 Hz covers all audible content) ---
# bq_highshelf at 30 Hz: gain applied to everything above 30 Hz
node("pgL", "bq_highshelf", Freq=30.0, Q=0.7, Gain=PRE_GAIN_DB)
node("pgR", "bq_highshelf", Freq=30.0, Q=0.7, Gain=PRE_GAIN_DB)

# --- Woofer Left: 2x LPF + flow PEQ ---
wL = ["pgL"]
for i in range(2):
    n = f"wL_lp{i+1}"
    node(n, "bq_lowpass", Freq=XOVER_HZ, Q=XOVER_Q)
    wL.append(n)
for i, p in enumerate(WOOFER_PEQ):
    n = f"wL_eq{i+1}"
    t = p.get("type", "peaking")
    label = "bq_lowshelf" if t == "lowshelf" else "bq_peaking"
    node(n, label, Freq=p["f0"], Q=p["Q"], Gain=p["gain"])
    wL.append(n)
chain(wL)

# --- Woofer Right: same ---
wR = ["pgR"]
for i in range(2):
    n = f"wR_lp{i+1}"
    node(n, "bq_lowpass", Freq=XOVER_HZ, Q=XOVER_Q)
    wR.append(n)
for i, p in enumerate(WOOFER_PEQ):
    n = f"wR_eq{i+1}"
    t = p.get("type", "peaking")
    label = "bq_lowshelf" if t == "lowshelf" else "bq_peaking"
    node(n, label, Freq=p["f0"], Q=p["Q"], Gain=p["gain"])
    wR.append(n)
chain(wR)

# --- Tweeter Left: +6 dB compensation + [optional HPF] + PEQ ---
# Pre-gain is -12 dB (needed for woofer's +11.4 dB flow boost).
# Tweeter path needs only -6 dB headroom, so compensate +6 dB here.
node("tgL", "bq_highshelf", Freq=30.0, Q=0.7, Gain=6.0)
link("pgL", "tgL")
tL = ["tgL"]
if TWEETER_HPF_HZ:
    for i in range(2):
        n = f"tL_hp{i+1}"
        node(n, "bq_highpass", Freq=float(TWEETER_HPF_HZ), Q=XOVER_Q)
        tL.append(n)
for i, p in enumerate(TWEETER_PEQ):
    n = f"tL_eq{i+1}"
    label = "bq_highshelf" if p.get("type") == "highshelf" else "bq_peaking"
    node(n, label, Freq=p["f0"], Q=p["Q"], Gain=p["gain"])
    tL.append(n)
chain(tL)

# --- Tweeter Right: same ---
node("tgR", "bq_highshelf", Freq=30.0, Q=0.7, Gain=6.0)
link("pgR", "tgR")
tR = ["tgR"]
if TWEETER_HPF_HZ:
    for i in range(2):
        n = f"tR_hp{i+1}"
        node(n, "bq_highpass", Freq=float(TWEETER_HPF_HZ), Q=XOVER_Q)
        tR.append(n)
for i, p in enumerate(TWEETER_PEQ):
    n = f"tR_eq{i+1}"
    label = "bq_highshelf" if p.get("type") == "highshelf" else "bq_peaking"
    node(n, label, Freq=p["f0"], Q=p["Q"], Gain=p["gain"])
    tR.append(n)
chain(tR)

# ---------------------------------------------------------------------------
# Assemble config
# ---------------------------------------------------------------------------

nodes_str = "\n".join(nodes)
links_str = "\n".join(links)

conf = f"""context.modules = [
  {{ name = libpipewire-module-filter-chain
    args = {{
      node.description = "iMac A2115 4-Speaker DSP"
      filter.graph = {{
        nodes = [
{nodes_str}
        ]
        links = [
{links_str}
        ]
        inputs  = [ "pgL:In"  "pgR:In" ]
        outputs = [ "{tL[-1]}:Out"  "{tR[-1]}:Out"  "{wL[-1]}:Out"  "{wR[-1]}:Out" ]
      }}
      capture.props = {{
        node.name        = "imac_dsp_in"
        node.description = "iMac Speakers"
        audio.channels   = 2
        audio.position   = [ FL FR ]
        media.class      = "Audio/Sink"
      }}
      playback.props = {{
        node.name        = "imac_dsp_out"
        node.description = "iMac DSP Output"
        node.target      = "alsa_output.pci-0000_00_1f.3.analog-surround-40"
        audio.channels   = 4
        audio.position   = [ FL FR RL RR ]
      }}
    }}
  }}
]
"""

out = "/home/mrhogun/.config/pipewire/pipewire.conf.d/99-imac-dsp.conf"
with open(out, "w") as f:
    f.write(conf)
print(f"Written {len(nodes)} nodes, {len(links)} links to {out}")
