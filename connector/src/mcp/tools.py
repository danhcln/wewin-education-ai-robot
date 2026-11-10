"""
Tool Declarations and Execution Handlers for XiaoZhi AI and Model Context Protocol (MCP).
"""
import json
from typing import Dict, Any, List, Optional
from src.storage.db import get_db
from src.reading.articles import READING_TOOL_NAMES, execute_reading_tool
from src.reading.tool_definitions import READING_TOOL_DEFINITIONS
from src.media.tools import MEDIA_DEFINITIONS, MEDIA_NAMES, relay_cloud_media_tool

# Standard MCP JSON Schemas for Tool Registration
TOOL_DEFINITIONS = [
    {
        "name": "wewin_test_connection",
        "description": (
            "Kiểm tra kết nối MCP trực tiếp với hệ thống WeWIN Education. "
            "BẮT BUỘC gọi công cụ này khi người dùng nói 'test WeWIN', 'kiểm tra kết nối WeWIN', "
            "'test kết nối', hoặc hỏi 'kết nối WeWIN có hoạt động không'. Trả về chuỗi WeWIN MCP OK."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "wewin_search",
        "description": (
            "Tìm kiếm thông tin chính thức trên website WeWIN Education (https://wewin.edu.vn/). "
            "BẮT BUỘC sử dụng khi người dùng hỏi các câu hỏi chung về WeWIN, WeWIN là gì, chứng chỉ Cambridge, "
            "khóa học IELTS, phương pháp đào tạo, đội ngũ giáo viên, ưu đãi, học phí, lịch học, sách hoặc tài liệu học."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Nội dung hoặc từ khóa cần tìm kiếm (tiếng Việt có dấu hoặc không dấu)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Số lượng kết quả cần lấy (mặc định là 3)",
                    "default": 3
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "wewin_get_programs",
        "description": (
            "Lấy danh sách các chương trình đào tạo tiếng Anh tại WeWIN Education theo từng nhóm tuổi "
            "(Mầm non 3-6 tuổi, Cambridge 6-12 tuổi, IELTS 12-18 tuổi và người lớn). "
            "Nếu người dùng hỏi cho độ tuổi cụ thể (ví dụ: 'con tôi 9 tuổi thì học gì'), truyền tham số age "
            "để hệ thống trả về lộ trình và khóa học được khuyến nghị chính xác nhất."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "age": {
                    "type": "integer",
                    "description": "Độ tuổi của học viên (ví dụ: 4, 9, 15)"
                }
            },
            "required": []
        }
    },
    {
        "name": "wewin_get_contact",
        "description": (
            "Lấy thông tin liên hệ chính thức của WeWIN Education bao gồm số điện thoại hotline, Zalo, email, "
            "địa chỉ 2 cơ sở tại Quận Bình Thạnh TP.HCM và link đăng ký kiểm tra năng lực 4 kỹ năng miễn phí. "
            "BẮT BUỘC gọi khi người dùng hỏi thông tin liên hệ, hotline, số điện thoại, địa chỉ, cơ sở của WeWIN."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "wewin_get_page",
        "description": (
            "Xem nội dung chi tiết của một trang hoặc bài viết trên website WeWIN Education "
            "thông qua đường dẫn URL cụ thể."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Đường dẫn URL đầy đủ (ví dụ: https://wewin.edu.vn/about/)"
                }
            },
            "required": ["url"]
        }
    }
]
TOOL_DEFINITIONS.extend(READING_TOOL_DEFINITIONS)
TOOL_DEFINITIONS.extend(MEDIA_DEFINITIONS)
from src.media.audio_endpoint import AUDIO_TOOL_DEFINITION, prepare_audio_descriptor
TOOL_DEFINITIONS.append(AUDIO_TOOL_DEFINITION)

def wewin_test_connection_tool() -> str:
    """Minimal test tool returning string as requested."""
    return "WeWIN MCP OK"

def wewin_search_tool(query: str, limit: int = 3) -> str:
    """Executes search and formats speech-friendly text for XiaoZhi voice assistant."""
    db = get_db()
    results = db.search(query, limit=limit)
    if not results:
        return (
            f"Không tìm thấy thông tin phù hợp với từ khóa '{query}' trên website WeWIN Education. "
            "Bạn có thể liên hệ trực tiếp hotline WeWIN: 034 596 9388 hoặc 037 866 9388 để được hỗ trợ trực tiếp. "
            "(Nguồn: https://wewin.edu.vn/)"
        )

    response_lines = [f"Dưới đây là thông tin tìm kiếm được từ website WeWIN Education cho '{query}':"]
    for i, r in enumerate(results, start=1):
        clean_snippet = r['snippet'].replace("\n", " ").strip()
        response_lines.append(f"{i}. {r['title']}: {clean_snippet} (Nguồn: {r['url']})")

    return "\n\n".join(response_lines)

def wewin_get_programs_tool(age: Optional[int] = None) -> str:
    """Returns structured programs with age-tailored recommendation."""
    db = get_db()
    data = db.get_programs(age=age)

    lines = []
    if data.get("recommendation"):
        rec = data["recommendation"]
        lines.append(f"Gợi ý cho học viên {rec['age']} tuổi: Khóa học phù hợp nhất là '{rec['recommended_program']}'.")
        lines.append(f"Lý do: {rec['reason']}")
        if rec.get("level_details"):
            lines.append(f"Chi tiết phân lớp: {rec['level_details']}")
        lines.append(f"Quyền lợi: {data['free_assessment']}")
        lines.append(f"Chi tiết chương trình tại: {data['source_url']}")
        return "\n".join(lines)

    lines.append("Các chương trình đào tạo tiếng Anh chính tại WeWIN Education:")
    for p in data["programs"]:
        lines.append(f"- {p['name']} ({p['age_range']}): {p['description']}")
    lines.append(f"\nƯu đãi đặc biệt: {data['free_assessment']}")
    lines.append(f"Nguồn tham khảo: {data['source_url']}")
    return "\n".join(lines)

def wewin_get_contact_tool() -> str:
    """Returns official contact information."""
    db = get_db()
    c = db.get_contact()
    campuses_str = "\n".join([f"  + {camp['name']}: {camp['address']}" for camp in c["campuses"]])
    return (
        f"Thông tin liên hệ của WeWIN Education (Trung tâm Ngoại ngữ Công Thành):\n"
        f"- Hotline tư vấn: {c['hotline']}\n"
        f"- Số điện thoại / Zalo: {c['phone_zalo']}\n"
        f"- Email: {c['email']}\n"
        f"- Hệ thống cơ sở tại TP.HCM:\n{campuses_str}\n"
        f"- Đăng ký kiểm tra 4 kỹ năng miễn phí: {c['registration_link']}\n"
        f"- Fanpage: {c['fanpage']}\n"
        f"(Nguồn: {c['source_url']})"
    )

def wewin_get_page_tool(url: str) -> str:
    """Returns content of a specific cached page."""
    db = get_db()
    page = db.get_page(url)
    if not page:
        return "Không tìm thấy nội dung công khai được duyệt cho URL này trong kho WeWIN."
    content_preview = page["content"][:800]
    return f"Nội dung trang '{page['title']}' ({page['url']}):\n{content_preview}"

def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Universal dispatcher for tool execution."""
    if tool_name == "wewin_prepare_audio":
        return json.dumps(prepare_audio_descriptor(arguments.get("asset_id", "")), ensure_ascii=False)
    if isinstance(tool_name, str) and tool_name in MEDIA_NAMES:
        return json.dumps(relay_cloud_media_tool(tool_name, arguments), ensure_ascii=False)
    if isinstance(tool_name, str) and tool_name in READING_TOOL_NAMES:
        return json.dumps(execute_reading_tool(tool_name, arguments, get_db()), ensure_ascii=False)

    if tool_name == "wewin_test_connection":
        return wewin_test_connection_tool()

    elif tool_name == "wewin_search":
        q = arguments.get("query") or arguments.get("q", "")
        limit = int(arguments.get("limit", 3))
        return wewin_search_tool(q, limit)

    elif tool_name == "wewin_get_programs":
        raw_age = arguments.get("age")
        age = int(raw_age) if raw_age is not None else None
        return wewin_get_programs_tool(age)

    elif tool_name == "wewin_get_contact":
        return wewin_get_contact_tool()

    elif tool_name == "wewin_get_page":
        url = arguments.get("url", "")
        return wewin_get_page_tool(url)

    else:
        return f"Lỗi: Không tìm thấy công cụ '{tool_name}'."
