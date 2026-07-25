"""Presentation-only styling for the GreenMachine landing hub.

Original GreenMachine artwork and styling, *inspired by* the classic console
dashboard aesthetic without copying any Xbox logo, icon, asset, or menu
graphic. Everything is generated CSS: dark emerald/black geometric grid,
an original glowing energy-sphere orb (pure radial gradients with baseball
seam arcs), neon-green horizontal menu bars, circular accents, and a subtle
pulse animation confined to the landing hub.

Constraints honored here:

* **no remote request of any kind** — no CSS resource references or style
  imports, no external font, image, stylesheet, or script; typography uses
  local/system font stacks only;
* accessible contrast (bright green on near-black exceeds WCAG AA for the
  sizes used) and meaning never carried by color alone (labels and icons
  accompany every state);
* keyboard access is preserved by styling real Streamlit buttons rather than
  replacing them, with a visible ``:focus`` state;
* the stylized console look lives on the hub — content screens reuse only the
  calmer base theme for readability.

This module is deliberately free of imports: it is a static asset for the
``streamlit_app.py`` composition root.
"""

from __future__ import annotations

# Applied on every screen: the dark-green identity, calm enough for metrics.
BASE_THEME_CSS = """
<style>
:root {
    --gm-black: #050a07;
    --gm-deep: #0a1710;
    --gm-emerald: #10331f;
    --gm-neon: #52e07c;
    --gm-neon-bright: #7dffa8;
    --gm-text: #d9ffe6;
}
.stApp {
    background:
        linear-gradient(rgba(82, 224, 124, 0.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(82, 224, 124, 0.045) 1px, transparent 1px),
        radial-gradient(ellipse at 20% -10%, #123a22 0%, transparent 55%),
        linear-gradient(160deg, var(--gm-deep) 0%, var(--gm-black) 70%);
    background-size: 44px 44px, 44px 44px, auto, auto;
    color: var(--gm-text);
}
h1, h2, h3, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
    font-family: Consolas, "Cascadia Mono", "Segoe UI", "Lucida Console", monospace;
    letter-spacing: 0.06em;
    color: var(--gm-neon-bright);
}
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #071209 0%, #04080a 100%);
    border-right: 1px solid rgba(82, 224, 124, 0.25);
}
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: rgba(82, 224, 124, 0.28) !important;
    border-radius: 10px;
    background: rgba(6, 18, 11, 0.55);
}
.stButton > button {
    font-family: Consolas, "Cascadia Mono", "Segoe UI", monospace;
    letter-spacing: 0.08em;
    border: 1px solid rgba(82, 224, 124, 0.55);
    background: linear-gradient(90deg, rgba(16, 51, 31, 0.9), rgba(8, 22, 14, 0.9));
    color: var(--gm-text);
    border-radius: 999px;
}
.stButton > button:hover, .stButton > button:focus {
    border-color: var(--gm-neon-bright);
    color: #06130b;
    background: linear-gradient(90deg, var(--gm-neon), var(--gm-neon-bright));
    box-shadow: 0 0 14px rgba(82, 224, 124, 0.65);
    outline: 2px solid var(--gm-neon-bright);
    outline-offset: 1px;
}
</style>
"""

# Hub-only decoration: the orb and blade styling plus the pulse animation.
HUB_CSS = """
<style>
.gm-hub-wrap { text-align: center; padding-top: 0.5rem; }
.gm-orb {
    width: 168px; height: 168px; margin: 0 auto 0.6rem auto;
    border-radius: 50%;
    background:
        radial-gradient(circle at 34% 30%, rgba(255, 255, 255, 0.75) 0%, transparent 18%),
        radial-gradient(circle at 50% 50%, #b8ffce 0%, #52e07c 34%, #14824a 62%, #06301b 88%);
    box-shadow:
        0 0 34px rgba(82, 224, 124, 0.8),
        0 0 90px rgba(82, 224, 124, 0.35),
        inset 0 0 26px rgba(4, 16, 9, 0.6);
    position: relative;
    animation: gm-pulse 3.2s ease-in-out infinite;
}
.gm-orb::before, .gm-orb::after {
    content: "";
    position: absolute; top: 8px; bottom: 8px;
    width: 58%;
    border: 3px solid rgba(6, 26, 14, 0.55);
    border-top-color: transparent; border-bottom-color: transparent;
    border-radius: 50%;
}
.gm-orb::before { left: -6px; transform: rotate(14deg); }
.gm-orb::after { right: -6px; transform: rotate(-14deg); }
.gm-ring {
    width: 216px; height: 216px; margin: -196px auto 24px auto;
    border-radius: 50%;
    border: 1px solid rgba(82, 224, 124, 0.35);
    box-shadow: 0 0 18px rgba(82, 224, 124, 0.18) inset;
}
.gm-title {
    font-family: Consolas, "Cascadia Mono", "Segoe UI", monospace;
    font-size: 2.6rem; font-weight: 700; letter-spacing: 0.34em;
    color: #7dffa8;
    text-shadow: 0 0 18px rgba(82, 224, 124, 0.75);
    margin: 0.2rem 0 0 0;
}
.gm-subtitle {
    color: #9adfb4; letter-spacing: 0.18em; font-size: 0.85rem;
    margin-bottom: 1.4rem;
}
@keyframes gm-pulse {
    0%, 100% { box-shadow: 0 0 30px rgba(82, 224, 124, 0.7), 0 0 80px rgba(82, 224, 124, 0.3); }
    50% { box-shadow: 0 0 46px rgba(125, 255, 168, 0.95), 0 0 120px rgba(82, 224, 124, 0.5); }
}
@media (prefers-reduced-motion: reduce) {
    .gm-orb { animation: none; }
}
.gm-hub-menu .stButton > button {
    width: 100%;
    max-width: 560px;
    padding: 0.65rem 1rem;
    margin: 0.22rem auto;
    font-size: 1.02rem;
    text-align: left;
    border-radius: 999px;
}
</style>
"""

# The orb + wordmark, as one HTML block (original artwork; generated CSS only).
HUB_HEADER_HTML = """
<div class="gm-hub-wrap">
  <div class="gm-orb" role="img" aria-label="GreenMachine energy sphere"></div>
  <div class="gm-ring"></div>
  <p class="gm-title">GREENMACHINE</p>
  <p class="gm-subtitle">MANUAL REVIEW CONSOLE &middot; PROTOTYPE &middot; v0.2.0</p>
</div>
"""
