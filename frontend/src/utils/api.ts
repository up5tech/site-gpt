import axios, { AxiosInstance } from 'axios';
import type { LoginResponse } from '../types/api';

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

export const chat = (q: string) => api.get(`/chat?q=${encodeURIComponent(q)}`);

export const ingest = (sitemapUrl: string) =>
  api.post('/ingest', { sitemap_url: sitemapUrl });

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
