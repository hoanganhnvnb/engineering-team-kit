#!/usr/bin/env bash
# Tiny node project with one obvious bug. Runs in the empty eval workspace.
set -euo pipefail
mkdir -p src test
cat > package.json <<'EOF'
{ "name": "tiny-shop", "private": true, "type": "module", "scripts": { "test": "node --test test/" } }
EOF
cat > CLAUDE.md <<'EOF'
Money is integer cents. Every exported function has a test in test/. Run tests with `npm test`.
EOF
cat > src/cart.js <<'EOF'
export function createCart() { return { items: [] }; }
export function addItem(cart, { sku, priceCents, qty = 1 }) {
  const existing = cart.items.find((i) => i.sku === sku);
  if (existing) existing.qty = qty;
  else cart.items.push({ sku, priceCents, qty });
  return cart;
}
export const subtotalCents = (cart) => cart.items.reduce((s, i) => s + i.priceCents * i.qty, 0);
EOF
cat > test/cart.test.js <<'EOF'
import { test } from "node:test";
import assert from "node:assert/strict";
import { createCart, addItem, subtotalCents } from "../src/cart.js";
test("adds a new item", () => {
  assert.equal(subtotalCents(addItem(createCart(), { sku: "A", priceCents: 500, qty: 2 })), 1000);
});
EOF
git init -q -b main && git add -A && git -c user.email=e@x -c user.name=e commit -qm baseline
