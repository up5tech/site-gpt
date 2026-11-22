import { useEffect } from 'react';

/**
 * Sets the document title for a public page (V5-13). The console keeps the app
 * title, so the previous value is restored when the page unmounts.
 */
export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = title;
    return () => {
      document.title = 'Site GPT';
    };
  }, [title]);
}
