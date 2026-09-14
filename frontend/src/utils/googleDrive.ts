// Google Drive Picker helper (loaded on demand, only when a client id is set).
// Uses Google Identity Services for the OAuth token + the Picker API to let the
// user select files. The selected file id + access token are returned to the
// caller, which forwards them to the backend /uploads/google-drive endpoint.
//
// TypeScript can't see the global `google` object, so we treat it as `any`.

const GSI_SRC = 'https://accounts.google.com/gsi/client';
const GAPI_SRC = 'https://apis.google.com/js/api.js';

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) {
      resolve();
      return;
    }
    const el = document.createElement('script');
    el.src = src;
    el.async = true;
    el.onload = () => resolve();
    el.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.body.appendChild(el);
  });
}

function extractDriveFileId(input: string): string | null {
  const s = input.trim();
  if (!s) return null;
  const fileMatch = s.match(/\/file\/d\/([^/?]+)/);
  if (fileMatch) return fileMatch[1];
  const idMatch = s.match(/[?&]id=([^&]+)/);
  if (idMatch) return idMatch[1];
  // Assume the user pasted a raw file id.
  if (/^[A-Za-z0-9_-]{20,}$/.test(s)) return s;
  return null;
}

export { extractDriveFileId };

/**
 * Open the Google Picker and resolve with the selected [{ id, name, token }].
 * Requires a configured OAuth client id (Google Cloud, with the Picker API
 * enabled and the origin authorized). The `token` is the OAuth access token
 * needed by the backend to fetch the (private) file.
 */
export async function pickGoogleDriveFiles(
  clientId: string,
): Promise<Array<{ id: string; name: string; token: string }>> {
  await loadScript(GSI_SRC);
  await loadScript(GAPI_SRC);

  const google = (window as any).google;
  if (!google || !google.accounts || !google.accounts.oauth2) {
    throw new Error('Google Identity Services failed to load');
  }

  // 1) Get an access token via the GIS token client.
  const tokenResponse = await new Promise<any>((resolve, reject) => {
    const client = google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope: 'https://www.googleapis.com/auth/drive.file',
      callback: (resp: any) => {
        if (resp.error) reject(new Error(resp.error));
        else resolve(resp);
      },
    });
    client.requestAccessToken({ prompt: '' });
  });

  const accessToken = tokenResponse.access_token;

  // 2) Load the Picker and show it.
  await new Promise<void>((resolve) => google.gapi.load('picker', resolve));

  return new Promise<Array<{ id: string; name: string; token: string }>>(
    (resolve) => {
      const docsView = new google.picker.DocsView(google.picker.ViewId.DOCS)
        .setIncludeFolders(false)
        .setMimeTypes(
          'application/pdf,text/plain,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        .setSelectFolderEnabled(false);

      const picker = new google.picker.PickerBuilder()
        .addView(docsView)
        .setOAuthToken(accessToken)
        .setDeveloperKey('')
        .setCallback((data: any) => {
          if (
            data.action === google.picker.Action.PICKED ||
            data.action === google.picker.Action.SELECTED
          ) {
            const docs = (data.docs || []).map((d: any) => ({
              id: d.id,
              name: d.name,
              token: accessToken,
            }));
            resolve(docs);
          } else if (data.action === google.picker.Action.CANCEL) {
            resolve([]);
          }
        })
        .build();
      picker.setVisible(true);
    },
  );
}
