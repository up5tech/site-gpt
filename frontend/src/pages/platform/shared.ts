import type { AxiosError } from 'axios';

/** Human message from an API error without leaking a stack or request body. */
export function platformErrorMessage(error: unknown, fallback: string): string {
  const response = (error as AxiosError<{ detail?: unknown }>)?.response;
  const detail = response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (response?.status === 404) return 'The platform console is not enabled.';
  if (response?.status === 403) return 'Operator access is required.';
  return fallback;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  return new Date(value).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

/** Integer minor units → a display price. Mirrors the public pricing page. */
export function formatMoney(minor: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: currency.toUpperCase(),
    }).format(minor / 100);
  } catch {
    return `${(minor / 100).toFixed(2)} ${currency.toUpperCase()}`;
  }
}

/** "websites=1\nseats=3" → { websites: 1, seats: 3 } with validation. */
export function parseLimits(text: string): Record<string, number> {
  const limits: Record<string, number> = {};
  for (const line of text.split('\n')) {
    const value = line.trim();
    if (!value) continue;
    const [key, raw] = value.split('=');
    const parsed = Number(raw);
    if (!key?.trim() || !Number.isInteger(parsed) || parsed < 0) {
      throw new Error(`Invalid limit line: ${value}`);
    }
    limits[key.trim()] = parsed;
  }
  return limits;
}

export function limitsText(limits: Record<string, number>): string {
  return Object.entries(limits)
    .map(([key, value]) => `${key}=${value}`)
    .join('\n');
}
