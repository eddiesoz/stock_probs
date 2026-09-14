---
name: visual-standards-conventions
description: "Visual design and UI standardization rules for overlays, cards, and page layouts"
---

# Visual Standards Conventions

## 🔴 HARD RULEs
- All new overlays must use constrained default sizing: w-11/12 max-w-7xl max-h-[90vh]
- No new overlays should use fullScreen mode
- Status page cards must distinguish between supervisord services (/services/:name) and in-process applications (/services/applications/:name)
- INFO-badge CSS variable must be used for overlay styling

## 🔴 Orchestration Visual Validation
- Follow the assigned visual gate in the orchestrator and `@ingenium-qa` profile; `@ingenium-qa` owns changed-route and batch desktop/mobile validation.
