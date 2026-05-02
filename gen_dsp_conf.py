#!/usr/bin/env python3
"""Generate PipeWire filter-chain config for iMac A2115 2019 4-speaker DSP.

Signal chain:
  Input stereo (L, R)
  -> Pre-gain -6 dB (headroom for PEQ boosts)
  -> Fan-out: woofer path + tweeter path (PipeWire handles fan-out natively)
     Woofer  L/R: 2x LPF @800 Hz (4th-order) -> CONF_0911 ch0 PEQ (6 bands)
     Tweeter L/R: 2x HPF @800 Hz (4th-order) -> CONF_0911 ch1 PEQ (6 bands)
  -> Output 4ch surround-40
       FL = tweeter_L,  FR = tweeter_R,  RL = woofer_L,  RR = woofer_R

CONF_0911 from cs4208_38.inf, subsystem HDAUDIO VEN_1013&DEV_8409&SUBSYS_106B1000
(Cirrus CS8409+CS42L83, iMac A2115 2019).

Dolby DAX3 EQ is intentionally omitted: it is one part of a multi-stage
perceptual pipeline (DRC, dynamics, virtualiser); applying the 20-band section
alone produces wrong tonal balance. Basic CONF_0911 hardware correction is
sufficient for accurate reproduction matching the speaker design intent.
"""

# ---------------------------------------------------------------------------
# CONF_0911 parameters
# ---------------------------------------------------------------------------

# ch0 = woofer, ch1 = tweeter
XOVER_HZ = 800.0
XOVER_Q  = 0.70   # Butterworth 2nd-order (two cascaded = 4th-order Linkwitz-Riley)

# Tweeter software HPF:
#   800  = same as woofer LPF (crossover pair) — use if driver does NOT init HW EQ
#   None = no software HPF (use if HW EQ1S1R7/EQ1S2R7 are programmed, or for testing)
#   200  = subsonic-only protection (compromise test)
# No software HPF on tweeter — matches Windows APO (HW CS42L83 does DC blocking only)
TWEETER_HPF_HZ = None

WOOFER_PEQ = [
    {"f0": 1320.0, "Q": 0.62, "gain": 17.22},
    {"f0":  210.0, "Q": 0.84, "gain": -14.42},
    {"f0": 1663.0, "Q": 0.23, "gain": 10.52},
    {"f0": 2500.0, "Q": 0.29, "gain": -19.71},
    {"f0":  604.0, "Q": 0.33, "gain": -7.63},
    {"f0":  345.0, "Q": 0.46, "gain": -9.00},
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
    {"type": "highshelf", "f0": 9000.0, "Q": 0.7, "gain": 7.9},
]

# Pre-gain: largest single PEQ boost in tweeter path is +11.48 dB.
# Apply -6 dB headroom so a 0-dBFS signal stays below clipping after boost.
PRE_GAIN_DB = -6.0

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

# --- Woofer Left: 2x LPF + 6 PEQ ---
wL = ["pgL"]
for i in range(2):
    n = f"wL_lp{i+1}"
    node(n, "bq_lowpass", Freq=XOVER_HZ, Q=XOVER_Q)
    wL.append(n)
for i, p in enumerate(WOOFER_PEQ):
    n = f"wL_eq{i+1}"
    node(n, "bq_peaking", Freq=p["f0"], Q=p["Q"], Gain=p["gain"])
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
    node(n, "bq_peaking", Freq=p["f0"], Q=p["Q"], Gain=p["gain"])
    wR.append(n)
chain(wR)

# --- Tweeter Left: [optional HPF] + 6 PEQ ---
# Windows APO has NO software HPF for tweeter (hardware CS42L83 EQ1S1R7/EQ1S2R7 does it).
# Linux driver does NOT program those hardware regs, so we add software HPF.
# Set TWEETER_HPF_HZ = None to test without HPF (matches Windows APO exactly).
tL = []
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
link("pgL", tL[0])
chain(tL)

# --- Tweeter Right: same ---
tR = []
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
link("pgR", tR[0])
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
