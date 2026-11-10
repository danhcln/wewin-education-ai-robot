# WeWIN Education API inventory

Session/RBAC/scope apply. Mutations require matching Origin and CSRF. External XiaoZhi/TanDev management remains unsupported. Opt-in WeWIN AI staging uses candidate confirmation and runtime readback; server proof never verifies a physical robot.

| Method | Path | Operation |
| --- | --- | --- |
| POST | `/api/portal/login` | Token Login |
| POST | `/api/portal/auth/login` | Password Login |
| GET | `/api/portal/session` | Whoami |
| POST | `/api/portal/logout` | Logout |
| GET | `/api/portal/users` | Users |
| POST | `/api/portal/users` | Create User |
| POST | `/api/portal/device-bindings` | Assign Robot |
| POST | `/api/portal/guardian-links` | Guardian Link |
| GET | `/api/portal/profile` | Profile |
| PUT | `/api/portal/profile` | Update Profile |
| GET | `/api/portal/overview` | Overview |
| GET | `/api/portal/robots/{robot_id}/config` | Get Config |
| PUT | `/api/portal/robots/{robot_id}/config` | Save Config |
| GET | `/api/portal/robots/{robot_id}/history` | History |
| GET | `/api/portal/mcp` | Mcp |
| GET | `/api/portal/lessons` | Lessons |
| POST | `/api/portal/lessons` | Create Lesson |
| GET | `/api/portal/lessons/{lid}` | Lesson Detail |
| PUT | `/api/portal/lessons/{lid}` | Update Lesson |
| GET | `/api/portal/paths` | Paths |
| POST | `/api/portal/paths` | Create Path |
| PUT | `/api/portal/paths/{pid}` | Update Path |
| POST | `/api/portal/paths/{pid}/enroll` | Enroll |
| POST | `/api/portal/learning/sessions` | Start |
| POST | `/api/portal/learning/sessions/{sid}/complete` | Finish |
| GET | `/api/portal/learning/dashboard` | Dashboard |
| GET | `/api/portal/tasks` | Tasks |
| POST | `/api/portal/tasks` | Create Task |
| PUT | `/api/portal/tasks/{tid}` | Update Task |
| DELETE | `/api/portal/tasks/{tid}` | Delete Task |
| POST | `/api/portal/tasks/{tid}/complete` | Complete Task |
| GET | `/api/portal/tasks/{tid}/history` | Task History |
| GET | `/api/portal/memories` | Memories |
| POST | `/api/portal/memories` | Create Memory |
| PUT | `/api/portal/memories/{mid}` | Update Memory |
| DELETE | `/api/portal/memories/{mid}` | Delete Memory |
| GET | `/api/portal/knowledge` | Knowledge |
| POST | `/api/portal/knowledge` | Create Document |
| POST | `/api/portal/knowledge/upload` | Upload Document |
| POST | `/api/portal/knowledge/{kid}/reindex` | Reindex |
| DELETE | `/api/portal/knowledge/{kid}` | Delete Document |
| GET | `/api/portal/media` | Media |
| POST | `/api/portal/media` | Create Media |
| GET | `/api/portal/media/connector/{asset_id}/audio` | Connector Audio |
| POST | `/api/portal/media/{mid}/bind` | Bind Media |
| GET | `/api/portal/providers` | Provider Status |
| POST | `/api/portal/ocr` | Image Ocr |
| POST | `/api/portal/homework` | Solve Homework |
| GET | `/api/portal/homework` | Homework History |
| GET | `/api/portal/logs` | Logs |
| POST | `/api/portal/teacher-students` | Assign Teacher |
| GET | `/api/portal/students` | Students |
| POST | `/api/portal/role-bindings` | Role Binding |
| POST | `/api/portal/knowledge/{kid}/bindings` | Knowledge Binding |
| GET | `/api/portal/knowledge/{kid}/bindings` | Knowledge Bindings |
| GET | `/api/portal/curricula` | Curricula |
| POST | `/api/portal/curricula` | Create Curriculum |
| PUT | `/api/portal/curricula/{cid}` | Update Curriculum |
| POST | `/api/portal/curricula/{cid}/enroll` | Enroll Curriculum |
| GET | `/api/portal/roles` | List Roles |
| POST | `/api/portal/roles` | Create Role |
| GET | `/api/portal/roles/{rid}` | Get Role |
| PUT | `/api/portal/roles/{rid}` | Update Role |
| GET | `/api/portal/roles/{rid}/history` | Role History |
| GET | `/api/portal/cloud-connection-guide` | Connection Guide |
| GET | `/api/portal/robots` | Robots |
| POST | `/api/portal/robots/{rid}/config/candidates` | Configuration Candidate |
| POST | `/api/portal/robots/{rid}/roles/{role_id}/candidate` | Role Candidate |
| POST | `/api/portal/robots/{rid}/config/candidates/save` | Save Candidate |
| POST | `/api/portal/robots/{rid}/roles/{role_id}/apply` | Assign Role |
| POST | `/api/portal/robots/{rid}/config/apply` | Apply Cloud |
| GET | `/api/portal/robots/{rid}/config/sync-status` | Sync Status |
| POST | `/api/portal/robots/{rid}/config/read-cloud` | Read Cloud |
| GET | `/api/portal/robots/{rid}/history/{version}` | Version Detail |
| POST | `/api/portal/robots/{rid}/config/restore` | Restore |
| GET | `/api/portal/robots/{rid}/cloud-connection` | Connection Profile |
| PUT | `/api/portal/robots/{rid}/cloud-connection` | Save Connection Profile |
| GET | `/api/portal/robots/{rid}/self-hosted` | Get Link |
| POST | `/api/portal/robots/{rid}/self-hosted` | Enable Link |
| POST | `/api/portal/robots/{rid}/self-hosted/disconnect` | Disable Link |
| GET | `/api/health` | Health |
