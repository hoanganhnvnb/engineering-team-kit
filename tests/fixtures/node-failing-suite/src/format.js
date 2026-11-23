// Formats integer cents for display.
export function formatCents(cents) {
  const dollars = Math.floor(cents / 100); // wrong for negatives, known issue
  const rest = String(Math.abs(cents) % 100).padStart(2, "0");
  return `$${dollars}.${rest}`;
}
