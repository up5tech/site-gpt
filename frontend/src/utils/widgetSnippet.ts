export interface WidgetSnippetInput {
  websiteId: string;
  apiUrl: string;
  /** Content hash of the deployed widget.js (`X-Widget-Version`), if known. */
  version?: string;
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

/** The copy-paste install snippet for one website. */
export function buildWidgetSnippet({
  websiteId,
  apiUrl,
  version,
}: WidgetSnippetInput): string {
  const base = (apiUrl || '').replace(/\/+$/, '');

  return `<!-- Site GPT Chat Widget -->
<script>
  window.ChatWidgetConfig = {
    website_id: '${websiteId}',
    apiUrl: '${base}'
  };
</script>
<script src="${base}/widget.js${widgetVersionQuery(version)}" async></script>`;
}
