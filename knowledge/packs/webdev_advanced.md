# WORLD-CLASS WEB DESIGN — ADVANCED DEEP DIVE

## EXTENDED TYPOGRAPHY
- Font-weight contrast: heavy (700-900) headlines against regular (400) body = strong hierarchy
- Fluid type via clamp(): clamp(1rem, 2.5vw, 1.5rem) for body, clamp(2rem, 5vw, 4rem) for H1
- Avoid extra letter-spacing on body text (hurts readability)
- System fonts are correct for utility-heavy UI (dashboards, admin) where density matters

## EXTENDED COLOR
- Neutral ramps should not be pure gray — tint slightly toward brand hue
- Dark mode: reduced-saturation accents to avoid vibration/glow artifacts
- Single accent color used sparingly = more premium than competing colors
- Test with color-blind simulation tools

## EXTENDED LAYOUT
- 12-column grid for flexibility; break grid occasionally for visual interest
- Asymmetric layouts (offset content, unequal columns) = more crafted
- Alignment discipline: misalignment is fastest tell of amateur work
- Section rhythm: vary padding intentionally for visual pacing

## EXTENDED VISUAL POLISH
- Micro-details that signal craft: custom selection color, custom scrollbar, designed empty states
- Image treatment (crop, overlay, duotone) as part of the system
- Real high-quality imagery beats generic stock every time
- Consider using search_stock_images tool to fetch real Unsplash photos

## CATEGORY-SPECIFIC GUIDANCE

### E-commerce
- Product cards: image dominates, price prominent, quick-add CTA
- Cart: clear subtotal, quantity controls, remove button
- Checkout: minimal distraction, progress indicator, trust signals
- Product detail: image gallery, specs, reviews, related products

### Portfolio
- Work should dominate, not template chrome
- Case studies: context, problem, process, solution, results
- Minimal nav, let the work breathe

### SaaS/Marketing
- Hero: specific headline, real product screenshot, 2 CTAs (primary + ghost)
- Social proof: real logos, real quotes (never invent)
- Pricing: clear tiers, feature comparison, highlighted recommended plan

### Dashboard
- Density over decoration
- Status indicators, sortable tables, keyboard efficiency
- Sidebar nav with clear hierarchy
- Data visualization: purposeful, not decorative

### Blog/Editorial
- Typography IS the product
- Clear article hierarchy, metadata, reading time
- Related content, newsletter signup
- Code blocks styled for readability if technical

## ENGINEERING QUALITY
- Design tokens as CSS custom properties (not hardcoded values)
- Consistent component structure: small, composable, single-responsibility
- Reusable UI primitives (buttons, inputs, cards) built once, composed everywhere
- Clean semantic naming that mirrors UI structure
- State management proportional to actual complexity

## SEO & METADATA
- Proper title, meta description, canonical tags
- Open Graph / Twitter card tags for social sharing
- Semantic heading structure
- JSON-LD structured data where relevant

## CONTENT CRAFT
- Headlines: specific, benefit-driven ("Ship 3x faster" beats "Welcome to our platform")
- Microcopy matters: button labels, empty states, error messages = product feel
- Consistent voice matching brand emotional register
- NEVER use lorem ipsum in final output
