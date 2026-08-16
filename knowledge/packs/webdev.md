# WEBDEV (elite, lean)

## COLOR PALETTES (pick ONE)
- Violet:  --primary:#8b5cf6 --dark:#7c3aed --accent:#ec4899
- Ocean:   --primary:#3b82f6 --dark:#2563eb --accent:#06b6d4
- Sunset:  --primary:#f97316 --dark:#ea580c --accent:#ec4899

FORBIDDEN: SlateBlue, Gold, plain "red"/"blue" keywords.

## REQUIRED SECTIONS (landing page)
1. Sticky nav (backdrop-filter blur)
2. Hero (gradient mesh bg + gradient text + 2 CTAs)
3. Trust bar (5 brand logos, grayscale)
4. Features grid (6 cards WITH SVG icons via lucide CDN)
5. Testimonials (4-6 with avatar circles)
6. Pricing (3 tiers, middle = highlighted)
7. FAQ (5-8 collapsible)
8. CTA section (gradient bg)
9. Footer (4 columns + copyright 2025)

## VISUAL EFFECTS (mandatory)
- Hero bg: radial gradient mesh OR animated grid pattern
- Cards: border-radius 16px, colored shadow rgba(139,92,246,0.15)
- Buttons: gradient bg + colored shadow + hover translateY(-2px)
- Scroll animations via Intersection Observer

## SVG ICONS (use lucide CDN)
<script src="https://unpkg.com/lucide@latest"></script>
<i data-lucide="rocket"></i>
<script>lucide.createIcons();</script>

## FORBIDDEN
- via.placeholder.com images
- "Click Here" copy
- Lorem ipsum
- Broken nav links (link to sections that dont exist)
- Copyright year != 2025
- Only 2 testimonials (need 4+)
- Missing pricing section

## COPY RULES
Wrong: "Boost productivity"  
Right: "Ship 3x faster with AI-powered automation"
Numbers > adjectives.

## STRUCTURE
- index.html
- styles/main.css      (tokens + hero)
- styles/components.css  (buttons, cards)
- styles/responsive.css  (mobile-first)
- scripts/main.js      (nav, scroll, animations)
- README.md

Use batch_edit with ALL files at once. Never partial.
