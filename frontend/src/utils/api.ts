import axios, { AxiosInstance } from 'axios';
import type { ChatResponse, FeedbackRequest, LoginResponse, WidgetConfig } from '../types/api';

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

export type { LoginResponse } from '../types/api';
