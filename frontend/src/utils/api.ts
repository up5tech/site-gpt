import axios, { AxiosInstance } from 'axios';
import type { ChatResponse, ConversationList, ConversationMessages, DashboardStats, FeedbackRequest, LoginResponse, RecentConversations, WidgetConfig } from '../types/api';

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

// API functions
export const register = (data: any) => api.post('/register', data);

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

export const getWidgetConfig = (websiteId: string) =>
  api.get<WidgetConfig>('/widget-config', {
    params: { website_id: websiteId },
  });

export const ingest = (websiteId: string) =>
  api.post('/ingest', null, { params: { website_id: websiteId } });

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

export type { LoginResponse } from '../types/api';
