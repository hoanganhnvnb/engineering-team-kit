# Online Store 2.0 theme for Acme Outdoor

Liquid + vanilla JS + CSS, no build step.

- Use the `liquid-conventions` skill for any Liquid change.
- All customer-facing text goes through locale keys in `locales/en.default.json` (`{{ 'key' | t }}`). No hard-coded strings.
- CSS uses the custom properties in `assets/base.css`. No inline styles.
- Never edit `config/settings_data.json` by hand (merchant data).
- Validate with `shopify theme check` when the CLI is available.
