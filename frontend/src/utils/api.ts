import axios, { AxiosInstance } from 'axios';
import type { AnalyticsSummary, ApiKeyCreated, ApiKeyItem, ApiKeyPayload, BillingStatus, BillingSummary, BillingUrl, BillingUsage, ChatResponse, ContactList, ConversationList, ConversationMessages, DashboardStats, DeliveryAttempt, DeliveryList, DeliveryStatus, DigestPreview, DigestSendResult, FeedbackItem, FeedbackList, FeedbackRequest, FeedbackReview, HandoffList, HandoffUpdate, InboxConversation, InboxConversationDetail, InboxList, InboxMessage, InboxPresence, InboxState, InboxStatus, IntegrationItem, IntegrationPayload, IntegrationTestResult, LoginResponse, PublicPlanList, RecentConversations, RegisterRequest, RetentionPurgeResult, Setting, Website, WebsiteQuota, WidgetConfig } from '../types/api';

// Base API instance with proxy /api -> backend
const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_BACKEND_URL + '/api',
});

// Request interceptor to add token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;

// Auth helpers
export const setAuthToken = (token: string) => {
  localStorage.setItem('access_token', token);
};

export const clearAuthToken = () => {
  localStorage.removeItem('access_token');
};

export const getAuthToken = (): string | null => {
  return localStorage.getItem('access_token');
};

/**
 * Human-readable message for a failed API call: the backend's `detail` when it
 * sent one, otherwise the caller's fallback text. Keeps `catch` blocks typed
 * without reaching into `error.response` untyped.
 */
/**
 * HTTP status of a failed API call, or undefined when it never reached the
 * server. Callers use it to decide whether the response is worth showing.
 */
export const getApiErrorStatus = (error: unknown): number | undefined =>
  axios.isAxiosError(error) ? error.response?.status : undefined;

export const getApiErrorMessage = (
  error: unknown,
  fallback: string,
): string => {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { detail?: string } | undefined;
    if (typeof data?.detail === 'string' && data.detail) return data.detail;
  }
  return fallback;
};

// API functions
export const register = (data: RegisterRequest) => api.post('/register', data);

export const login = (email: string, password: string) =>
  api.post<LoginResponse>('/token', { email: email, password });

export const chat = (
  websiteId: string,
  sessionId: string,
  question: string,
) => api.post<ChatResponse>('/chat', {
  website_id: websiteId,
  session_id: sessionId,
  question,
});

export const sendFeedback = (payload: FeedbackRequest) =>
  api.post('/chat/feedback', payload);

// Feedback review (admin): the 👎 queue, the decision, and the Q&A rebuild.
export const getFeedback = (
  params: {
    website_id?: string;
    status?: 'pending' | 'approved' | 'rejected';
    rating?: 'up' | 'down';
    page?: number;
    limit?: number;
  } = {},
) => api.get<FeedbackList>('/feedback', { params });

export const reviewFeedback = (id: string, payload: FeedbackReview) =>
  api.patch<FeedbackItem>(`/feedback/${id}`, payload);

// Handoff requests (F5): the widget's request shows up here for the team.
export const getHandoffs = (
  params: {
    website_id?: string;
    status?: 'pending' | 'accepted' | 'closed';
    page?: number;
    limit?: number;
  } = {},
) => api.get<HandoffList>('/handoffs', { params });

export const updateHandoff = (id: string, payload: HandoffUpdate) =>
  api.patch(`/handoffs/${id}`, payload);

// Company API keys for /api/v1 (F8). The raw key is only in the create response.
export const getApiKeys = () => api.get<ApiKeyItem[]>('/api/api-keys/');

export const createApiKey = (payload: ApiKeyPayload) =>
  api.post<ApiKeyCreated>('/api/api-keys/', payload);

export const revokeApiKey = (id: string) =>
  api.delete(`/api/api-keys/${id}`);

// Outbound integrations (F7). Reads are masked server-side.
export const getIntegrations = () =>
  api.get<IntegrationItem[]>('/integrations/');

export const createIntegration = (payload: IntegrationPayload) =>
  api.post<IntegrationItem>('/integrations/', payload);

export const updateIntegration = (id: string, payload: IntegrationPayload) =>
  api.patch<IntegrationItem>(`/integrations/${id}`, payload);

export const deleteIntegration = (id: string) =>
  api.delete(`/integrations/${id}`);

export const testIntegration = (id: string) =>
  api.post<IntegrationTestResult>(`/integrations/${id}/test`);

// Tracked deliveries: every event is stored before it is sent, retried with
// backoff, and parked as `dead` when the attempts run out.
export const getIntegrationDeliveries = (params?: {
  integration_id?: string;
  status?: DeliveryStatus;
}) => api.get<DeliveryList>('/integrations/deliveries', { params });

export const resendIntegrationDelivery = (id: string) =>
  api.post<DeliveryAttempt>(`/integrations/deliveries/${id}/resend`);

// Analytics and the weekly digest (F6).
export const getAnalyticsSummary = (days = 7) =>
  api.get<AnalyticsSummary>('/analytics/summary', { params: { days } });

/**
 * Download the window's aggregate CSV (V4-11). A plain link cannot carry the
 * JWT, so the file is fetched as a blob and saved under the filename the server
 * chose in `Content-Disposition` (it carries the window's dates).
 */
export const exportAnalyticsCsv = async (days = 7) => {
  const response = await api.get<Blob>('/analytics/export.csv', {
    params: { days },
    responseType: 'blob',
  });
  const disposition = String(response.headers['content-disposition'] ?? '');
  const filename = disposition.match(/filename="?([^";]+)"?/)?.[1];
  const url = URL.createObjectURL(response.data);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename ?? `analytics-${days}d.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

export const previewDigest = () =>
  api.post<DigestPreview>('/digest/preview');

export const sendDigestNow = () =>
  api.post<DigestSendResult>('/digest/send-now');

export const rebuildQa = (websiteId: string) =>
  api.post<{ status: string; approved: number; chunks: number }>(
    '/feedback/rebuild',
    null,
    { params: { website_id: websiteId } },
  );

export const getWidgetConfig = (websiteId: string) =>
  api.get<WidgetConfig>('/widget-config', {
    params: { website_id: websiteId },
  });

export const ingest = (websiteId: string) =>
  api.post('/ingest', null, { params: { website_id: websiteId } });

// Company settings. `PUT` upserts, so a key added after the company was created
// still persists; internal keys never come back through the widget config.
export const getSettings = () => api.get<Setting[]>('/settings');

export const updateSettings = (settings: Pick<Setting, 'key' | 'value'>[]) =>
  api.put('/settings', settings);

// Retention preview: asks what the purge would delete, without deleting it. The
// days override lets an owner try a policy before saving it.
export const previewRetentionPurge = (retentionDays: number) =>
  api.post<RetentionPurgeResult>('/privacy/retention', {
    dry_run: true,
    retention_days: retentionDays,
  });

// The destructive half of the same call: `dry_run: false` deletes now instead of
// waiting for the daily worker. The UI only reaches this behind a confirmation.
export const applyRetentionPurge = (retentionDays: number) =>
  api.post<RetentionPurgeResult>('/privacy/retention', {
    dry_run: false,
    retention_days: retentionDays,
  });

// Conversation history (admin panel)
export const getConversations = (websiteId: string, params: { limit?: number; offset?: number } = {}) =>
  api.get<ConversationList>('/conversations', {
    params: { website_id: websiteId, ...params },
  });

export const getConversationMessages = (websiteId: string, sessionId: string) =>
  api.get<ConversationMessages>('/conversations/' + encodeURIComponent(sessionId), {
    params: { website_id: websiteId },
  });

export const deleteConversation = (websiteId: string, sessionId: string) =>
  api.delete('/conversations/' + encodeURIComponent(sessionId), {
    params: { website_id: websiteId },
  });

// Live-agent inbox (V3-44). `getInboxStatus` is the navigation gate: it answers
// `{enabled}` for a manager instead of the 404 the rest of the surface gives
// when the company has not turned the inbox on.

/**
 * Settings caches nothing, but the navigation reads the flag once per session.
 * Saving the live-inbox switch fires this so it re-reads `getInboxStatus` and
 * adds or removes the `/inbox` link without a page reload.
 */
export const INBOX_STATUS_CHANGED = 'inbox-status-changed';

export const notifyInboxStatusChanged = () => {
  window.dispatchEvent(new Event(INBOX_STATUS_CHANGED));
};
export const getInboxStatus = () => api.get<InboxStatus>('/inbox/status');

export const getInboxConversations = (
  params: {
    state?: InboxState;
    website_id?: string;
    assigned_user_id?: string;
    page?: number;
    limit?: number;
  } = {},
) => api.get<InboxList>('/inbox/conversations', { params });

export const getInboxConversation = (id: string) =>
  api.get<InboxConversationDetail>(`/inbox/conversations/${id}`);

export const claimInboxConversation = (id: string) =>
  api.post<InboxConversation>(`/inbox/conversations/${id}/claim`);

export const releaseInboxConversation = (id: string) =>
  api.post<InboxConversation>(`/inbox/conversations/${id}/release`);

export const closeInboxConversation = (id: string) =>
  api.post<InboxConversation>(`/inbox/conversations/${id}/close`);

export const sendInboxReply = (id: string, message: string) =>
  api.post<InboxMessage>(`/inbox/conversations/${id}/messages`, { message });

export const getInboxPresence = () =>
  api.get<InboxPresence[]>('/inbox/presence');

/**
 * The console's event stream, opened with `fetch()`: `EventSource` cannot send
 * the JWT `Authorization` header. The caller owns the abort signal and reads
 * the body itself.
 */
export const openInboxEvents = (signal: AbortSignal) =>
  fetch(`${import.meta.env.VITE_BACKEND_URL}/api/inbox/events`, {
    headers: { Authorization: `Bearer ${getAuthToken() || ''}` },
    signal,
  });

// Contacts (visitors who filled the widget pre-chat form)
export const getContacts = (websiteId: string, params: { limit?: number; offset?: number } = {}) =>
  api.get<ContactList>('/contacts', {
    params: { website_id: websiteId, ...params },
  });

// Dashboard: latest conversations across the whole company
export const getRecentConversations = (limit = 5) =>
  api.get<RecentConversations>('/conversations/recent', {
    params: { limit },
  });

export const getCompanies = (
  params: { name?: string; page?: number; limit?: number } = {},
) => api.get('/companies', { params });

export const getCurrentCompany = () => api.get(`/companies/current`);

export const getCompanyUsers = (params: {
  name?: string;
  role?: string;
  email?: string;
  page?: number;
  limit?: number;
}) => api.get(`/companies/users`, { params });

export const getDashboardStats = () =>
  api.get<DashboardStats>('/websites/stats');

export const getWebsites = (params: { page?: number; limit?: number } = {}) =>
  api.get<{ total: number; page: number; limit: number; items: Website[] }>(
    '/websites',
    { params: { page: 1, limit: 100, ...params } },
  );

// Today's chat usage against the website's daily cap (owner-facing).
export const getWebsiteQuota = (websiteId: string) =>
  api.get<WebsiteQuota>(`/websites/${websiteId}/quota`);

export type { LoginResponse } from '../types/api';

// Public plan catalog (V5-11). Unauthenticated and read-only: the pricing page
// renders exactly what the server publishes, prices included.
export const getPlans = () => api.get<PublicPlanList>('/plans');

// Billing (V5 F2). Checkout and the portal return a Stripe-hosted URL; the
// browser never posts a price, amount, customer or return URL.
export const getBillingStatus = () =>
  api.get<BillingStatus>('/billing/status');

export const getBillingSummary = () =>
  api.get<BillingSummary>('/billing/subscription');

export const startBillingCheckout = (planCode: string) =>
  api.post<BillingUrl>('/billing/checkout', { plan_code: planCode });

export const openBillingPortal = () =>
  api.post<BillingUrl>('/billing/portal');

// Plan state and countable usage for the console Billing page (V5-32).
// Read-only and company-scoped; only admins may change billing.
export const getBillingUsage = () => api.get<BillingUsage>('/billing/usage');


// -- Platform owner console (V5 Wave 4). Every route answers 404 while
// PLATFORM_CONSOLE_ENABLED is false and 403 for anyone without an active grant.

export const getPlatformSession = () =>
  api.get<import('../types/api').PlatformSession>('/platform/session');

export const getPlatformOverview = () =>
  api.get<import('../types/api').PlatformOverview>('/platform/overview');

export const getPlatformCompanies = (params: {
  search?: string;
  page?: number;
  page_size?: number;
}) => api.get<import('../types/api').PlatformCompanyList>('/platform/companies', { params });

export const getPlatformSubscriptions = (params: {
  status?: string;
  search?: string;
  page?: number;
  page_size?: number;
}) => api.get<import('../types/api').PlatformSubscriptionList>('/platform/subscriptions', { params });

export const runPlatformSubscriptionAction = (
  companyId: string,
  body: {
    action: import('../types/api').PlatformSubscriptionAction;
    reason: string;
    confirm?: boolean;
  },
) =>
  api.post<import('../types/api').PlatformActionResult>(
    `/platform/subscriptions/${companyId}/actions`,
    body,
  );

export const getPlatformPlans = () =>
  api.get<import('../types/api').PlatformPlanList>('/platform/plans');

export const createPlatformPlan = (body: Record<string, unknown>) =>
  api.post<import('../types/api').PlatformPlan>('/platform/plans', body);

export const updatePlatformPlan = (code: string, body: Record<string, unknown>) =>
  api.put<import('../types/api').PlatformPlan>(`/platform/plans/${code}`, body);

export const addPlatformPlanPrice = (code: string, body: Record<string, unknown>) =>
  api.post<import('../types/api').PlatformPlan>(`/platform/plans/${code}/prices`, body);

export const publishPlatformPlan = (code: string, reason: string) =>
  api.post<import('../types/api').PlatformPlan>(`/platform/plans/${code}/publish`, {
    reason,
    confirm: true,
  });

export const archivePlatformPlan = (code: string, reason: string) =>
  api.post<import('../types/api').PlatformPlan>(`/platform/plans/${code}/archive`, {
    reason,
    confirm: true,
  });

export const getPlatformSettings = () =>
  api.get<import('../types/api').PlatformSettingList>('/platform/settings');

export const previewPlatformSetting = (key: string, value: string) =>
  api.post<{ key: string; current: string; next: string; changed: boolean }>(
    `/platform/settings/${key}/preview`,
    { value },
  );

export const updatePlatformSetting = (
  key: string,
  body: { value: string; reason: string; confirm?: boolean },
) => api.put<import('../types/api').PlatformSetting>(`/platform/settings/${key}`, body);

export const getPlatformAudit = (limit = 50) =>
  api.get<import('../types/api').PlatformAuditList>('/platform/audit', {
    params: { limit },
  });

/** Anonymous display values (V5-43); empty strings mean "hide". */
export const getPublicConfig = () =>
  api.get<import('../types/api').PublicConfig>('/public/config');
