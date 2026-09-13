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
  status: string;
  ingest_status: string;
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
  sources?: ChatSource[];
}

export interface DashboardStats {
  total_websites: number;
  indexed_websites: number;
  ingesting_websites: number;
  total_documents: number;
  total_chat_messages: number;
  team_members: number;
}

export interface ChatSource {
  title?: string | null;
  url?: string | null;
  source_type?: string | null; // "page" | "document"
}

export interface FeedbackRequest {
  website_id: string;
  session_id: string;
  rating: 'up' | 'down';
  comment?: string;
}

/** Public widget config fetched by the embeddable widget (key/value map). */
export type WidgetConfig = Record<string, string>;

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
