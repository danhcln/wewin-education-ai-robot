import time
from src.mcp.bridge_status import read_status
API_STARTED = time.monotonic()
"""
FastAPI Routes for WeWIN AI Connector.
Provides REST endpoints and tool-calling endpoints for XiaoZhi.
"""
from datetime import datetime, timezone
import json
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header, Query, status

from src.config import settings
from src.api.security import verify_admin_token, is_valid_admin_token, redact_sensitive_data, redact_sensitive_text
from src.storage.db import get_db, DatabaseManager
from src.crawler.sitemap_crawler import WeWinCrawler
from src.crawler.curated_seeds import get_curated_seeds
from src.sync.sync_engine import get_sync_engine, SyncAlreadyRunningError, SyncLock
from src.api.schemas import (
    SearchResponse,
    ContactResponse,
    ProgramsResponse,
    HealthResponse,
    SyncResponse,
    SyncStatusResponse,
    SyncHistoryResponse,
    DashboardStatsResponse,
    DashboardDatabaseStats,
    DashboardSyncEngineStats,
    DashboardMCPStats,
    RobotItemSchema,
    RobotHardwareSchema,
    AssistantItemSchema,
    KnowledgePagesResponse,
    KnowledgeItemSchema,
    MCPToolsListResponse,
    MCPToolDetailSchema,
    SystemLogsResponse,
    LogEntrySchema,
    AuthVerifyRequest,
    AuthVerifyResponse
)

router = APIRouter()

@router.get("/health", response_model=HealthResponse)
def health_check(db: DatabaseManager = Depends(get_db)):
    """Health check endpoint reporting database status and article counts."""
    total_articles = 0
    db_ok = True
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM public_pages;")
            total_articles = cur.fetchone()[0]
    except Exception:
        db_ok = False

    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        service="WeWIN AI Website Connector",
        version="1.0.0",
        database_ok=db_ok,
        total_indexed_articles=total_articles,
        timestamp=datetime.now(timezone.utc).isoformat()
    )

@router.get("/search", response_model=SearchResponse)
def search_wewin(
    q: str = Query(..., description="Từ khóa hoặc câu hỏi cần tìm kiếm"),
    limit: int = Query(4, ge=1, le=10, description="Số lượng kết quả trả về"),
    db: DatabaseManager = Depends(get_db)
):
    """
    Full-text search endpoint using SQLite FTS5.
    Returns ranked excerpts with canonical source URLs.
    """
    results = db.search(q, limit=limit)
    return SearchResponse(
        query=q,
        total_results=len(results),
        results=results
    )

@router.get("/programs", response_model=ProgramsResponse)
def get_programs(
    age: Optional[int] = Query(None, ge=1, le=100, description="Độ tuổi của học viên"),
    db: DatabaseManager = Depends(get_db)
):
    """
    Returns English training programs at WeWIN.
    If age is provided (e.g., 9), returns precise recommended level.
    """
    return db.get_programs(age=age)

@router.get("/contact", response_model=ContactResponse)
def get_contact(db: DatabaseManager = Depends(get_db)):
    """
    Returns official contact details: hotlines, campuses, email, and fanpage.
    """
    return db.get_contact()

@router.get("/page")
def get_page_content(
    url: str = Query(..., description="Đường dẫn URL của trang cần xem nội dung chi tiết"),
    db: DatabaseManager = Depends(get_db)
):
    """
    Returns cached full text content of a specific page.
    """
    page = db.get_page(url)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found in local cache.")
    return page

@router.get("/sync/status", response_model=SyncStatusResponse, dependencies=[Depends(verify_admin_token)])
def get_sync_status(db: DatabaseManager = Depends(get_db)):
    """
    Returns latest synchronization status, timestamp, active lock, and page counts.
    Admin authentication required.
    """
    status_info = db.get_sync_status()
    lock = SyncLock()
    cursor = int(db.get_state("crawl_cursor", "0") or 0)
    checkpoint_valid = True
    try:
        checkpoint = json.loads(db.get_state("sync_checkpoint", "") or "null") or {}
        retry_queue = json.loads(db.get_state("sync_retry_urls", "[]") or "[]")
        if not isinstance(checkpoint, dict) or not isinstance(retry_queue, list):
            raise ValueError("Invalid checkpoint shape")
        if checkpoint and (checkpoint.get("version") != 1 or not isinstance(checkpoint.get("urls"), list)
                           or not isinstance(checkpoint.get("offset"), int)
                           or not 0 <= checkpoint["offset"] <= len(checkpoint["urls"])):
            raise ValueError("Invalid checkpoint position")
        pending = max(0, len(checkpoint.get("urls", [])) - checkpoint.get("offset", 0))
        retries = len(retry_queue)
        metrics = json.loads(db.get_state("last_sync_report", "") or "null")
        if metrics is not None and not isinstance(metrics, dict):
            raise ValueError("Invalid metrics shape")
    except (ValueError, TypeError, AttributeError):
        checkpoint_valid, pending, retries, metrics = False, 0, 0, None
    return SyncStatusResponse(
        is_syncing=lock.is_locked(),
        total_pages=status_info["total_pages"],
        seed_pages=status_info["seed_pages"],
        scraped_pages=status_info["scraped_pages"],
        crawl_cursor=cursor,
        last_sync=redact_sensitive_data(status_info.get("last_sync")),
        pending_urls=pending, retry_urls=retries, checkpoint_valid=checkpoint_valid,
        scheduler_owner=settings.SYNC_SCHEDULER_OWNER, schedule_armed=settings.SYNC_SCHEDULE_ARMED,
        last_run_metrics=redact_sensitive_data(metrics)
    )

@router.get("/sync/history", response_model=SyncHistoryResponse, dependencies=[Depends(verify_admin_token)])
def get_sync_history(
    limit: int = Query(15, ge=1, le=100, description="Số lượng bản ghi lịch sử"),
    db: DatabaseManager = Depends(get_db)
):
    """
    Returns recent synchronization execution history and audit logs.
    Admin authentication required.
    """
    history_records = redact_sensitive_data(db.get_sync_history(limit=limit))
    return SyncHistoryResponse(
        total_records=len(history_records),
        history=history_records
    )

@router.post("/sync", response_model=SyncResponse, dependencies=[Depends(verify_admin_token)])
def trigger_sync(
    max_pages: Optional[int] = Query(None, ge=1, le=500, description="Giới hạn số trang tối đa cần đồng bộ theo batch"),
    all_pages: bool = Query(False, description="Nếu true, đồng bộ toàn bộ URL hợp lệ trong một đợt"),
    dry_run: bool = Query(False, description="Nếu true, chỉ kiểm tra thay đổi không ghi vào database"),
    db: DatabaseManager = Depends(get_db)
):
    """
    Admin-only endpoint to incrementally synchronize WeWIN website public content.
    Uses SHA-256 content hashing to avoid redundant writes and updates SQLite FTS5 index atomically.
    """
    engine = get_sync_engine()
    try:
        report = engine.run_sync(trigger_type="api", max_pages=max_pages, dry_run=dry_run, crawl_all=all_pages)
        return SyncResponse(
            success=report.status in ("success", "partial", "dry_run"),
            message=f"Sync finished with status '{report.status}'. Added: {report.pages_added}, Updated: {report.pages_updated}, Unchanged: {report.pages_unchanged}, Failed: {report.pages_failed}, Skipped: {report.pages_skipped}.",
            total_indexed=report.pages_added + report.pages_updated + report.pages_unchanged,
            report=redact_sensitive_data(report.to_dict())
        )
    except SyncAlreadyRunningError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Synchronization failed: {redact_sensitive_text(str(e))}"
        )

@router.post("/sync/unlock", dependencies=[Depends(verify_admin_token)])
def force_unlock_sync():
    """
    Recovers stale metadata while retaining the persistent OS guard.
    """
    lock = SyncLock()
    try:
        lock.recover_stale()
    except SyncAlreadyRunningError:
        raise HTTPException(status_code=409, detail="Sync job is active; unlock refused.") from None
    except OSError:
        raise HTTPException(status_code=503, detail="Unable to inspect/recover sync lock safely.") from None
    return {"success": True, "message": "Đã kiểm tra và phục hồi metadata khóa bỏ lại; không can thiệp job đang chạy."}

@router.post("/api/xiaozhi/tool")
def xiaozhi_http_tool_webhook(payload: Dict[str, Any], db: DatabaseManager = Depends(get_db)):
    """
    Universal HTTP Webhook Adapter for XiaoZhi / Dify / OpenAI Function Calling.
    Accepts: { "tool": "wewin_search", "arguments": { "query": "..." } }
    """
    tool_name = payload.get("tool") or payload.get("name") or payload.get("function")
    args = payload.get("arguments") or payload.get("parameters") or {}

    from src.media.tools import MEDIA_NAMES
    if isinstance(tool_name, str) and tool_name in MEDIA_NAMES:
        from src.media.routes import handle_media_tool
        return {'tool':tool_name,'data':handle_media_tool(tool_name,args)}

    from src.reading.articles import READING_TOOL_NAMES, execute_reading_tool
    if isinstance(tool_name, str) and tool_name in READING_TOOL_NAMES:
        return {"tool": tool_name, "data": execute_reading_tool(tool_name, args, db)}

    if tool_name == "wewin_test_connection":
        return {"tool": tool_name, "data": "WeWIN MCP OK"}

    elif tool_name == "wewin_search":
        q = args.get("query") or args.get("q", "")
        limit = int(args.get("limit", 3))
        results = db.search(q, limit=limit)
        return {"tool": tool_name, "results": results}

    elif tool_name == "wewin_get_programs":
        age = args.get("age")
        if age is not None:
            age = int(age)
        return {"tool": tool_name, "data": db.get_programs(age=age)}

    elif tool_name == "wewin_get_contact":
        return {"tool": tool_name, "data": db.get_contact()}

    elif tool_name == "wewin_get_page":
        url = args.get("url", "")
        return {"tool": tool_name, "data": db.get_page(url)}

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool '{tool_name}'. Available: wewin_search, wewin_get_programs, wewin_get_contact, wewin_get_page"
        )


@router.post("/api/auth/verify", response_model=AuthVerifyResponse)
def verify_token(req: AuthVerifyRequest):
    """Verifies admin token submitted from the UI."""
    is_valid = is_valid_admin_token(req.token.strip())
    return AuthVerifyResponse(
        valid=is_valid,
        message="Token hợp lệ" if is_valid else "Token không chính xác",
        role="admin" if is_valid else "guest"
    )


@router.get("/api/dashboard/stats", response_model=DashboardStatsResponse, dependencies=[Depends(verify_admin_token)])
def get_dashboard_stats(db: DatabaseManager = Depends(get_db)):
    """
    Returns aggregated stats for WeWIN AI Control Center dashboard:
    database counts, sync status, MCP status, hardware devices, and assistants.
    """
    # 1. Database and Category stats
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pages;")
        total_pages = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM pages WHERE source_type = 'seed';")
        seed_pages = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM pages WHERE source_type = 'scraped';")
        scraped_pages = cur.fetchone()[0]

        cur.execute("SELECT category, COUNT(*) FROM pages GROUP BY category;")
        categories_distribution = {row[0] or "general": row[1] for row in cur.fetchall()}

        public_count = cur.execute("SELECT COUNT(*) FROM public_pages").fetchone()[0]

    # 2. Sync state and schedule
    lock = SyncLock()
    is_syncing = lock.is_locked()
    last_sync = redact_sensitive_data(db.get_last_sync())
    cursor = int(db.get_state("crawl_cursor", "0") or 0)

    # Next schedule: 08:00 or 20:00 local time
    now = datetime.now()
    if now.hour < 8:
        next_run = "08:00 Hôm nay"
    elif now.hour < 20:
        next_run = "20:00 Hôm nay"
    else:
        next_run = "08:00 Ngày mai"
    if not settings.SYNC_SCHEDULE_ARMED:
        next_run = "Chưa kích hoạt lịch tự động"

    # 4. Registered robots
    robots = [
        RobotItemSchema(
            id="esp32-robot-01",
            name="ESP32-S3 N16R8",
            type="Smart Audio Assistant",
            agent="AI Vietnamese",
            status="unknown",
            hardware=RobotHardwareSchema(
                mcu="ESP32-S3-WROOM-1 N16R8 (16MB Flash, 8MB PSRAM)",
                mic="INMP441 (I2S MEMS Omnidirectional)",
                speaker="MAX98357A (I2S 3.2W Class D)",
                display="OLED SSD1306 (128x64 I2C)"
            ),
            firmware="Unknown",
            last_active="Unknown — chưa có heartbeat thiết bị"
        )
    ]

    # 5. Assistant
    assistants = [
        AssistantItemSchema(
            id="asst-vi-01",
            name="AI Vietnamese",
            model="Unknown",
            voice_role="Unknown",
            knowledge_source="WeWIN RAG & Curated Seeds",
            status="unknown",
            tools=[
                "wewin_search",
                "wewin_get_programs",
                "wewin_get_contact",
                "wewin_get_page",
                "wewin_test_connection"
            ],
            device_id="esp32-robot-01"
        )
    ]

    recent_syncs = redact_sensitive_data(db.get_sync_history(limit=5))
    from src.mcp.tools import TOOL_DEFINITIONS

    return DashboardStatsResponse(
        service="WeWIN AI Control Center",
        version="1.0.0",
        backend_status="healthy",
        uptime_seconds=int(time.monotonic() - API_STARTED),
        database=DashboardDatabaseStats(
            total_pages=total_pages,
            seed_pages=seed_pages,
            scraped_pages=scraped_pages,
            public_searchable=public_count
        ),
        sync_engine=DashboardSyncEngineStats(
            is_syncing=is_syncing,
            auto_sync_enabled=settings.SYNC_SCHEDULE_ARMED and (settings.SYNC_SCHEDULER_OWNER == "windows" or (settings.SYNC_SCHEDULER_OWNER == "internal" and settings.AUTO_SYNC_ENABLED)),
            schedule_times=["08:00", "20:00"],
            next_scheduled_run=next_run,
            crawl_cursor=cursor,
            total_discovered=(last_sync or {}).get("total_discovered", 0),
            valid_urls=(last_sync or {}).get("valid_urls", 0),
            last_sync=last_sync
        ),
        mcp_bridge=DashboardMCPStats(
            connection_configured=bool(settings.XIAOZHI_MCP_ENDPOINT),
            connection_status=read_status(),
            tools_registered=len(TOOL_DEFINITIONS),
            tools_list=[t['name'] for t in TOOL_DEFINITIONS]
        ),
        robots=robots,
        assistants=assistants,
        categories_distribution=categories_distribution,
        recent_syncs=recent_syncs
    )


@router.get("/api/knowledge/pages", response_model=KnowledgePagesResponse, dependencies=[Depends(verify_admin_token)])
def list_knowledge_pages(
    page: int = Query(1, ge=1, description="Trang hiện tại"),
    limit: int = Query(12, ge=1, le=100, description="Số lượng mục mỗi trang"),
    search: Optional[str] = Query(None, description="Từ khóa tìm kiếm"),
    category: Optional[str] = Query(None, description="Lọc theo danh mục"),
    source_type: Optional[str] = Query(None, description="seed hoặc scraped"),
    db: DatabaseManager = Depends(get_db)
):
    """
    Lists indexed knowledge articles with pagination, search, and category filtering.
    """
    conditions = []
    params = []

    if search:
        conditions.append("(title LIKE ? OR content LIKE ?)")
        search_param = f"%{search.strip()}%"
        params.extend([search_param, search_param])

    if category and category.lower() != "all":
        conditions.append("category = ?")
        params.append(category.strip())

    if source_type and source_type.lower() != "all":
        conditions.append("source_type = ?")
        params.append(source_type.strip())

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    offset = (page - 1) * limit

    with db.get_connection() as conn:
        cur = conn.cursor()

        # Count total
        cur.execute(f"SELECT COUNT(*) FROM pages {where_clause};", params)
        total_count = cur.fetchone()[0]

        # Fetch distinct categories
        cur.execute("SELECT DISTINCT category FROM pages WHERE category IS NOT NULL ORDER BY category;")
        categories = [r[0] for r in cur.fetchall()]

        # Query paginated rows
        query = f"""
            SELECT id, url, title, category, content, content_hash,
                   last_modified, retrieved_at, source_type, http_status
            FROM pages
            {where_clause}
            ORDER BY id ASC
            LIMIT ? OFFSET ?;
        """
        cur.execute(query, params + [limit, offset])
        rows = cur.fetchall()

    items = []
    for r in rows:
        content_text = r["content"] or ""
        items.append(KnowledgeItemSchema(
            id=r["id"],
            url=r["url"],
            title=r["title"] or "Không có tiêu đề",
            category=r["category"] or "general",
            content=content_text,
            content_hash=r["content_hash"] or "",
            last_modified=r["last_modified"],
            retrieved_at=r["retrieved_at"],
            source_type=r["source_type"] or "scraped",
            http_status=r["http_status"] or 200,
            char_count=len(content_text)
        ))

    total_pages = max(1, (total_count + limit - 1) // limit)

    return KnowledgePagesResponse(
        items=items,
        total=total_count,
        page=page,
        limit=limit,
        total_pages=total_pages,
        categories=categories
    )


@router.get("/api/mcp/tools", response_model=MCPToolsListResponse)
def list_mcp_tools():
    """
    Returns the metadata, description, and JSON schema for all WeWIN MCP tools.
    """
    tools = [
        MCPToolDetailSchema(
            name="wewin_test_connection",
            title="Kiểm Tra Kết Nối MCP",
            description="Kiểm tra trạng thái kết nối giữa robot XiaoZhi AI và WeWIN Backend. Luôn trả về 'WeWIN MCP OK' khi thành công.",
            category="System",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            },
            sample_arguments={},
            status="active"
        ),
        MCPToolDetailSchema(
            name="wewin_search",
            title="Tìm Kiếm Nội Dung WeWIN",
            description="Tìm kiếm bài viết, tài liệu, chính sách, học bổng từ website WeWIN Education qua SQLite FTS5 theo độ liên quan BM25.",
            category="Knowledge",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Từ khóa hoặc câu hỏi cần tra cứu (VD: 'khóa học IELTS', 'học phí')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Số lượng kết quả trả về (mặc định: 3)"
                    }
                },
                "required": ["query"]
            },
            sample_arguments={"query": "khóa học IELTS", "limit": 3},
            status="active"
        ),
        MCPToolDetailSchema(
            name="wewin_get_programs",
            title="Chương Trình Đào Tạo",
            description="Lấy danh mục các khóa học tiếng Anh chính (Mầm non, Cambridge Tiểu học, IELTS). Nếu cung cấp độ tuổi học viên, trả về chính xác cấp độ phù hợp.",
            category="Academics",
            parameters={
                "type": "object",
                "properties": {
                    "age": {
                        "type": "integer",
                        "description": "Độ tuổi của học viên (VD: 9)"
                    }
                },
                "required": []
            },
            sample_arguments={"age": 9},
            status="active"
        ),
        MCPToolDetailSchema(
            name="wewin_get_contact",
            title="Thông Tin Liên Hệ & Cơ Sở",
            description="Lấy thông tin liên hệ chính thức của WeWIN Education: 2 cơ sở Bình Thạnh, 2 hotline, số Zalo, email, link đăng ký test miễn phí và fanpage.",
            category="Contact",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            },
            sample_arguments={},
            status="active"
        ),
        MCPToolDetailSchema(
            name="wewin_get_page",
            title="Xem Chi Tiết Bài Viết",
            description="Truy xuất toàn văn nội dung một trang web cụ thể từ bộ nhớ đệm WeWIN dựa theo đường dẫn URL chính thức.",
            category="Knowledge",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Đường dẫn URL của trang cần xem"
                    }
                },
                "required": ["url"]
            },
            sample_arguments={"url": "https://wewin.edu.vn/gioi-thieu/"},
            status="active"
        )
    ]
    from src.reading.tool_definitions import READING_TOOL_DEFINITIONS
    from src.media.tools import MEDIA_DEFINITIONS
    from src.media.audio_endpoint import AUDIO_TOOL_DEFINITION
    for definition in [*READING_TOOL_DEFINITIONS,*MEDIA_DEFINITIONS,AUDIO_TOOL_DEFINITION]:
        tools.append(MCPToolDetailSchema(
            name=definition['name'], title=definition['name'],
            description=definition['description'], category='Reading',
            parameters=definition['inputSchema'], sample_arguments={}, status='active'))
    return MCPToolsListResponse(total=len(tools), tools=tools)


@router.get("/api/system/logs", response_model=SystemLogsResponse, dependencies=[Depends(verify_admin_token)])
def get_system_logs(
    limit: int = Query(50, ge=1, le=200, description="Số dòng log gần nhất"),
    db: DatabaseManager = Depends(get_db)
):
    """
    Returns recent system and synchronization log entries.
    """
    entries = []
    log_id = 1

    # Read from sync_history
    history = db.get_sync_history(limit=20)
    for h in history:
        status_label = h.get("status", "unknown").upper()
        level = "ERROR" if status_label == "FAILED" else ("WARNING" if status_label == "PARTIAL" else "INFO")
        msg = f"[SYNC-{status_label}] Trigger: {h.get('trigger_type')} | Added: {h.get('pages_added')}, Updated: {h.get('pages_updated')}, Unchanged: {h.get('pages_unchanged')}, Skipped: {h.get('pages_skipped')}, Failed: {h.get('pages_failed')} ({h.get('duration_seconds')}s)"
        if h.get("error_summary"):
            msg += f" - Lỗi: {h['error_summary']}"
        entries.append(LogEntrySchema(
            id=log_id,
            timestamp=h.get("started_at", ""),
            level=level,
            source="AutoSyncEngine",
            message=msg
        ))
        log_id += 1

    # Read tail from logs/sync_scheduled.log if exists
    from pathlib import Path
    log_file = Path("logs/sync_scheduled.log")
    if log_file.exists():
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-limit:]:
                if not line.strip():
                    continue
                level = "INFO"
                if "ERROR" in line or "failed" in line.lower() or "exit code 1" in line.lower():
                    level = "ERROR"
                elif "WARNING" in line or "skipped" in line.lower():
                    level = "WARNING"
                entries.append(LogEntrySchema(
                    id=log_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    level=level,
                    source="TaskSchedulerLog",
                    message=line.strip()
                ))
                log_id += 1
        except Exception:
            pass

    for entry in entries:
        entry.message = redact_sensitive_text(entry.message)
    return SystemLogsResponse(total=len(entries), logs=entries[-limit:])

