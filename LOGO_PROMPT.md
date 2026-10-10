# Logo prompt for Lumen Atlas

Paste into an image model (ChatGPT/DALL·E, Midjourney, Ideogram, Firefly). Ideogram or ChatGPT handle the wordmark
text best; with Midjourney generate the symbol only and add the text yourself.

---
**Prompt**

Design a clean, modern logo for "Lumen Atlas", an academic research platform that maps the global collaboration
network of neurointerventional physicians (endovascular neurosurgery, interventional neurology and interventional
neuroradiology). It is the companion to a neurosurgery atlas called "Cortex Atlas", so it should feel like a sibling
brand: same seriousness, different motif.

Symbol: the cross-section of a blood vessel seen end-on — a circular arterial wall forming a ring — whose open
lumen glows softly from within. Inside or around the ring, a minimal network of small nodes connected by fine lines
suggests a co-authorship graph, and three subtly different node tones hint at three specialties converging. Optional
subtle cue of a catheter or guidewire entering the lumen as a single smooth curve. No brain illustration, no blood
drops, no red gore, no medical cross, no caduceus.

Style: flat vector, geometric, minimal, high contrast, works at 32 px as a favicon and at 1200 px in a header. Palette:
deep teal-blue (#0B6E8E) and navy (#1B2A33) with one warm accent of soft amber light (#E69F00) for the glowing
lumen; white or transparent background. Wordmark "LUMEN ATLAS" in a modern geometric sans-serif (similar to Inter,
Montserrat or Avenir), medium weight, generous letter spacing, to the right of the symbol; optional small tagline
"Neurointerventional Co-Authorship Network" beneath in lighter weight.

Deliver: horizontal lockup (symbol + wordmark), a square symbol-only version, transparent background, no mockups,
no 3D, no gradients beyond the soft inner glow, no extra text.
---

**Variations to ask for if the first round misses**
- "Make the vessel ring thinner and the glowing lumen more prominent; reduce the network to 6–8 nodes."
- "Show the vessel as a gentle bifurcation (Y-shape) in negative space instead of a ring."
- "Match the visual weight of the Cortex Atlas logo" (attach that logo as a reference image).

**Hand-off**: save as `webapp\assets\lumen_atlas_logo.png` (transparent, ~1200 px wide; the square version can be the
favicon), then run `.\BUILD_AND_DEPLOY.ps1 -AppOnly`.
