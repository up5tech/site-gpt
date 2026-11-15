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

export interface WebsiteQuota {
  website_id: string;
  date: string;
  used: number | null;
  limit: number;
  unlimited: boolean;
  remaining: number | null;
  near_limit: boolean;
  available: boolean;
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

export interface ConversationMessage {
  id: string;
  session_id: string;
  website_id: string;
  role: 'user' | 'assistant';
  message: string;
  created_at: string;
}

export interface ConversationSummary {
  session_id: string;
  website_id: string;
  title: string | null;
  message_count: number;
  created_at: string;
  last_message_at: string;
}

export interface ConversationList {
  items: ConversationSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ConversationMessages {
  items: ConversationMessage[];
}

export interface RecentConversation {
  session_id: string;
  website_id: string;
  website_name: string;
  title: string | null;
  message_count: number;
  last_message_at: string;
}

export interface RecentConversations {
  items: RecentConversation[];
}

export interface Contact {
  id: string;
  website_id: string;
  session_id: string;
  first_name: string;
  last_name: string;
  email: string;
  created_at: string;
  updated_at: string;
}

export interface ContactList {
  items: Contact[];
  total: number;
  limit: number;
  offset: number;
}

/** One row of a company's settings registry (`GET`/`PUT /api/settings`). */
export interface Setting {
  id?: string;
  company_id?: string;
  key: string;
  value: string;
  created_at?: string;
  updated_at?: string;
}

/**
 * Known keys of the public widget config. Every field is optional: the endpoint
 * only returns allowlisted keys the company actually has a row for, and each V2
 * feature ships off/empty by default.
 */
export interface WidgetSettings {
  // V1 appearance keys.
  assistant_name?: string;
  widget_header_color?: string;
  widget_footer_color?: string;
  widget_position?: 'bottom-left' | 'bottom-right';
  greeting_message?: string;
  placeholder_text?: string;
  suggested_questions?: string;
  // V2 widget-facing keys (`plans/SPEC.md` §9). Booleans are strings here,
  // like every other setting value.
  widget_language?: string; // 'auto' or a BCP-47 code
  widget_ui_strings?: string; // JSON overrides for the widget's own labels
  widget_logo_url?: string;
  handoff_enabled?: 'true' | 'false';
  handoff_label?: string;
  require_consent?: 'true' | 'false';
  privacy_policy_url?: string;
}

/** Public widget config fetched by the embeddable widget (key/value map). */
export type WidgetConfig = Record<string, string> & Partial<WidgetSettings>;

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
