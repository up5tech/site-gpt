export interface Company {
  id: string;
  name: string;
  description: string;
  created_at: string;
}

export interface CompanyPaginated {
  total: number;
  page: number;
  limit: number;
  items: Company[];
}

export interface User {
  id: string;
  created_at: string;
  company_id: string;
  email: string;
  phone?: string;
  first_name: string;
  last_name: string;
  role?: string;
  status?: string;
}

export interface Website {
  id: string;
  name: string;
  url: string;
  description?: string;
  site_map_url: string;
  company_id: string;
  created_at: string;
  updated_at: string;
}

export interface WebsitePage {
  id: string;
  url: string;
  name: string;
  description?: string;
  website_id: string;
  created_at: string;
  updated_at: string;
}

export interface WebsitePagePaginated {
  total: number;
  page: number;
  limit: number;
  items: WebsitePage[];
}

export interface ChatResponse {
  answer: string;
}

export interface RegisterRequest {
  company_name: string;
  first_name: string;
  last_name: string;
  email: string;
  password: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}
