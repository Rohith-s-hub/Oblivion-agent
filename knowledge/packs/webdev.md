# WORLD-CLASS WEB DESIGN SYSTEM

## JUDGMENT PROCESS (Run Before Writing ANY Code)

1. **Read Intent:** What is this site's purpose? Convert, inform, showcase, sell? Who is the audience? What emotional register? (Fintech dashboard != kids toy store)
2. **Establish a Design Point of View:** Pick ONE strong direction and commit. Avoid "default-itis" (default fonts, default blue links, default shadows on everything).
3. **Hierarchy First:** Every screen needs ONE clear focal point. Establish hierarchy via scale, weight, color, whitespace — before reaching for borders/shadows.
4. **Constraint-Driven System:** Build a small design token system (spacing: 4/8/12/16/24/32/48/64, type scale, color palette, radius scale). Use ONLY those values. No magic numbers.
5. **Self-Critique Loop:** After first pass, ask: Does anything look like a browser default? Is there enough whitespace? Would this survive a 2-second screenshot judgment?

## TYPOGRAPHY (70% of Visual Design)
- Pairing: 1 distinctive heading font + 1 readable body font (or Inter/Geist across weights)
- Scale: Use a ratio (1.25 or 1.333). Ensure strong contrast between heading and body sizes.
- Line-height: 1.0-1.2 for large headings, 1.5-1.7 for body
- Line length: 45-75 characters (use max-width in ch units)
- Letter-spacing: slightly negative on bold headlines = premium feel

## COLOR
- Palette: 1 primary, 1-2 accent, 8-10 step neutral ramp, semantic colors
- Avoid pure black (#000) on pure white — use off-black (#0a0a0a-#111) and off-white
- Tint neutral grays toward brand hue for cohesion
- Use color with restraint — single accent used sparingly = more premium than many colors
- Dark mode needs its own palette (surfaces via lighter grays, reduced saturation accents)

## SPACING & LAYOUT
- Strict spacing scale: 4/8/12/16/24/32/48/64/96px — no random values
- Generous whitespace = confidence/premium; cramped = cheap/rushed
- Vary section padding for visual pacing (not identical everywhere)
- Asymmetric layouts read more crafted than centered-everything

## VISUAL POLISH
- Border-radius: consistent scale (4/8/16px), never mix arbitrary radii
- Shadows: soft, layered, low-opacity, tinted toward background hue — not harsh black
- Borders: hairline 1px low-opacity = refined
- Icons: one consistent set (stroke width, corner style) — never mix icon libraries
- Custom focus states, selection color, scrollbar styling, favicon, empty states designed

## MOTION
- Purpose: guide attention, communicate state change, provide feedback — not decoration
- Easing: custom cubic-bezier (ease-out for entrances, ease-in for exits)
- Duration: 100-200ms for micro-interactions, 200-400ms for transitions
- Respect prefers-reduced-motion
- Hover/focus/active states on EVERY interactive element

## COMPONENTS
- Forms: real labels (not placeholder-only), inline validation, loading state on submit
- Navigation: clear current-page indicator, sensible mobile pattern
- Buttons: primary/secondary/tertiary hierarchy, 44px+ tap targets, all states
- Empty/error/loading states DESIGNED for every async UI — never blank white flash

## RESPONSIVE
- Design mobile-first for content/conversion sites
- Breakpoints driven by content (where layout breaks), not arbitrary device widths
- Touch targets, thumb zones, 16px+ body text (avoids iOS auto-zoom)
- Test with real content lengths, not lorem ipsum

## ACCESSIBILITY (Non-negotiable)
- Semantic HTML first (button not div onclick, proper headings, landmarks)
- Full keyboard navigability, visible focus indicators
- Color contrast WCAG AA (4.5:1 body, 3:1 large text)
- Alt text for meaningful images, empty alt for decorative

## PERFORMANCE
- Skeleton loaders > spinners; optimistic UI > waiting
- Images: WebP/AVIF, responsive srcset, lazy-load, explicit dimensions
- Font: font-display swap, preload critical, subset unused glyphs
- Code-split, lazy-load non-critical routes

## SELF-CHECK (Run Before Saying Done)

| Amateur Tell | World-Class Fix |
|---|---|
| Default system font, default blue links | Deliberate type system with real hierarchy |
| Equal padding everywhere | Varied, intentional section pacing |
| Pure black on pure white, harsh shadows | Off-black/off-white, soft tinted shadows |
| Every element same visual weight | Clear single focal point per screen |
| Mixed icon styles, mixed border-radius | One icon set, one radius scale |
| No hover/focus states | Custom interactive states everywhere |
| Spinner-only loading, blank errors | Designed skeleton/empty/error states |
| Lorem ipsum | Real, specific, benefit-driven copy |
| Desktop-only layout | True mobile-first responsive |
| Hardcoded magic numbers in CSS | Token-based design system |

## EXECUTION PROTOCOL
1. Use `batch_edit` for multi-file websites (all files in ONE atomic call, or 2-3 batches for large projects)
2. CSS file MUST be minimum 1,500+ characters with full design token system
3. Never generate placeholder content — every page production-ready
4. After first batch: self-critique against the Tells table above, then fix issues in a second pass
