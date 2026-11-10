export interface RobotHardware {
  mcu: string;
  mic: string;
  speaker: string;
  display: string;
}

export interface RobotItem {
  id: string;
  name: string;
  type: string;
  agent: string;
  status: 'active' | 'offline' | 'registered' | 'unknown';
  hardware: RobotHardware;
  firmware: string;
  last_active: string;
}

export interface AssistantItem {
  id: string;
  name: string;
  model: string;
  voice_role: string;
  knowledge_source: string;
  status: 'active' | 'paused' | 'unknown';
  tools: string[];
  device_id: string;
}

export interface DatabaseStats {
  public_searchable: number;
  total_pages: number;
  seed_pages: number;
  scraped_pages: number;
}

export interface SyncHistoryItem {
  id: number;
  started_at: string;
  completed_at: string;
  status: 'success' | 'partial' | 'failed';
  duration_seconds: number;
  total_discovered: number;
  valid_urls?: number;
  batch_target_count?: number;
  pages_added: number;
  pages_updated: number;
  pages_unchanged: number;
  pages_failed: number;
  pages_skipped?: number;
  crawl_cursor?: number;
  trigger_type: string;
  error_summary?: string;
}

export interface SyncEngineStats {
  is_syncing: boolean;
  auto_sync_enabled: boolean;
  schedule_times: string[];
  next_scheduled_run: string;
  crawl_cursor: number;
  total_discovered: number;
  valid_urls: number;
  last_sync: SyncHistoryItem | null;
}

export interface MCPStats {
  connection_status: string;
  connection_configured: boolean;
  tools_registered: number;
  tools_list: string[];
}

export interface DashboardStats {
  uptime_seconds: number;
  service: string;
  version: string;
  backend_status: string;
  database: DatabaseStats;
  sync_engine: SyncEngineStats;
  mcp_bridge: MCPStats;
  robots: RobotItem[];
  assistants: AssistantItem[];
  categories_distribution: Record<string, number>;
  recent_syncs: SyncHistoryItem[];
}

export interface KnowledgeItem {
  id: number;
  url: string;
  title: string;
  category: string;
  content: string;
  content_hash: string;
  last_modified: string | null;
  retrieved_at: string | null;
  source_type: 'seed' | 'scraped';
  http_status: number;
  char_count: number;
  content_length?: number;
  updated_at?: string;
}

export interface KnowledgeResponse {
  items: KnowledgeItem[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
  categories: string[];
}

export interface MCPToolDetail {
  name: string;
  title: string;
  description: string;
  category: string;
  parameters: Record<string, any>;
  inputSchema?: Record<string, any>;
  sample_arguments: Record<string, any>;
  status: string;
}

export interface LogEntry {
  id: number;
  timestamp: string;
  level: 'INFO' | 'WARNING' | 'ERROR';
  source: string;
  message: string;
}

export interface SyncReportResult {
  started_at: string;
  completed_at: string;
  status: string;
  duration_seconds: number;
  total_discovered: number;
  valid_urls: number;
  batch_target_count: number;
  pages_added: number;
  pages_updated: number;
  pages_unchanged: number;
  pages_failed: number;
  pages_skipped: number;
  crawl_cursor: number;
  trigger_type: string;
  error_summary: string;
  changes: Array<{ url: string; action: string; title: string }>;
  skipped_details: Array<{ url: string; reason: string }>;
}
