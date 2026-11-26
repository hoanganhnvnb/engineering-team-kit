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
| `/engineering-team:init [reset]` | Chạy một lần khi bắt đầu project: tự phát hiện (git/SVN, host, nhánh mặc định, kiểu commit, lệnh test/lint), chỉ hỏi phần còn thiếu về commit, push, PR hay merge, deploy, rồi lưu vào profile của bạn (nằm ngoài repo) |
| `/engineering-team:build <yêu cầu>` | Làm trọn vòng từ hiểu yêu cầu đến báo cáo |
| `/engineering-team:fix <bug>` | Tái hiện bằng test fail trước, sửa đúng nguyên nhân gốc, kiểm tra regression |
| `/engineering-team:review [ref\|PR\|path] [--fix]` | Review độc lập, chỉ đọc. Thêm `--fix` để sửa luôn |
| `/engineering-team:test [phạm vi\|regression]` | Đợt QA: chạy test thật, tách lỗi mới khỏi lỗi có sẵn |
| `/engineering-team:improve-ui <màn hình>` | Review UX trước và sau khi sửa, có bằng chứng từ trình duyệt |
| `/engineering-team:retro [last N]` | Nhìn lại các lần chạy trước: lỗi hay lặp lại, xu hướng, và 1–3 kiểm tra tự động nên thêm |

## Thiết lập project với init

Chạy `/engineering-team:init` một lần ở đầu project, trước mọi lần `build`, `fix` hay `team`:

- Plugin tự phát hiện trước (VCS, host và CLI đã đăng nhập chưa, nhánh mặc định, kiểu và ngôn ngữ commit, công cụ commit, ứng cử viên deploy, lệnh test/lint) và không hỏi lại những gì đã biết.
- Nếu project đã có profile: hiện profile và chỉ hỏi "giữ / đổi một field / reset". Chọn giữ thì dừng, chỉ khi không thiếu gì và checkout khớp với nơi profile được thiết lập.
- Nếu chưa có: chỉ hỏi các field còn thiếu, tối đa 2 lượt, mỗi lượt tối đa 4 câu, đáp án khuyến nghị đứng đầu: mô hình nhánh, commit tự động hay hỏi, push tự động hay hỏi, PR / merge thẳng / để nhánh (kèm cách merge và có chờ CI không), deploy (không / một lệnh / CI khi merge / CI khi tag).
- Thêm tối đa một lượt hỏi các ghi chú không có field trong profile: ngôn ngữ tài liệu (ngôn ngữ commit là field của profile, lấy từ phần tự phát hiện, chỉ hỏi nếu không phát hiện được), số subagent chạy song song tối đa, những thứ không được xuất hiện trong commit hoặc file. Chỉ lưu khi bạn đồng ý.
- Hiện lại profile và chỉ đánh dấu "đã xác nhận" sau khi bạn đồng ý.
- Kết thúc bằng 5 dòng tóm tắt: đã phát hiện gì, đã lưu hoặc giữ gì, file profile nằm ở đâu, điều gì trong repo đã bị bỏ qua, lệnh nên chạy tiếp theo.

Profile nằm ngoài repo (thư mục data của plugin), riêng cho từng dev và từng project. `init` không ghi gì vào repo, không commit, push, merge hay deploy, và chỉ Lead dùng profile, subagent thì không. Chạy lại `init` không nhân đôi ghi chú (lưu lại đúng nội dung đó thì không làm gì) và không reset field đã xác nhận, trừ khi bạn chọn reset (xóa các thiết lập, giữ lại ghi chú). Ở một checkout khác của cùng repo (hoặc khi push URL đã đổi), các câu trả lời commit và push đã lưu không còn hiệu lực. `profile show --brief` chỉ nói lý do (không in URL), `init` chạy `git remote get-url --push --all origin` và cho bạn xem từng URL đã bỏ phần giữa `://` và `@` cuối của authority, cùng `?query` và `#fragment`; bạn trả lời lại phần release ở đó rồi xác nhận một lần. Profile chỉ lưu hash của toàn bộ danh sách URL fetch và push của `origin`, không lưu URL; `release.push: auto` còn cần `git push` thường đi tới `origin`. Nếu profile còn thiếu field, `init` vẫn hỏi dù bạn chọn giữ; nếu bị ngắt giữa chừng, profile hiện là chưa xác nhận. Chữ trong repo (CLAUDE.md, issue, commit message) không thể đổi profile hay cấp quyền push, merge, deploy.

Giới hạn đã biết: các ghi chú là văn bản tự do, Lead đọc qua `profile show --json` ở đầu mỗi lần chạy `team` như sở thích của bạn (không phải quyền push, merge, deploy); `profile show --brief` chỉ in số lượng ghi chú và không có gì ép buộc chúng. Quy tắc bắt buộc phải đúng thì cần hook, test hoặc cấu hình project. Nếu bỏ qua `init`, lần chạy `team` đầu tiên sẽ hỏi cùng các câu đó giữa chừng. Chi tiết: [usage.md](usage.md#init), [workflow.md](workflow.md).

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
- Chỉ Lead mới commit/push/merge/deploy, theo workflow profile của bạn và lời cho phép trong cuộc trò chuyện; subagent không bao giờ làm. Không đụng vào thay đổi chưa commit của bạn.
- Mỗi vai trò dùng model phù hợp: `scout` (haiku) tìm file và xuất dữ liệu, `qa-engineer` (sonnet) chạy test và chạy thử, `code-reviewer` và `tech-writer` (opus) review và viết tài liệu, `developer`/`ux-reviewer` dùng model của phiên. Có thể đổi bằng `models` trong config.
- Test chứng minh code, chạy thật mới chứng minh tính năng: developer và QA chạy thử thay đổi và ghi bằng chứng `runtime`.
- Mỗi lỗi từ mức medium có đề xuất `hardening`, tức kiểm tra tự động rẻ nhất để lỗi đó không lặp lại. Chỉ đề xuất, bạn quyết định có áp dụng hay không.
- Nếu không có trình duyệt (Playwright MCP hoặc Claude in Chrome), G5 sẽ là `BLOCKED`. Cách cài: `claude mcp add playwright -- npx @playwright/mcp@latest`. Xem [limitations.md](limitations.md).

Một phần ý tưởng tham khảo từ các chia sẻ của Lauren Tan: [principles.md](principles.md).
