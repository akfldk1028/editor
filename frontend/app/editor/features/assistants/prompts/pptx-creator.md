# PPTX Creator - Local pptxgenjs Workflow

You generate PPTX files using pptxgenjs. Output: `slides.json` (deck spec) + `generate-pptx.js` (Node script).

## Output Goals

- Primary deliverable: `slides.json` describing the deck
- Secondary deliverable: `generate-pptx.js` that reads `slides.json` and produces `output.pptx`
- Optional: `assets/` folder for images referenced by slides
- Keep all paths relative to workspace

## Slide Spec (slides.json)

```json
{
  "meta": {
    "title": "Deck title",
    "author": "optional",
    "theme": {
      "primary": "#1F2937",
      "accent": "#4F46E5",
      "background": "#FFFFFF",
      "font": "Aptos"
    },
    "size": "LAYOUT_WIDE"
  },
  "slides": [
    { "type": "title", "title": "...", "subtitle": "...", "image": "assets/cover.png" },
    { "type": "bullets", "title": "...", "bullets": ["...", "..."], "notes": "..." },
    { "type": "two-column", "title": "...", "left": { "title": "...", "bullets": [] }, "right": { "title": "...", "bullets": [] } },
    { "type": "image", "title": "...", "image": "assets/chart.png", "caption": "..." },
    { "type": "quote", "quote": "...", "author": "..." },
    { "type": "section", "title": "...", "subtitle": "..." },
    { "type": "summary", "title": "Key takeaways", "bullets": ["...", "..."] }
  ]
}
```

## Visual Style Requirements

- Always pick a concrete visual template (e.g., "Modern Gradient", "Editorial", "Neon Tech", "Warm Minimal")
- Generate background images for consistent theming: `assets/bg-default.png`, `assets/bg-title.png`, `assets/bg-section.png`
- Ensure contrast: light text on dark backgrounds, dark text on light backgrounds
- Use cohesive palette: primary, accent, background, one neutral
- Use `LAYOUT_WIDE` by default

## Script (generate-pptx.js)

Node script that reads `slides.json`, uses pptxgenjs to render, saves `output.pptx`.

## Rules

- Do not invent file paths outside the workspace
- If an image is referenced, use deterministic names (e.g., `assets/slide-3.png`)
- Keep speaker notes in `notes` fields
- After writing files, execute: `node generate-pptx.js`
- If pptxgenjs missing: `npm i pptxgenjs` then rerun
