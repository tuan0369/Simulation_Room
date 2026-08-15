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
   - Unified 3D 4-Room View: `http://localhost:8080/room3d.html`
3. **Đưa về trạng thái ban đầu:** Đảm bảo dashboard tải ở chế độ `baseline` (`Safe`, `Online`, Rủi ro quạt thấp).
4. **Chuẩn bị sẵn Terminal để demo lệnh CLI nếu cần.**

---

## Cảnh 1 — Giới thiệu & Kiến trúc Hệ sinh thái 4 Phòng (0:00 – 0:50)

**Trên màn hình:** Sơ đồ Kiến trúc Tích hợp (`report/hw2-evidence/00-integrated-architecture.png`) hoặc `docs/architecture.md`.

**Thuyết minh:**
> "Xin chào thầy cô và các bạn! Chào mừng đến với buổi demo dự án **EcoHVAC Guardian** — hệ sinh thái Digital Twin trong Project 2 cho việc quản lý và vận hành thông minh hệ thống HVAC phòng lab.
>
> Trong Project 1, chúng ta mới chỉ mô phỏng một phòng đơn lẻ. Sang Project 2, chúng tôi đã mở rộng thành một **Hệ sinh thái Cánh thông minh 4 Phòng (4-Zone Smart Wing Ecosystem)** hoàn chỉnh:
> - `Room 1`: Giảng đường lớn (30 chỗ)
> - `Room 2`: Phòng Lab Robotics (20 chỗ, kèm tải nhiệt thiết bị +400W)
> - `Room 3`: Phòng Seminar (15 chỗ)
> - `Room 4`: Computing Hub (20 chỗ, kèm cụm máy chủ +600W)
> Cả 4 phòng cùng chia sẻ lưu lượng làm mát từ một cụm xử lý không khí trung tâm (VAV AHU) công suất $0.48\text{ m}^3\text{/s}$.
>
> Kiến trúc tích hợp bộ điều khiển PID cục bộ chống bão hòa tích phân, bộ điều phối công bằng `occupied-comfort-debt-v2`, mô hình Machine Learning dự đoán hỏng quạt có tính giải thích cao, luồng pipeline dự báo rủi ro 5 bước, và mô hình 3D WebGL thời gian thực."

**Thao tác:** Rê chuột theo luồng kiến trúc: 4 Phòng Lab $\rightarrow$ Fairness Coordinator $\rightarrow$ Shared VAV AHU $\rightarrow$ ML Predictive Risk $\rightarrow$ MQTT $\rightarrow$ Dashboard & 3D Spatial Twin.

---

## Cảnh 2 — Trung tâm Vận hành, Luồng Pipeline 5 Bước & Bản đồ Phân bổ Tài nguyên (0:50 – 1:50)

**Trên màn hình:** Streamlit Operations Dashboard tại `http://localhost:8501` (tab `Operations centre (with 3D Twin)`).

**Thuyết minh:**
> "Đây là **Trung tâm Vận hành (Operations Centre)**. Ngay phía trên mô hình 3D là **Luồng Pipeline Dự báo Rủi ro & Giải pháp HVAC 5 Bước**:
> 1. **Step 1: Sensing** — Đo tổng số sinh viên (42 người) và tổng tải nhiệt thời gian thực (5.1 kW).
> 2. **Step 2: Prediction** — Dự báo nhu cầu làm mát ($0.241\text{ m}^3\text{/s}$) và rủi ro quạt ML ($2\%$).
> 3. **Step 3: Coordinator** — Phân xử công bằng theo nợ tiện nghi để chống bỏ đói dịch vụ.
> 4. **Step 4: Solution** — Đề xuất chính sách làm mát đón đầu (Preemptive Pre-Cooling).
> 5. **Step 5: Verify & Learn** — Chạy bộ kiểm thử tự động 4 bài và lưu tri thức vào Knowledge Base.
>
> Ngay bên dưới là **Bản đồ Phân bổ Tài nguyên Khí tươi (Resource Distribution Map)** dạng thanh phân đoạn trực quan: màu xanh dương cho Room 1, xanh ngọc cho Room 2, tím cho Room 3, cam cho Room 4, và xám cho dung lượng dự phòng."

**Thao tác:** Rê chuột chỉ lần lượt qua 5 hộp bước của Pipeline, thanh phân bổ tài nguyên, và mô hình 3D WebGL bên dưới.

---

## Cảnh 3 — Kịch bản Thử tải Đa phòng & Bão hòa Nhiệt động lực học (1:50 – 2:50)

**Trên màn hình:** Mục Guided Scenarios & Bộ tiêm tải nhiệt tương tác 4 phòng.

**Thuyết minh:**
> "Bây giờ, chúng ta sẽ thử nghiệm các tình huống tải đa dạng. Tôi sẽ kích hoạt kịch bản **'📝 Campus Exam (75 ppl)'** hoặc kéo thanh trượt số người tại **Room 3 (Seminar Room)** lên 14 người và **Room 4 (Computing Hub)** lên 16 người."

**Thao tác:** Nhấp nút **`📝 Campus Exam (75 ppl)`** hoặc điều chỉnh thanh trượt tải Room 3 / Room 4.

**Thuyết minh:**
> "Khi tải nhiệt tăng đột ngột:
> 1. Nhu cầu lưu lượng gió của 4 phòng tăng vọt vượt khả năng cung cấp của AHU.
> 2. Thanh phân bổ tài nguyên lập tức hiển thị cảnh báo **Capacity Deficit Alert** màu vàng.
> 3. Bộ điều phối công bằng ưu tiên cấp khí cho các phòng có nợ tiện nghi cao nhất để duy trì ổn định toàn cánh nhà."

---

## Cảnh 4 — Agent Tự hành, Popup Thông báo Tri thức & Kiểm định 4 Bài (2:50 – 4:00)

**Trên màn hình:** Khu vực Đề xuất Hành động & Banner Popup Agent Tự hành.

**Thuyết minh:**
> "Hệ thống cung cấp danh sách đề xuất độc lập cho từng phòng: `Execute for ROOM1`, `Execute for ROOM2`, `Execute for ROOM3`, và `Execute for ROOM4`.
>
> Khi chúng ta bật chế độ **'Autonomous Action Mode 🤖'**:
> 1. Agent tự động phát hiện nguy cơ quá nhiệt và áp dụng chính sách làm mát đón đầu từ Knowledge Base.
> 2. Một **Banner Popup nổi bật** màu xanh lục kèm thông báo Toast xuất hiện: *'AUTONOMOUS AGENT ACTIVE · KNOWLEDGE BASE POLICY APPLIED — Preemptive Precool (ROOM3)'*.
> 3. Thanh tiến trình chạy chu kỳ đánh giá thực tế (Tick 1 đến 15).
> 4. Sau 15 tick, chính sách tự động vượt qua 4 bài kiểm thử: Tiện nghi nhiệt (0% lỗi), Rủi ro thiết bị (98% an toàn), Tính nhất quán năng lượng (96%), và Tính công bằng (95%) rồi được lưu vào Knowledge Hub."

**Thao tác:** Bật toggle **`Autonomous Action Mode 🤖`**, chỉ vào Banner Popup màu xanh lục, thanh tiến trình tick, và thông báo Toast ở góc màn hình.

---

## Cảnh 5 — Tư vấn Nâng cấp Phần cứng CapEx khi Chạm Giới hạn Vật lý (4:00 – 4:50)

**Trên màn hình:** Thẻ đề xuất **Equipment Retrofit & CapEx Sizing Advisory**.

**Thuyết minh:**
> "Một điểm đặc biệt trong Project 2 là khi tối ưu hóa phần mềm chạm đến **giới hạn vật lý nhiệt động lực học** (tổng nhiệt $>8.5\text{ kW}$, lưu lượng yêu cầu $>0.55\text{ m}^3\text{/s}$ vượt 115% công suất AHU):
> Hệ thống sẽ tự động phát sinh khuyến nghị **Tư vấn Nâng cấp CapEx Thiết bị**:
> - **Option A:** Nâng cấp cụm VAV AHU trung tâm lên $0.75\text{ m}^3\text{/s}$ (Chi phí ~S$12.5k, hoàn vốn 1.8 năm).
> - **Option B:** Lắp thêm máy lạnh Inverter cục bộ $3.5\text{ kW}$ riêng cho Room 4 Computing Hub (Chi phí ~S$2.8k, hoàn vốn chỉ 11 tháng).
> Điều này giúp nhà quản lý cơ sở vật chất đưa ra quyết định đầu tư chính xác dựa trên dữ liệu thực tế."

**Thao tác:** Chỉ vào bảng so sánh Option A và Option B cùng thời gian hoàn vốn ROI trên giao diện.

---

## Cảnh 6 — Quản trị Minh bạch, Nhật ký SHA-256 & Kết luận (4:50 – 5:30)

**Trên màn hình:** Tab `Strategy & Governance` và `Self-Learning Knowledge Hub`.

**Thuyết minh:**
> "Toàn bộ mọi quyết định tự hành đều được lưu vết trong **Sổ cái Kiểm toán Mã hóa SHA-256** chống giả mạo và tuân thủ tuyệt đối chuẩn riêng tư Không-PII.
>
> Toàn bộ mã nguồn đã vượt qua **161 / 161 bài kiểm thử tự động** (100% Pass Rate). EcoHVAC Guardian chứng minh năng lực toàn diện của một hệ sinh thái Cyber-Physical Twin thông minh, an toàn và tối ưu chiến lược.
>
> Cảm ơn thầy cô và các bạn đã theo dõi!"

**Thao tác:** Cuộn qua bảng Knowledge Hub, bảng Audit Log, và kết quả kiểm thử terminal.
