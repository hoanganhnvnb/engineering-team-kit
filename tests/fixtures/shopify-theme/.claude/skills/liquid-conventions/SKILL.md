---
name: liquid-conventions
description: Acme theme rules for Liquid snippets and sections. Use when creating or editing .liquid files in this theme.
---

# Liquid conventions (Acme theme)

- Snippets are rendered with `{% render 'name', param: value %}` and never `include`.
- Every snippet starts with a `{% comment %}` doc block listing its parameters.
- Money is output with `| money`, never by dividing by 100.
- Badges use `snippets/badge.liquid` and the classes `badge badge--<variant>`.
- Allowed variants: `sale`, `sold-out`, `new`. New variants get a rule in `assets/base.css` using tokens.
