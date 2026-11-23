import { test } from "node:test";
import assert from "node:assert/strict";
import { formatCents } from "../src/format.js";

test("formats positive cents", () => {
  assert.equal(formatCents(1999), "$19.99");
});

test("formats refunds (negative cents)", () => {
  // Pre-existing failure: tracked separately, not part of most tasks.
  assert.equal(formatCents(-250), "-$2.50");
});
