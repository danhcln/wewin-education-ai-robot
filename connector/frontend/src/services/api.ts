import {
  DashboardStats,
  KnowledgeResponse,
  KnowledgeItem,
  MCPToolDetail,
  LogEntry,
  SyncReportResult
} from '../types';
import {browserSession,getBrowserCsrf} from './browserSession';

const API_BASE = ''; // relative path uses Vite proxy or FastAPI origin

export const TOKEN_STORAGE_KEY = 'wewin_admin_token';
export const UNAUTHORIZED_EVENT = 'wewin:unauthorized';

export function getAdminToken(): string {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY); // Discard credentials from older builds.
    return sessionStorage.getItem(TOKEN_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

export function setAdminToken(token: string): void {
  sessionStorage.setItem(TOKEN_STORAGE_KEY, token.trim());
}

export function clearAdminToken(): void {
  try {
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // Access remains denied even when browser storage is unavailable.
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  if(headers.get('Authorization')?.trim()==='Bearer')headers.delete('Authorization');
  const adminRequest = endpoint.startsWith('/sync') ||
    endpoint.startsWith('/api/dashboard/') || endpoint.startsWith('/api/knowledge/') ||
    endpoint.startsWith('/api/system/');
  if (adminRequest && !headers.has('Authorization')) {
    const token = getAdminToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);
  }
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  if(adminRequest&&!getAdminToken()){
    if(!getBrowserCsrf())await browserSession();
    if(options.method&& !['GET','HEAD'].includes(options.method.toUpperCase()))headers.set('X-WeWIN-CSRF',getBrowserCsrf());
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
    cache: 'no-store'
  });

  if (!response.ok) {
    if (response.status === 401 && adminRequest) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    let errorDetail = response.statusText;
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || errJson.message || JSON.stringify(errJson);
    } catch {
      // fallback to statusText
    }
    throw new Error(`[HTTP ${response.status}] ${errorDetail}`);
  }

  return response.json();
}

export const api = {
  // Auth
  async verifyToken(token: string): Promise<{ valid: boolean; message: string; role: string }> {
    return request('/api/auth/verify', {
      method: 'POST',
      body: JSON.stringify({ token })
    });
  },

  // Dashboard
  async getDashboardStats(): Promise<DashboardStats> {
    return request<DashboardStats>('/api/dashboard/stats');
  },

  // Knowledge Manager
  async getKnowledgePages(params: {
    page?: number;
    limit?: number;
    search?: string;
    category?: string;
    source_type?: string;
  }): Promise<KnowledgeResponse> {
    const sp = new URLSearchParams();
    if (params.page) sp.set('page', params.page.toString());
    if (params.limit) sp.set('limit', params.limit.toString());
    if (params.search) sp.set('search', params.search);
    if (params.category && params.category !== 'all') sp.set('category', params.category);
    if (params.source_type && params.source_type !== 'all') sp.set('source_type', params.source_type);
    
    return request<KnowledgeResponse>(`/api/knowledge/pages?${sp.toString()}`);
  },

  async getPageContent(url: string): Promise<KnowledgeItem> {
    const sp = new URLSearchParams({ url });
    return request<KnowledgeItem>(`/page?${sp.toString()}`);
  },

  async searchKnowledge(q: string, limit: number = 4) {
    const sp = new URLSearchParams({ q, limit: limit.toString() });
    return request<{ query: string; total_results: number; results: any[] }>(`/search?${sp.toString()}`);
  },

  // Sync Manager
  async getSyncStatus() {
    return request<any>('/sync/status', {
      headers: {
        Authorization: `Bearer ${getAdminToken()}`
      }
    });
  },

  async getSyncHistory(limit: number = 15) {
    return request<{ total_records: number; history: any[] }>(`/sync/history?limit=${limit}`, {
      headers: {
        Authorization: `Bearer ${getAdminToken()}`
      }
    });
  },

  async triggerSync(options: { maxPages?: number; allPages?: boolean; dryRun?: boolean } = {}): Promise<{
    success: boolean;
    message: string;
    total_indexed: number;
    report: SyncReportResult;
  }> {
    const sp = new URLSearchParams();
    if (options.maxPages) sp.set('max_pages', options.maxPages.toString());
    if (options.allPages) sp.set('all_pages', 'true');
    if (options.dryRun) sp.set('dry_run', 'true');

    return request(`/sync?${sp.toString()}`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${getAdminToken()}`
      }
    });
  },

  async unlockSync(): Promise<{ success: boolean; message: string }> {
    return request('/sync/unlock', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${getAdminToken()}`
      }
    });
  },

  // MCP Tools
  async getMCPTools(): Promise<{ total: number; tools: MCPToolDetail[] }> {
    return request<{ total: number; tools: MCPToolDetail[] }>('/api/mcp/tools');
  },

  async executeTool(toolName: string, args: Record<string, any>): Promise<any> {
    return request('/api/xiaozhi/tool', {
      method: 'POST',
      body: JSON.stringify({
        tool: toolName,
        arguments: args
      })
    });
  },

  // System Logs
  async getSystemLogs(limit: number = 50): Promise<{ total: number; logs: LogEntry[] }> {
    return request<{ total: number; logs: LogEntry[] }>(`/api/system/logs?limit=${limit}`);
  }
};
