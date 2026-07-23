export const trNumberFormatter = new Intl.NumberFormat("tr-TR");

export const trCompactNumberFormatter = new Intl.NumberFormat("tr-TR", {
  notation: "compact",
  maximumFractionDigits: 1,
});
