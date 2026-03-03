export interface ApiErrorPayload {
  error?: {
    code?: string;
    message?: string;
    trace_id?: string;
  };
  [key: string]: unknown;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  admin: {
    username: string;
  };
}

export interface AdminProfile {
  username: string;
  exp: number;
  iat: number;
}

export interface SessionState {
  baseUrl: string;
  token: string;
  username: string;
  exp?: number;
}

export interface HealthPayload {
  status: string;
  service?: string;
  timestamp?: string;
  nodes: {
    total: number;
    enabled: number;
    healthy: number;
  };
  keys: {
    total: number;
    enabled: number;
    healthy: number;
    total_requests: number;
    total_failures: number;
  };
  // Backward compatibility for earlier payload shape
  node_pool?: {
    total: number;
    enabled: number;
    healthy: number;
  };
  key_pool?: {
    total: number;
    enabled: number;
    healthy: number;
    total_requests: number;
    total_failures: number;
  };
}

export interface NodeItem {
  id: string;
  base_url: string;
  enabled: boolean;
  healthy: boolean;
  active_connections: number;
  fail_count: number;
  total_requests: number;
  total_failures: number;
  last_error: string | null;
  last_checked_at: string | null;
}

export interface KeyItem {
  id: string;
  key: string;
  enabled: boolean;
  healthy: boolean;
  total_requests: number;
  total_failures: number;
  fail_count: number;
  last_error: string | null;
  cooldown_until: string | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
}

export interface StatsPayload {
  health: HealthPayload;
  nodes: NodeItem[];
  keys: KeyItem[];
}

export interface LogItem {
  ts: number;
  time: string;
  level: string;
  event: string;
  detail: string;
}

export interface SearxCompatSettings {
  enabled: boolean;
  username: string;
  has_password: boolean;
  search_path: string;
}
