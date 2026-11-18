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

export interface EmbedToken {
  id: string;
  website_id: string;
  token_prefix: string;
  active: boolean;
  created_at: string;
  last_used_at?: string | null;
  revoked_at?: string | null;
}

/** Mint/rotate answer: the only response that ever carries the raw token. */
export interface EmbedTokenCreated extends EmbedToken {
  token: string;
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
  /** The assistant message being rated, so the pair can be reviewed (F4). */
  message_id?: string;
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

/** One row of a company's settings registry, mirroring `SettingRes`.
 * `PUT /api/settings` only reads `key` and `value` from each entry. */
export interface RetentionPurgeResult {
  retention_days: number;
  /** Rows strictly older than this go; null when the policy is "keep for ever". */
  cutoff: string | null;
  dry_run: boolean;
  /** Rows that were (or, in a dry run, would be) deleted, per table. */
  deleted: Record<string, number>;
  total: number;
}

export interface Setting {
  id?: string;
  key: string;
  value: string;
  created_at?: string;
  updated_at?: string;
}

export interface ApiKeyItem {
  id: string;
  name: string;
  /** First characters of the key: the only part stored in a readable form. */
  key_prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at?: string | null;
  revoked_at?: string | null;
}

export interface ApiKeyCreated extends ApiKeyItem {
  /** The raw key — returned exactly once, on creation. */
  key: string;
}

export interface ApiKeyPayload {
  name: string;
  scopes: string[];
}

export type IntegrationType = 'webhook' | 'slack' | 'zendesk' | 'crisp';

export interface IntegrationItem {
  id: string;
  type: IntegrationType;
  name: string;
  /** Credentials come back masked as "***" — never the stored value. */
  config: Record<string, string>;
  events: string[];
  enabled: boolean;
  created_at: string;
  updated_at: string;
  /** Config keys that hold a secret, so the form can show a placeholder. */
  secret_fields: string[];
}

export interface IntegrationPayload {
  type?: IntegrationType;
  name?: string;
  config?: Record<string, string>;
  events?: string[];
  enabled?: boolean;
}

export interface IntegrationTestResult {
  type: string;
  delivered: boolean;
  status_code?: number | null;
  error?: string | null;
}

export type DeliveryStatus = 'pending' | 'delivered' | 'dead';

/** One tracked event → integration delivery. The payload is not exposed. */
export interface DeliveryItem {
  id: string;
  integration_id: string | null;
  integration_name: string;
  integration_type: IntegrationType;
  /** Stable across retries, so a receiver can drop duplicates. */
  event_id: string;
  event_type: string;
  status: DeliveryStatus;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  last_status_code: number | null;
  next_attempt_at: string | null;
  delivered_at: string | null;
  created_at: string;
  /** False once retention cleared the payload: the event cannot be resent. */
  payload_available: boolean;
}

export interface DeliveryList {
  items: DeliveryItem[];
  total: number;
  pending: number;
  dead: number;
  delivered: number;
}

export interface DeliveryAttempt {
  id: string;
  status: DeliveryStatus;
  attempts: number;
  delivered: boolean;
  last_error: string | null;
  next_attempt_at: string | null;
}

export interface DigestTopic {
  term: string;
  count: number;
}

export interface UnansweredQuestion {
  question?: string | null;
  website_id: string;
  website_name?: string | null;
  session_id: string;
  asked_at: string;
  link: string;
}

export interface DigestSummary {
  company_id: string;
  period_start: string;
  period_end: string;
  conversation_volume: number;
  message_count: number;
  new_contacts: number;
  feedback_up: number;
  feedback_down: number;
  top_topics: DigestTopic[];
  unanswered_questions: UnansweredQuestion[];
}

export interface AnalyticsSummary extends DigestSummary {
  days: number;
}

export interface DigestPreview {
  period_start: string;
  period_end: string;
  html: string;
  summary: DigestSummary;
}

export interface DigestSendResult {
  status: string;
  reason?: string | null;
  recipients?: number | null;
  period_start?: string | null;
}

export interface HandoffItem {
  id: string;
  website_id: string;
  website_name?: string | null;
  session_id: string;
  contact_id?: string | null;
  contact_name?: string | null;
  contact_email?: string | null;
  message?: string | null;
  status: 'pending' | 'accepted' | 'closed';
  channel?: string | null;
  created_at: string;
}

export interface HandoffList {
  total: number;
  page: number;
  limit: number;
  items: HandoffItem[];
}

export interface HandoffUpdate {
  status?: 'pending' | 'accepted' | 'closed';
}

export interface FeedbackItem {
  id: string;
  website_id: string;
  session_id: string;
  rating: 'up' | 'down';
  comment?: string | null;
  message_id?: string | null;
  status: 'pending' | 'approved' | 'rejected';
  reviewed_answer?: string | null;
  question?: string | null;
  answer?: string | null;
  created_at: string;
}

export interface FeedbackList {
  total: number;
  page: number;
  limit: number;
  items: FeedbackItem[];
}

export interface FeedbackReview {
  status?: 'pending' | 'approved' | 'rejected';
  reviewed_answer?: string;
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
