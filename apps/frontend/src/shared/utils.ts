/** Format an ISO timestamp string to a local-friendly display format. */
export function formatTimestamp(iso: string | unknown): string {
  return String(iso ?? '').replace('T', ' ').slice(0, 19);
}
