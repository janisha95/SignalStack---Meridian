# Design System Document: Quantitative Precision

## 1. Overview & Creative North Star
**Creative North Star: The Sovereign Console**

This design system is engineered for the high-frequency environment of quantitative trading, where cognitive load is managed through mathematical rigor rather than decorative flourishes. The aesthetic is "Sovereign Console"—a digital environment that feels like a physical piece of high-end aerospace equipment: cold, precise, and authoritative.

To move beyond a "standard dashboard" look, we employ **Intentional Asymmetry**. While the grid is dense, we avoid a perfectly centered "template" feel. We use the contrast between the human-readable **Inter** and the machine-readable **JetBrains Mono** to create an editorial tension. Layouts should prioritize data-primary positioning, where the most volatile metrics are given "breathing room" through negative space, even within a high-density environment.

---

## 2. Colors & Surface Logic

### The Palette
The core of the system is a deep, monolithic charcoal-navy that provides the ultimate stage for high-contrast data visualization.

- **Background (Base):** `#0b1326` (Surface)
- **Primary (Action):** `#adc6ff` (Primary) / `#4d8eff` (Container)
- **Long/Profit:** `#4edea3` (Secondary)
- **Short/Loss:** `#ffb2b7` (Tertiary)
- **Warning:** `#f59e0b` (Custom Amber)

### The "No-Line" Rule
**Explicit Instruction:** Designers are prohibited from using 1px solid borders to section off UI components. Structural definition is achieved exclusively through **Surface Tiering**. If you feel the need to draw a line, instead shift the background color of the nested element.

### Surface Hierarchy & Nesting
We create depth by "stacking" tonal shifts. This mimics the appearance of milled metal or precision-cut glass without using shadows.
- **Level 0 (App Base):** `surface` (#0b1326)
- **Level 1 (Module/Panel):** `surface_container_low` (#131b2e)
- **Level 2 (Active Widget):** `surface_container` (#171f33)
- **Level 3 (Popovers/Overlays):** `surface_container_high` (#222a3d)

### Signature Tonal Shifts
To ensure the "No-Line" rule works, utilize the `outline_variant` (#424754) only as a "Ghost Border" at 10-15% opacity when two identical surface colors must touch.

---

## 3. Typography
The typographic system is a dialogue between human strategy and machine execution.

- **Labels & Headers (Inter):** Used for navigation, field labels, and instructional text. It is clean, approachable, and stays in the background.
- **The Numeric Engine (JetBrains Mono):** Every price, quantity, percentage, and timestamp must be set in JetBrains Mono. This provides tabular alignment (monospacing) which is critical for scanning vertical columns of numbers.

**Scale Highlights:**
- **Display-LG:** 3.5rem (Inter). Used for high-level portfolio totals.
- **Label-SM:** 0.6875rem (Inter). Used for secondary metadata.
- **Numeric-MD:** (Custom implementation of JetBrains Mono at 0.875rem). The workhorse for order books and execution logs.

---

## 4. Elevation & Depth: Tonal Layering
In this system, elevation is a function of light, not shadow. 

1.  **The Layering Principle:** To "lift" a component (like a trade entry module), place a `surface_container_high` block inside a `surface_container_low` wrapper. The delta in lightness creates a tactile "recessed" or "raised" effect.
2.  **No Drop Shadows:** Traditional shadows are banned to maintain the precision of the terminal. If an element is "floating" (e.g., a context menu), use a `surface_bright` (#31394d) background with a 1px `outline` (#8c909f) at 20% opacity.
3.  **Backdrop Blurs:** For overlays, use a `surface_container_highest` color at 80% opacity with a `20px` backdrop blur. This allows the movement of the ticker data behind the overlay to remain visible, maintaining the "always-on" nature of trading.

---

## 5. Components

### Buttons
- **Primary:** `primary_container` background with `on_primary_container` text. Square corners (`0px`).
- **Ghost (Secondary):** No background. `primary` text. Border: 1px `outline_variant` at 30% opacity.
- **States:** Hover states should simply brighten the background by 5%. No scale transforms.

### Data Inputs
- **Numeric Fields:** Must use JetBrains Mono. 
- **Structure:** `surface_container_lowest` background. No border. Active state is indicated by a 1px `primary` bottom-border only.

### High-Density Lists (Order Books)
- **Divider Forfeiture:** Forbid the use of horizontal lines. 
- **Separation:** Use `0.15rem` (Spacing 1) of vertical padding and alternating `surface_container` / `surface_container_low` backgrounds for row "zebra-striping" if density exceeds 20 rows per viewport.

### Chips (Position Tags)
- **Status:** Rectangle-only (no border-radius). 
- **Long:** `secondary_container` background with `on_secondary_container` text.
- **Short:** `tertiary_container` background with `on_tertiary_container` text.

### Execution Toasts
- **Positioning:** Top-right. Use `surface_bright` background. No shadows. Use a high-contrast `primary` vertical accent bar (3px) on the left edge to denote "Active" status.

---

## 6. Do’s and Don’ts

### Do
- **Do** lean into extreme density. Use the `0.15rem` and `0.3rem` spacing tokens to pack information.
- **Do** align all decimals in tables. This is why we use JetBrains Mono.
- **Do** use `primary_fixed_dim` for inactive but important navigational elements.
- **Do** treat "Negative Space" as a luxury. Use it only to highlight the most critical "Panic" or "Profit" metrics.

### Don't
- **Don't** use border-radius. Every corner in this system is `0px`. Roundness suggests softness; this system is hard-edged.
- **Don't** use standard "Grey" for text. Use `on_surface_variant` (#c2c6d6) to maintain the navy-tinted chromatic harmony.
- **Don't** use gradients for "vibe." Gradients are only permitted if they represent a data trend (e.g., a heat-map in a volume profile).
- **Don't** use icons where a text label in `label-sm` would be more precise.