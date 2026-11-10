# WeWIN Education AI Robot Platform - API Reference Specification

## 1. WeWIN Education Portal API (Port 8001)

All endpoints are prefixed with `/api/portal` unless otherwise specified.

### Authentication & Sessions
- `POST /api/portal/login`: Authenticate with admin sync token or username/password. Returns CSRF token and session cookie.
- `POST /api/portal/auth/login`: Authenticate standard users (student, teacher, guardian).
- `GET /api/portal/session`: Return the currently authenticated user profile and permissions.
- `POST /api/portal/logout`: Terminate active session and invalidate CSRF tokens.

### Users & Role-Based Access Control (Admin/Teacher)
- `GET /api/portal/users`: List users in the organization (supports filtering by role).
- `POST /api/portal/users`: Create a new user (`student`, `teacher`, `guardian`, `admin`).
- `PUT /api/portal/users/{user_id}`: Update user metadata or active status.
- `GET /api/portal/profile`: Retrieve personal user profile.
- `PUT /api/portal/profile`: Update personal display name, proficiency level, and learning goals.

### Curriculum & Lessons
- `GET /api/portal/lessons`: Retrieve published educational lessons.
- `POST /api/portal/lessons`: Create a new lesson (teacher/admin only).
- `GET /api/portal/lessons/{lesson_id}`: Retrieve detailed lesson payload, vocabulary, and practice questions.
- `PUT /api/portal/lessons/{lesson_id}`: Update lesson content and exercises.

### Learning Sessions & Progress Tracking
- `POST /api/portal/learning/sessions`: Begin a new practice session for a lesson.
- `POST /api/portal/learning/sessions/{session_id}/complete`: Submit student answers, automatically grade, and store score.
- `GET /api/portal/learning/dashboard`: Retrieve aggregated student learning statistics (sessions completed, average score).

### Robot Configuration & AI Personas
- `GET /api/portal/overview`: Retrieve high-level summary of registered robots, active drafts, and MCP status.
- `GET /api/portal/robots`: List all authorized robots and simulated devices.
- `GET /api/portal/robots/{robot_id}/config`: Retrieve current AI configuration (assistant name, prompt, voice, speech rate).
- `PUT /api/portal/robots/{robot_id}/config`: Update robot persona candidate.
- `GET /api/portal/roles`: Retrieve available AI roles (Coach, Teacher, Tutor, Storyteller).

---

## 2. WeWIN Centre Connector API (Port 8000)

### Public & Educational Endpoints
- `GET /health`: Health check, returns database status and count of indexed knowledge records.
- `GET /search?q={query}`: SQLite FTS5 search across all published WeWIN articles and course programs.
- `GET /programs?age={age}`: Query educational programs filtered by target age group.
- `GET /contact`: Retrieve verified official contact information for WeWIN Centre.

### XiaoZhi MCP Tool Execution (Port 8000)
- `POST /api/xiaozhi/tool`: Execute verified MCP tools. Supported tools:
  - `wewin_search`: Search knowledge base.
  - `wewin_get_programs`: Get curriculum and program details.
  - `wewin_test_connection`: Health check tool.

### Administrative & Synchronization
- `POST /sync`: Trigger website re-crawling and FTS5 index update (requires `Authorization: Bearer <ADMIN_SYNC_TOKEN>`).
- `GET /sync/status`: Query status of latest crawl and index synchronization job.

---

## 3. WeWIN AI Edge Server (Port 8010)

### WebSocket Real-Time Interface
- `ws://127.0.0.1:8010/xiaozhi/v1/`: Streaming WebSocket gateway for connected robots.
  - Handles bidirectional audio chunks (Opus / PCM).
  - Handles JSON signaling messages: `hello`, `listen`, `speak`, `abort`.
  - Dispatches MCP tools for verified public WeWIN knowledge.
