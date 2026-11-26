#!/usr/bin/env bash
# Tiny node project: git, a GitHub origin and Conventional Commits history, so detect finds
# the VCS, host and commit style. Release and deploy answers are not detectable. Runs in the empty eval workspace.
set -euo pipefail
mkdir -p src test
cat > package.json <<'EOP'
{ "name": "tiny-shop", "private": true, "type": "module", "scripts": { "test": "node --test test/" } }
EOP
cat > CLAUDE.md <<'EOP'
Money is integer cents. Every exported function has a test in test/. Run tests with `npm test`.
EOP
cat > src/cart.js <<'EOP'
export function createCart() { return { items: [] }; }
EOP
cat > test/cart.test.js <<'EOP'
import { test } from "node:test";
import assert from "node:assert/strict";
import { createCart } from "../src/cart.js";
test("a new cart is empty", () => { assert.equal(createCart().items.length, 0); });
EOP
git init -q -b main
git remote add origin https://github.com/example/tiny-shop.git
git add -A
c() { git -c user.email=e@x -c user.name=e commit -q --allow-empty -m "$1"; }
c "feat: add the cart module"
echo "// totals" >> src/cart.js && git add -A && c "feat(cart): add a subtotal helper"
echo "// fix" >> src/cart.js && git add -A && c "fix: handle an empty cart"
echo "// docs" >> src/cart.js && git add -A && c "docs: describe the cart"
echo "// test" >> src/cart.js && git add -A && c "test(cart): cover the empty cart"
