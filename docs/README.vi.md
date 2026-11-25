# Engineering Team Kit (Tiếng Việt)

Một "team kỹ sư thu nhỏ" cho Claude Code, đóng gói thành plugin, dành cho dev làm
một mình hoặc team nhỏ (SME). Đây không phải quy trình nặng nề kiểu công ty lớn.

Chỉ cần gõ một lệnh trong bất kỳ project nào:

```
/engineering-team:build thêm mã giảm giá cho giỏ hàng
```

Session chính sẽ đóng vai **Lead** và làm lần lượt các việc sau:
- đọc rule của project (CLAUDE.md, skills, agents, tài liệu kiến trúc) và viết tiêu chí nghiệm thu
- tự đánh giá độ lớn của task:
  - **nhỏ**: Lead tự làm
  - **vừa**: giao cho developer, rồi có reviewer độc lập kiểm tra
  - **lớn**: chốt contract trước, sau đó nhiều developer làm song song, mỗi người trong một git worktree riêng
- chạy vòng review → sửa → test lại, tối đa 3 vòng
- ghi kết quả 6 quality gate kèm bằng chứng
- báo cáo trung thực: chưa xong thì ghi INCOMPLETE/BLOCKED, không bao giờ ghi "không có bug"

## Lệnh

| Lệnh | Việc |
|---|---|
| `/engineering-team:build <yêu cầu>` | Làm trọn vòng từ hiểu yêu cầu đến báo cáo |
| `/engineering-team:fix <bug>` | Tái hiện bằng test fail trước, sửa đúng nguyên nhân gốc, kiểm tra regression |
| `/engineering-team:review [ref\|PR\|path] [--fix]` | Review độc lập, chỉ đọc. Thêm `--fix` để sửa luôn |
| `/engineering-team:test [phạm vi\|regression]` | Đợt QA: chạy test thật, tách lỗi mới khỏi lỗi có sẵn |
| `/engineering-team:improve-ui <màn hình>` | Review UX trước và sau khi sửa, có bằng chứng từ trình duyệt |
| `/engineering-team:retro [last N]` | Nhìn lại các lần chạy trước: lỗi hay lặp lại, xu hướng, và 1–3 kiểm tra tự động nên thêm |

## Cài đặt

Yêu cầu: Claude Code có hỗ trợ plugin và Python 3.12 trở lên (`python3`, `python3.12` hoặc `python3.13` trong `PATH`). Đây là thay đổi không tương thích ngược từ 0.3.0: thiếu Python phù hợp thì guard sẽ chặn các subagent của plugin.

```bash
claude plugin marketplace add hoanganhnvnb/engineering-team-kit
claude plugin install engineering-team@engineering-team-kit
```

Cách ghim version, cài cho cả team, nâng cấp, rollback và gỡ cài đặt: xem [install.md](install.md).

## Nguyên tắc chính

- Quy trình tương xứng với độ lớn của task. Phần lớn task là nhỏ.
- Tin vào bằng chứng, không tin vào lời tự báo cáo. Reviewer đọc diff thật, Lead tự chạy lại test.
- Quy tắc quan trọng được kiểm tra bằng script (`etk_run.py check`, guard hook), không chỉ viết bằng lời.
- Rule của project là ưu tiên cao nhất trong phạm vi của nó. Plugin chỉ áp dụng rule Shopify khi phát hiện project thật sự là Shopify.
- Không tự commit/push/deploy, không đụng vào thay đổi chưa commit của bạn.
- Mỗi vai trò dùng model phù hợp: `scout` (haiku) tìm file và xuất dữ liệu, `qa-engineer` (sonnet) chạy test và chạy thử, `code-reviewer` và `tech-writer` (opus) review và viết tài liệu, `developer`/`ux-reviewer` dùng model của phiên. Có thể đổi bằng `models` trong config.
- Test chứng minh code, chạy thật mới chứng minh tính năng: developer và QA chạy thử thay đổi và ghi bằng chứng `runtime`.
- Mỗi lỗi từ mức medium có đề xuất `hardening`, tức kiểm tra tự động rẻ nhất để lỗi đó không lặp lại. Chỉ đề xuất, bạn quyết định có áp dụng hay không.
- Nếu không có trình duyệt (Playwright MCP hoặc Claude in Chrome), G5 sẽ là `BLOCKED`. Cách cài: `claude mcp add playwright -- npx @playwright/mcp@latest`. Xem [limitations.md](limitations.md).

Một phần ý tưởng tham khảo từ các chia sẻ của Lauren Tan: [principles.md](principles.md).
