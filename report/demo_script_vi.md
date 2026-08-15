# EcoHVAC Guardian — Kịch bản Video Demo (Project 2 / HW2)

**Thời lượng mục tiêu:** ~5–6 phút
**Học phần:** SUTD Digital Twin — Project 2 (Intelligent Ecosystem & Strategic Optimization)
**Định dạng:** Quay màn hình kèm thuyết minh (voice-over). Mỗi cảnh liệt kê hình ảnh hiển thị, thao tác thực hiện, và lời thoại gợi ý.

---

## Danh sách kiểm tra trước khi quay

1. **Khởi động toàn bộ hệ thống Multi-Twin:**
   ```bash
   # 1. Khởi động broker Mosquitto (MQTT 1883, WS 9001)
   docker compose up -d

   # 2. Chạy simulator (Terminal 1)
   uv run python simulator/publisher.py

   # 3. Chạy server 3D tĩnh (Terminal 2)
   uv run python -m http.server 8080 --directory room3d

   # 4. Chạy Streamlit Operations Dashboard (Terminal 3)
   ECOHVAC_3D_URL=http://localhost:8080 uv run streamlit run dashboard/app.py
   ```
2. **Mở các tab trình duyệt:**
   - Operations Dashboard: `http://localhost:8501`
   - Unified 3D Two-Room View: `http://localhost:8080/room3d.html`
3. **Đưa về trạng thái ban đầu:** Đảm bảo dashboard tải ở chế độ `baseline` (`Safe`, `Online`, Rủi ro quạt thấp).
4. **Chuẩn bị sẵn Terminal để demo lệnh CLI nếu cần.**

---

## Cảnh 1 — Giới thiệu & Kiến trúc Hệ sinh thái (0:00 – 0:50)

**Trên màn hình:** Sơ đồ Kiến trúc Tích hợp (`report/hw2-evidence/00-integrated-architecture.png`) hoặc `docs/architecture.md`.

**Thuyết minh:**
> "Xin chào thầy cô và các bạn! Chào mừng đến với buổi demo dự án **EcoHVAC Guardian** — hệ sinh thái Digital Twin trong Project 2 cho việc quản lý và vận hành thông minh hệ thống HVAC phòng lab.
>
> Trong Project 1, chúng ta mới chỉ mô phỏng một phòng đơn lẻ. Sang Project 2, chúng tôi đã nâng cấp thành một **hệ sinh thái đa bản sao số (Multi-Twin Ecosystem)** hoàn chỉnh: gồm hai phòng thí nghiệm độc lập (`Room 1` và `Room 2`) cùng chia sẻ công suất làm mát từ một cụm xử lý không khí (AHU) có dung lượng giới hạn.
>
> Kiến trúc của hệ thống tích hợp bộ điều khiển PID cục bộ, bộ điều phối chia sẻ công bằng dưới điều kiện thiết bị xuống cấp, tính toán năng lượng thời gian thực với COP 3.2, mô hình Machine Learning dự đoán rủi ro hỏng quạt có tính giải thích cao, và hiển thị trực quan 3D thời gian thực."

**Thao tác:** Rê chuột theo luồng kiến trúc 6 tầng: Multi-Twin + Local PID $\rightarrow$ Fairness Coordinator $\rightarrow$ Shared AHU $\rightarrow$ Predictive Model $\rightarrow$ MQTT $\rightarrow$ Dashboard & 3D Viewer.

---

## Cảnh 2 — Trung tâm Vận hành & Trạng thái Cơ sở (0:50 – 1:40)

**Trên màn hình:** Streamlit Operations Dashboard tại `http://localhost:8501` (tab `Operations centre`).

**Thuyết minh:**
> "Đây là **Trung tâm Vận hành (Operations Centre)**. Ở thanh trạng thái trên cùng: simulator báo `ONLINE`, công suất chia sẻ ở mức `SAFE` (An toàn), và rủi ro quạt ở mức `LOW (15%)`.
>
> Phía dưới, hai phòng đang vận hành độc lập:
> - `Room 1` có 8 người, nhiệt độ 22.8 °C.
> - `Room 2` có 2 người, nhiệt độ 22.8 °C.
> - Cụm AHU hoạt động với bộ lọc sạch (nghẹt 5%) và quạt tốt (hao mòn 3%), đáp ứng 80% lưu lượng khí mà không bị nghẽn công suất.
>
> Toàn bộ dữ liệu telemetry đều được gắn ID snapshot tuần tự và timestamp đồng bộ qua các topic MQTT có lưu trữ (retained)."

**Thao tác:** Cuộn chuột qua các thẻ trạng thái, thông số đo của Room 1 / Room 2, và trạng thái cấp gió AHU.

---

## Cảnh 3 — Kịch bản Thử tải Nghẽn Công suất (1:40 – 2:45)

**Trên màn hình:** Mục Guided Scenarios trên Dashboard.

**Thuyết minh:**
> "Bây giờ, chúng ta sẽ mô phỏng một tình huống vận hành khắc nghiệt: thiết bị xuống cấp kết hợp tải nhiệt tăng vọt.
>
> Tôi sẽ nhấn kích hoạt kịch bản **'Run shared-capacity stress test'**."

**Thao tác:** Nhấp chuột vào nút **`Run shared-capacity stress test`**.

**Thuyết minh:**
> "Ngay lập tức, bộ mô phỏng áp dụng các biến đổi:
> 1. Bộ lọc bị nghẹt 85% và quạt mòn 75%, làm lưu lượng gió tối đa của AHU tụt xuống chỉ còn khoảng 40%.
> 2. Đồng thời, số người ở Room 1 tăng vọt lên 24 sinh viên, tạo yêu cầu làm mát tới 10.0 kW. Room 2 yêu cầu 3.5 kW.
>
> Hãy quan sát: Tổng lưu lượng khí yêu cầu vượt xa khả năng cung cấp của AHU. Trạng thái hệ thống lập tức chuyển sang **`CONSTRAINED`** (Bị nghẽn công suất)."

**Thao tác:** Chỉ vào cảnh báo `CONSTRAINED`, sự chênh lệch giữa lưu lượng yêu cầu và lưu lượng thực cấp, và nhiệt độ Room 1 bắt đầu tăng do thiếu khí làm mát.

---

## Cảnh 4 — Bộ điều phối Công bằng & Nợ Tiện nghi (2:45 – 3:45)

**Trên màn hình:** Khu vực Coordination & Allocation trên Dashboard.

**Thuyết minh:**
> "Hệ thống giải quyết sự tranh chấp tài nguyên này như thế nào?
>
> EcoHVAC Guardian sử dụng thuật toán điều phối tất định **`occupied-comfort-debt-v2`**:
> 1. Ưu tiên tuyệt đối cho phòng có người sử dụng.
> 2. Ưu tiên phòng có độ lệch nhiệt độ dương lớn hơn.
> 3. Tích lũy **Nợ Tiện nghi (Comfort Debt)** (tính bằng °C·giây) cho các phòng bị thiếu hụt lưu lượng gió theo thời gian, đảm bảo tính công bằng dài hạn và chống bỏ đói dịch vụ.
>
> Đặc biệt, lưu lượng thực tế được cấp được phản hồi ngược về bộ PID. Cơ chế **Actuator Feedback** này giúp xả tích phân và ngăn ngừa hiện tượng bão hòa tích phân (anti-windup) khi tài nguyên vật lý bị nghẽn."

**Thao tác:** Chỉ vào các mã lý do điều phối (`occupied`, `above_setpoint`, `capacity_limited`, `higher_comfort_priority_applied`) và biểu đồ tích lũy Comfort Debt.

---

## Cảnh 5 — Trí tuệ Dự đoán & AI Có thể Giải thích (3:45 – 4:35)

**Trên màn hình:** Chuyển sang tab **`Predictive intelligence`**.

**Thuyết minh:**
> "Tiếp theo là khả năng bảo trì dự đoán thiết bị.
>
> Trong tab Predictive Intelligence, mô hình **Logistic Regression** tính toán xác suất hỏng quạt trong vòng 7 ngày tới. Dưới kịch bản stress test, rủi ro đã tăng lên **63.0% (Rủi ro Trung bình - Cần kiểm tra)**.
>
> Khác với các mô hình AI hộp đen, mô hình của chúng tôi hoàn toàn minh bạch:
> - Hiển thị trực tiếp các trọng số **log-odds đóng góp rủi ro**: độ rung cao (4.27 mm/s) và bộ lọc nghẹt (+85%) là hai nguyên nhân chính.
> - Tích hợp cơ chế kiểm tra miền dữ liệu (Domain Bounds): nếu dữ liệu bị lỗi, thiếu hoặc vượt ngoài miền huấn luyện (OOD), mô hình sẽ chủ động **từ chối dự đoán (Abstain)** thay vì đưa ra kết quả giả mạo.
> - Về mặt an toàn, dự đoán này đóng vai trò **khuyến nghị hỗ trợ con người ra quyết định (Human-in-the-loop)**, không tự ý can thiệp nguy hiểm vào phần cứng."

**Thao tác:** Chỉ vào đồng hồ đo rủi ro (63%), danh sách các nhân tố log-odds chính, và biểu đồ quỹ đạo rủi ro.

---

## Cảnh 6 — Chế độ xem 3D Đồng bộ & Kết nối MQTT (4:35 – 5:15)

**Trên màn hình:** Chuyển sang tab `http://localhost:8080/room3d.html` (Mô hình 3D).

**Thuyết minh:**
> "Đây là **Giao diện 3D Digital Twin**, được xây dựng bằng Three.js và kết nối trực tiếp qua MQTT WebSockets.
>
> Cả Room 1 và Room 2 được mô phỏng trực quan đồng thời cùng hệ thống ống gió AHU ở giữa:
> - Bản đồ nhiệt sàn đổi màu theo nhiệt độ thực tế của phòng.
> - Nhân vật di chuyển ra vào phòng theo số lượng người cập nhật thời gian thực.
> - Luồng hạt trong ống gió hiển thị trực quan lưu lượng khí được phân bổ.
>
> Mọi thao tác điều khiển đều hỗ trợ kiểm tra chống lặp lệnh (Idempotency) với mã `command_id` duy nhất."

**Thao tác:** Xoay camera quanh 2 phòng lab, xem đường ống AHU và chỉ báo kết nối WebSocket.

---

## Cảnh 7 — Lộ trình Chiến lược, ROI & Tổng kết (5:15 – 5:45)

**Trên màn hình:** Quay lại Dashboard $\rightarrow$ tab **`Strategy & governance`**.

**Thuyết minh:**
> "Cuối cùng, tab **Strategy & Governance** trình bày khung triển khai thực tế:
> - Một **Sandbox tính toán ROI** minh bạch với thời gian hoàn vốn thực tế khoảng 33 tháng.
> - Lộ trình triển khai 5 giai đoạn: từ mô phỏng thử nghiệm, Digital Shadow đọc dữ liệu thực, phi công có con người giám sát, đến tự động hóa toàn diện cho nhiều tòa nhà.
>
> Tóm lại, EcoHVAC Guardian đã hoàn thành xuất sắc các yêu cầu của Project 2 với hệ sinh thái đa bản sao số, điều khiển tối ưu công bằng, AI có khả năng giải thích và trực quan hóa 3D. Cảm ơn thầy cô và các bạn đã lắng nghe!"

**Thao tác:** Lướt nhanh qua bảng tính ROI và lộ trình 5 giai đoạn để kết thúc.

---

## Gợi ý trả lời khi bảo vệ / Q&A

- **Khi được hỏi về PID so với ML:** "Bộ điều khiển PID và coordinator trung tâm đảm nhận việc điều phối lưu lượng vật lý theo luật tất định; trong khi mô hình Machine Learning đóng vai trò tư vấn bảo trì dự đoán cho người vận hành."
- **Khi được hỏi về kiểm thử:** Chạy lệnh `uv run pytest` trong terminal để chứng minh 144 unit tests vượt qua 100% trong 0.4 giây.
- **Khi được hỏi về bảo mật:** "Phiên bản lớp học sử dụng MQTT nội bộ, nhưng chúng tôi đã thiết kế và tài liệu hóa đầy đủ mô hình sản xuất mục tiêu với mTLS, ACL phân quyền theo topic và nhật ký kiểm toán SQLite hash-chain."
