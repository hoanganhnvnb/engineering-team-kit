import { test } from "node:test";
import assert from "node:assert/strict";
import { createCart, addItem, subtotalCents } from "../src/cart.js";

test("adds a new item", () => {
  const cart = addItem(createCart(), { sku: "A", priceCents: 500, qty: 2 });
  assert.equal(cart.items.length, 1);
  assert.equal(subtotalCents(cart), 1000);
});

test("rejects float prices", () => {
  assert.throws(() => addItem(createCart(), { sku: "A", priceCents: 4.99 }));
});

test("empty cart subtotal is zero", () => {
  assert.equal(subtotalCents(createCart()), 0);
});
