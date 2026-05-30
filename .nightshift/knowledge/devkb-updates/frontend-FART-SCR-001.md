# DevKB Update — FART-SCR-001
**Target file:** frontend.md
**Section:** Vanilla dashboard JSON viewers / data attributes
**Date:** 2026-05-30

## Entry

### JSON stored in HTML attributes needs attribute escaping, not only HTML escaping
**Problem:** A vanilla dashboard rendered pretty JSON correctly, but JQ-mode filtering read truncated raw JSON from `data-raw-json` because quoted JSON had been inserted into a double-quoted attribute.

**Root Cause:** The generic `escapeHtml()` helper escaped markup through `textContent`/`innerHTML`, which handles `<`, `>`, and `&`, but does not necessarily encode double quotes. That is safe for text nodes and unsafe for double-quoted attribute values containing JSON.

**Fix:** Use a dedicated attribute-escaping helper for dynamic attribute values and encode double quotes as `&quot;`. Keep `setAttribute()` for runtime DOM updates where possible.

**Prevention:** When embedding JSON in static HTML strings, use an attribute-specific escape helper or build the element and call `setAttribute()`. Add regression coverage for JQ/filter paths that read the raw attribute, not just for the initially rendered highlighted JSON.
