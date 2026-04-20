# Hệ thống Quản trị Tiến độ Lab PTIT

Hệ thống chuyên nghiệp phục vụ việc theo dõi, chấm công, và quản trị tiến độ các dự án/cam kết (Commitments) trong nội bộ các Lab thuộc Cơ sở PTIT. Được xây dựng trên nền tảng Flask (Python) với kiến trúc bảo mật nhiều lớp.

## 🚀 Tính năng nổi bật

Hệ thống vận hành bằng **Quy trình Xét duyệt 3 cấp độ (3-Level Workflow)**:
1. **Thành viên (Member):** Nhận phân công (Execution Items) từ Quản lý Lab. Trực tiếp làm việc, báo cáo trạng thái, và tải lên tệp minh chứng (Evidence Documents).
2. **Quản lý Lab (Manager):** Giám sát tiến độ thành viên trong Lab của mình. Có đặc quyền xét duyệt báo cáo con (Approve/Reject) và đóng gói nộp lên Admin xét duyệt bước cuối.
3. **Ban Quản trị (Admin):** Quản lý tối cao. Cấp phát tài khoản, phân bổ Lab, và là cấp thẩm định cuối cùng đưa ra quyết định chấp thuận hay yêu cầu sửa đổi cho một cam kết.

**Các Tiện ích Đi kèm:**
- **Dashboard Động:** Hệ thống hiển thị biểu đồ và thẻ số liệu tự động chuyển đổi thông minh dựa vào nhóm quyền (Role) của người dùng hiện tại đang truy cập (Admin/Manager/Member).
- **Hệ thống Notification:** Báo cáo thời gian thực mọi thay đổi trạng thái, giao việc hay quá hạn dự án.
- **Audit Trail & Update Controls:** Nhật ký lưu vết chi tiết mọi thao tác hệ thống; bộ đếm bộ nhớ truy biến để khống chế xung đột.

## 💻 Yêu cầu hệ thống

- Python 3.10+ (Đề xuất Python 3.12 / 3.13)
- Hỗ trợ đa nền tảng: Windows / Linux / macOS

## ⚙️ Hướng dẫn Cài đặt

1. **Tải mã nguồn:**
   ```bash
   git clone https://github.com/vduckj3n/github-demo-btl-py.git
   cd github-demo-btl-py
   ```

2. **Kích hoạt môi trường ảo (Virtual Environment):**
   *Trên Windows (PowerShell):*
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
   *Trên macOS / Linux:*
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Cài đặt thư viện phụ thuộc:**
   ```bash
   pip install -r requirements.txt
   ```

## 🚀 Chạy Ứng dụng

Ứng dụng có thể được chạy trực tiếp bằng `run.py`. Database tự động và tài khoản Admin gốc sẽ tự động được sinh ra nếu đây là lần khởi chạy đầu tiên.

```bash
python run.py
```

Truy cập vào ứng dụng trên trình duyệt web của bạn qua địa chỉ:
👉 `http://127.0.0.1:5000/`

**Tài khoản đăng nhập mặc định:**
- Tên đăng nhập: `admin`
- Mật khẩu: `admin123`

*(Quản trị viên sau khi đăng nhập cần tạo mới "Lab" và thêm các "Người dùng (Users)" vào hệ thống để bắt đầu vận hành).*

## 🧹 Công cụ Dọn dẹp Dữ liệu Test (Data Cleanup)

Để làm sạch rác sau một chu kỳ rà soát, kiểm thử (testing), nền tảng cung cấp một tập lệnh vệ sinh độc lập.

```bash
python cleanup_db.py
```
> Script này sẽ quét và xoá tận gốc toàn bộ các dự án/cam kết dùng để test (VD: tên chứa `test`, `aaaa`, `abc`) đi kèm với mọi hạng mục con, tệp báo cáo, và log hành vi sinh ra từ dự án test đó mà cấu trúc Lab, User không bị ảnh hưởng.

## 📂 Kiến trúc Mã Nguồn

- `run.py` — Tệp nổ máy (entry point) khởi động cục bộ của Server.
- `app/` — Cấu trúc mã hóa lõi phần mềm (Blueprints Architecture):
  - `__init__.py` — Tổ hợp cấu hình Controllers & Routing hệ thống.
  - `models.py` — Cấu trúc đối tượng CSDL (SQLAlchemy & ORM mapping).
  - `templates/` — Giao diện máy khách HTML & Jinja2 Macros.
  - `static/` — Chứa định dạng CSS nội bộ, hình ảnh và JavaScript.
- `config.py` — File định nghĩa các biến môi trường cấu hình mật.
- `instance/` — Vùng chứa Database nội bộ SQLite (`ptit_lab_progress.db`).
- `uploads/` — Nơi lưu trữ tài liệu minh chứng sau khi đã mã hóa tên tệp.

## ⚠️ Lưu ý kỹ thuật
- Nếu bạn gặp lỗi khi thực hiện chức năng **Xuất PDF báo cáo**, hãy chắc chắn thư viện báo cáo đã cài đặt đủ: `pip install reportlab`.
- Trong môi trường thực tế (Production Deployment), vui lòng thay thế hằng số `SECRET_KEY` bên trong `config.py`.
