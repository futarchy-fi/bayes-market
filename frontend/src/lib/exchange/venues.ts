import type { Instrument, Venue } from "./client";

export interface InstrumentPriceChip {
  venue: Venue;
  price: string;
}

export function instrumentPriceChips(instrument: Instrument): InstrumentPriceChip[] {
  return instrument.listings.map(({ venue, yesPrice }) => ({
    venue,
    price: yesPrice === null ? "—" : `${(yesPrice * 100).toFixed(1)}%`,
  }));
}

export function validateBookOrder(price: string, size: string): string | null {
  const priceNumber = Number(price);
  const sizeNumber = Number(size);
  if (!Number.isFinite(priceNumber) || priceNumber <= 0 || priceNumber >= 1) return "Price must be between 0 and 1.";
  if (!Number.isFinite(sizeNumber) || sizeNumber <= 0) return "Size must be greater than 0.";
  return null;
}
