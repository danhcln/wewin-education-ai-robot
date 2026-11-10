"""
Pydantic schemas for FastAPI request and response validation.
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class SearchResultItem(BaseModel):
    title: str = Field(..., description="Tiêu đề trang hoặc bài viết")
    url: str = Field(..., description="Đường dẫn nguồn chính thức")
    category: str = Field(..., description="Phân loại nội dung")
    snippet: str = Field(..., description="Đoạn trích nội dung liên quan nhất")
    relevance_rank: float = Field(..., description="Điểm số độ liên quan bm25")

class SearchResponse(BaseModel):
    query: str
    total_results: int
    results: List[SearchResultItem]

class CampusItem(BaseModel):
    name: str
    address: str

class ContactResponse(BaseModel):
    name: str
    hotline: str
    phone_zalo: str
    email: str
    campuses: List[CampusItem]
    registration_link: str
    fanpage: str
    source_url: str

class ProgramItem(BaseModel):
    name: str
    age_range: str
    description: str
    source_url: str

class AgeRecommendation(BaseModel):
    age: int
    recommended_program: str
    level_details: Optional[str] = None
    reason: str

class ProgramsResponse(BaseModel):
    programs: List[ProgramItem]
    recommendation: Optional[AgeRecommendation] = None
    free_assessment: str
    source_url: str

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    database_ok: bool
    total_indexed_articles: int
    timestamp: str

class LastSyncInfo(BaseModel):
    id: Optional[int] = None
    started_at: str
    completed_at: str
    status: str
    duration_seconds: float
    total_discovered: int
    valid_urls: Optional[int] = 0
    batch_target_count: Optional[int] = 0
    pages_added: int
    pages_updated: int
    pages_unchanged: int
    pages_failed: int
    pages_skipped: Optional[int] = 0
    crawl_cursor: Optional[int] = 0
    trigger_type: str
    error_summary: Optional[str] = ""

class SyncStatusResponse(BaseModel):
    is_syncing: bool
    total_pages: int
    seed_pages: int
    scraped_pages: int
    crawl_cursor: Optional[int] = 0
    last_sync: Optional[LastSyncInfo] = None
    pending_urls: int = 0
    retry_urls: int = 0
    checkpoint_valid: bool = True
    scheduler_owner: str = "external"
    schedule_armed: bool = False
    last_run_metrics: Optional[Dict[str, Any]] = None

class SyncHistoryItem(BaseModel):
    id: int
    started_at: str
    completed_at: str
    status: str
    duration_seconds: float
    total_discovered: int
    valid_urls: Optional[int] = 0
    batch_target_count: Optional[int] = 0
    pages_added: int
    pages_updated: int
    pages_unchanged: int
    pages_failed: int
    pages_skipped: Optional[int] = 0
    crawl_cursor: Optional[int] = 0
    trigger_type: str
    error_summary: Optional[str] = ""

class SyncHistoryResponse(BaseModel):
    total_records: int
    history: List[SyncHistoryItem]

class SyncResponse(BaseModel):
    success: bool
    message: str
    total_indexed: int = 0
    report: Optional[Dict[str, Any]] = None

class RobotHardwareSchema(BaseModel):
    mcu: str
    mic: str
    speaker: str
    display: str

class RobotItemSchema(BaseModel):
    id: str
    name: str
    type: str
    agent: str
    status: str
    hardware: RobotHardwareSchema
    firmware: str
    last_active: str

class AssistantItemSchema(BaseModel):
    id: str
    name: str
    model: str
    voice_role: str
    knowledge_source: str
    status: str
    tools: List[str]
    device_id: str

class DashboardDatabaseStats(BaseModel):
    public_searchable: int = 0
    total_pages: int
    seed_pages: int
    scraped_pages: int

class DashboardSyncEngineStats(BaseModel):
    is_syncing: bool
    auto_sync_enabled: bool
    schedule_times: List[str]
    next_scheduled_run: str
    crawl_cursor: int
    total_discovered: int
    valid_urls: int
    last_sync: Optional[LastSyncInfo] = None

class DashboardMCPStats(BaseModel):
    connection_status: str = "unknown"
    connection_configured: bool
    tools_registered: int
    tools_list: List[str]

class DashboardStatsResponse(BaseModel):
    uptime_seconds: int = 0
    service: str
    version: str
    backend_status: str
    database: DashboardDatabaseStats
    sync_engine: DashboardSyncEngineStats
    mcp_bridge: DashboardMCPStats
    robots: List[RobotItemSchema]
    assistants: List[AssistantItemSchema]
    categories_distribution: Dict[str, int]
    recent_syncs: List[SyncHistoryItem]

class KnowledgeItemSchema(BaseModel):
    id: int
    url: str
    title: str
    category: str
    content: str
    content_hash: str
    last_modified: Optional[str] = None
    retrieved_at: Optional[str] = None
    source_type: str
    http_status: int
    char_count: int

class KnowledgePagesResponse(BaseModel):
    items: List[KnowledgeItemSchema]
    total: int
    page: int
    limit: int
    total_pages: int
    categories: List[str]

class MCPToolDetailSchema(BaseModel):
    name: str
    title: str
    description: str
    category: str
    parameters: Dict[str, Any]
    sample_arguments: Dict[str, Any]
    status: str

class MCPToolsListResponse(BaseModel):
    total: int
    tools: List[MCPToolDetailSchema]

class LogEntrySchema(BaseModel):
    id: int
    timestamp: str
    level: str
    source: str
    message: str

class SystemLogsResponse(BaseModel):
    total: int
    logs: List[LogEntrySchema]

class AuthVerifyRequest(BaseModel):
    token: str = Field(..., max_length=512, repr=False)

class AuthVerifyResponse(BaseModel):
    valid: bool
    message: str
    role: str

