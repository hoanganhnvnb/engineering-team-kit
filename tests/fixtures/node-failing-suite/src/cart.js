// Cart helpers. Money is always integer cents.

export function createCart() {
  return { items: [] };
}

export function addItem(cart, { sku, priceCents, qty = 1 }) {
  if (!sku) throw new Error("sku is required");
  if (!Number.isInteger(priceCents) || priceCents < 0) throw new Error("priceCents must be a non-negative integer");
  const existing = cart.items.find((i) => i.sku === sku);
  if (existing) {
    existing.qty += qty;
  } else {
    cart.items.push({ sku, priceCents, qty });
  }
  return cart;
}

export function subtotalCents(cart) {
  return cart.items.reduce((sum, i) => sum + i.priceCents * i.qty, 0);
}
