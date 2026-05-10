# Design

## Theme

Primary scene: a Discord regular or moderator has the soundboard open next to Discord during an active voice session, sometimes in a dim room, sometimes on a bright desktop. Default light mode should feel like a tactile control desk; dark mode should reduce glare without becoming a generic terminal.

## Color

Use OKLCH tokens. The strategy is restrained product color with a committed ember accent for active controls, plus moss and amber as secondary state roles. Never use pure black or pure white; neutrals are warm and slightly tinted.

## Typography

Use Space Grotesk for UI and data, with Instrument Serif only for large display moments. Product labels, buttons, tables, forms, and charts stay in the sans stack for trust and density.

## Components

Controls use rounded-but-solid shapes, visible borders, tactile offset shadows, and clear states for hover, focus, disabled, login-required, sent, warning, and error. Tables remain compact and stable, with sticky headers and natural row heights.

## Layout

Desktop soundboard is a control-room strip over three dense table panels. Mobile keeps the nav non-sticky and makes the control room the sticky operating surface. Analytics uses a two-column dashboard with compact stat tiles and chart panels.

## Motion

Motion is functional only: short state transitions, loading sweep, chart/list reveal, and reduced-motion overrides. Avoid decorative choreography.
