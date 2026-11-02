---
type: Decision
title: "Responsive (SPEC-095)"
description: "Style mobile-first on one tree with only `tablet:` (≥900) and `desktop:` (≥1300) compiled; `useBreakpoint`/`useIsMobile` gates mounting, never styling."
---

Mobile-first with **two custom breakpoints** in `index.css` `@theme` — Tailwind defaults (`sm`/`md`/`lg`/`xl`/`2xl`) reset to `initial`, only `tablet:` (≥900) / `desktop:` (≥1300) compile; unprefixed = mobile. Reflow via responsive utilities on **one** tree (a `*Mobile`/`*Desktop` twin is a smell); a separate markup branch is allowed only for genuine structural divergence (Files table vs card list) or mount-cost/mobile-chrome cases. One viewport hook `useBreakpoint`/`useIsMobile` (`src/lib/`) for **mount-gating only**, never styling. Mobile nav = Header hamburger → `AppNavDrawer`; shared `Menu` + `MobileActionBar` primitives; `Modal`/`Drawer` gain small-screen presentations. Detail: `apps/portal/info/best-practices/react/react.md` §20.

## History

### 2026-07-08

- **Settled:** SPEC-095.
