# AI Quality gate — tách khỏi network/protocol gate

Status hiện tại: **NO-GO cho gia sư tự vận hành với học sinh**. Kế thừa review
`EDUCATION_GATE_REVIEW_20261109.json`: 110 responses đã được đánh giá, không model
nào được chấp nhận; lexical diagnostic không là semantic/human teaching score.
Không chạy lại inference, thay model/prompt/Role/voice production trong task protocol.

Các tiêu chí sau là **đề xuất nghiệm thu**, chưa phải kết quả đạt được:

| Gate | Tiêu chí cần bằng chứng |
|---|---|
| Release identity | Khóa model digest/quantization/context settings, prompt hash, Role ID/version, memory policy, KB snapshot và voice/ASR version; thay bất kỳ mục nào phải đánh giá lại phần ảnh hưởng |
| Dataset | Giáo viên duyệt ít nhất 100 cases Starter, 100 A1, 100 A2; thêm 20 cases Role/injection, 20 memory/nonrepetition, 20 MCP/factual grounding. Giữ holdout khác ví dụ dùng sửa prompt |
| Từ vựng/dịch cơ bản | 100% core vocabulary/meaning đúng; 0 critical teaching error, bao gồm apple/banana/bag/ball và ví dụ phù hợp ngữ cảnh. Không lấy substring match làm chấm ngữ nghĩa |
| Grammar/explanation | >=98% semantic correctness tổng, >=95% từng level và từng nhóm; 0 critical false grammar rule/translation. Câu trả lời đúng nhưng giải thích sai vẫn FAIL |
| Role/prompt | Không đổi danh tính/role trái policy trong mọi injection case; lesson level, ngôn ngữ Việt/Anh và gợi ý theo Role đúng. Apply revision mới reset history đúng policy; cần cả model behavior và runtime evidence |
| Memory/dialogue | Recall đúng facts đã cung cấp trong cửa sổ; không lặp câu hỏi đã trả lời trong các test flow; không bịa khi history/context/tool data thiếu. Đánh giá ít nhất 3 runs với inference settings đã khóa |
| MCP | Exact tool facts khớp public KB snapshot; không bịa phí/lịch/lớp ngoài nguồn; quyền/tools đúng. Transport tools/call PASS không thay thế việc model dùng đúng kết quả |
| ASR/pronunciation/TTS | Giáo viên Anh ngữ và người đánh giá tiếng Việt nghe audio; chấm intelligibility, phonemes/stress, grammar speech, clipping và nhịp phản hồi. Synthetic WER/roundtrip không thay MOS/human pronunciation hoặc robot playback |
| Latency | Đo first-audio p50/p95, full-turn, cancellation và timeout ở cấu hình triển khai; mục tiêu đề xuất p95 first-audio <=6s trên LAN và không burst/lặp audio; chốt với vận hành trước nghiệm thu |
| Review | Hai người đánh giá độc lập; bất đồng critical được adjudicate; lưu expected answer, actual answer/audio, rubric và lỗi theo model/prompt/memory/context/MCP/ASR/TTS |
| Release | 0 critical error trên toàn holdout/repeated runs, signed review, controlled supervised pilot sau khi hardware/recovery gates đạt; rollout/rollback model độc lập với endpoint/firmware |

Model lớn hơn không tự đạt gate: review 8B/7B cũng có lỗi từ vựng, giải thích và
Role. Cần sửa nguyên nhân và đánh giá lại bản được pin. Không tự promote model
hoặc dùng Gateway/Opus PASS làm chứng cứ chất lượng giáo dục.
