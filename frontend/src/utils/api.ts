import axios, { AxiosInstance } from 'axios';
import type { AnalyticsSummary, ChatResponse, ContactList, ConversationList, ConversationMessages, DashboardStats, DigestPreview, DigestSendResult, FeedbackItem, FeedbackList, FeedbackRequest, FeedbackReview, HandoffList, HandoffUpdate, LoginResponse, RecentConversations, RegisterRequest, Setting, Website, WebsiteQuota, WidgetConfig } from '../types/api';

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

// Analytics and the weekly digest (F6).
export const getAnalyticsSummary = (days = 7) =>
  api.get<AnalyticsSummary>('/analytics/summary', { params: { days } });

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
