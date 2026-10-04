/** Broker lease maximum minus its 60-second cleanup reserve. */
export function generationBudget(value: unknown): number {
  const budget = value === undefined ? 3_600_000 : value;
  if (typeof budget !== 'number' || !Number.isFinite(budget) || budget <= 0 || budget > 7_140_000) {
    throw new Error('invalid generation budget');
  }
  return budget;
}
