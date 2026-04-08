Original prompt: now there is no buttons to play etc

- Investigated `templates/index.html` layout regression after dynamic row-height work.
- Found brittle fake-table CSS (`tbody { display:block }`, `tbody tr { display:table }`) likely causing missing play columns/buttons.
- Simplified table rendering back toward native layout and kept explicit widths for play columns.
- Added explicit widths for the Recent Actions columns so the `Time` column cannot collapse out of view.
- Confirmed host timezone is `Atlantic/Madeira` but `web` and `bot` containers run in `UTC`.
- Fixed web timestamp parsing so naive DB timestamps are interpreted as UTC before formatting in the browser (`index.html` and `analytics.html`).
- Need browser verify for button visibility and row/card fit after the CSS change.
