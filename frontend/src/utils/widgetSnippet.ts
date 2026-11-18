export interface WidgetSnippetInput {
  websiteId: string;
  apiUrl: string;
  /** Content hash of the deployed widget.js (`X-Widget-Version`), if known. */
  version?: string;
  /**
   * Per-website embed token (V3 F4). Optional: without it the snippet is
   * byte-for-byte the V2.1 one, which `EMBED_TOKEN_MODE=compat` still accepts.
   */
  embedToken?: string;
}

/**
 * Shown when the API did not report a version. The snippet must never fall back
 * to a bare `/widget.js` URL: without `?v=` a deploy can leave embedded sites on
 * a cached, stale widget, which is exactly what the version token prevents.
 */
export const WIDGET_VERSION_PLACEHOLDER = '<WIDGET_VERSION>';

/** `?v=<version>`, or `?v=<WIDGET_VERSION>` when the version is unknown. */
export function widgetVersionQuery(version?: string): string {
  const trimmed = (version || '').trim();
  return `?v=${trimmed || WIDGET_VERSION_PLACEHOLDER}`;
}

/**
 * The raw token is interpolated into an HTML page, and the snippet is meant to be
 * copy-pasted, so anything outside the alphabet the server mints (`emb_` +
 * url-safe characters) is dropped. A tampered token must not be able to close the
 * string or inject a tag; it simply produces a token the server refuses.
 */
function snippetToken(raw?: string): string {
  return (raw || '').trim().replace(/[^A-Za-z0-9_-]/g, '');
}

/** The copy-paste install snippet for one website. */
export function buildWidgetSnippet({
  websiteId,
  apiUrl,
  version,
  embedToken,
}: WidgetSnippetInput): string {
  const base = (apiUrl || '').replace(/\/+$/, '');
  const token = snippetToken(embedToken);
  // Kept as a separate line so a tokenless snippet is unchanged, not merely
  // equivalent.
  const tokenLine = token ? `,\n    embedToken: '${token}'` : '';

  return `<!-- Site GPT Chat Widget -->
<script>
  window.ChatWidgetConfig = {
    website_id: '${websiteId}',
    apiUrl: '${base}'${tokenLine}
  };
</script>
<script src="${base}/widget.js${widgetVersionQuery(version)}" async></script>`;
}
