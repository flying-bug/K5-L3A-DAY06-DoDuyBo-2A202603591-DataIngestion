# Starter · PostgreSQL + pgvector

Bộ khởi động **tùy chọn** cho lab cá nhân. Docker Compose tạo PostgreSQL + pgvector local; các file trong `src/` là **khung pseudocode có TODO**, chưa đọc tài liệu, tạo embedding, lưu vector hay chạy benchmark. Bạn cần tự hiện thực. Vẫn có thể chọn Qdrant, Chroma hoặc vector store tương đương theo [GUIDE.md](../GUIDE.md).

## Cấu trúc

```text
starter/
├── docker-compose.yml     # PostgreSQL 16 + pgvector, chỉ mở cổng local
├── init.sql               # bật extension khi tạo database mới
├── requirements.txt       # psycopg, pypdf và python-dotenv
├── .env.example           # cấu hình mẫu; copy thành .env
├── scripts/check_setup.py # kiểm tra kết nối và extension (đã chạy được)
├── src/
│   ├── models.py          # cấu trúc dữ liệu mẫu
│   ├── ingestion.py       # TODO: đọc / chuẩn hóa tài liệu
│   ├── chunking.py        # TODO: chia chunk
│   ├── embeddings.py      # TODO: chọn model API hoặc local
│   ├── store.py           # TODO: lưu vector, metadata và filter
│   ├── evaluation.py      # TODO: chấm truy xuất, lưu trace
│   └── run.py             # TODO: kết nối các bước thành pipeline
├── data/                  # bạn tự chuẩn bị corpus được phép sử dụng
└── results/               # lưu kết quả của bạn
```

## 1. Cài và kiểm tra database

Cần Docker Desktop hoặc Docker Engine + Compose, Python **3.11–3.14**, và mạng để tải image/dependencies lần đầu. Các lệnh sau chạy từ thư mục `starter/`:

```bash
cd starter
python3 -m venv .venv
```

Kích hoạt `.venv`: macOS/Linux dùng `source .venv/bin/activate`; Windows PowerShell dùng `.venv\Scripts\Activate.ps1`. Sau đó:

```bash
python -m pip install -r requirements.txt
# macOS/Linux: cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py
```

Kỳ vọng: hiện tên database, phiên bản PostgreSQL và pgvector, sau đó `Setup OK`. Đây **chỉ là kiểm tra hạ tầng**, không phải kết quả benchmark. Docker dùng cổng `127.0.0.1:55433` và mật khẩu cố định **chỉ dùng local cho lab**; nếu cổng bận, sửa đồng thời port trong `docker-compose.yml` và `DATABASE_URL` trong `.env`. `init.sql` chỉ chạy khi volume mới được tạo; nếu database sẵn có chưa bật extension, xem log Docker và kiểm tra cấu hình thay vì xóa volume chứa dữ liệu.

Dừng container nhưng giữ dữ liệu:

```bash
docker compose -p day6_student_starter stop
```

## 2. Chọn embedding model

Điền key tương ứng trong `.env` nếu dùng OpenRouter, OpenAI hoặc Gemini; **không commit `.env`**. Model local không cần API key. `requirements.txt` chỉ có dependencies cơ bản: tự cài SDK hoặc thư viện local phù hợp với model bạn chọn và ghi lại version/lệnh cài trong báo cáo. Ghi tên model và số chiều; dùng cùng model cho toàn bộ chiến lược và vector query tương thích vector document.

## 3. Hoàn thiện pipeline

1. Đặt corpus vào `data/` hoặc cung cấp manifest/hướng dẫn truy cập. Đọc [GUIDE.md](../GUIDE.md) về **30 trang nội dung**, quyền dữ liệu và metadata.
2. Hoàn thiện từng hàm TODO trong `src/`. Lưu ID tài liệu, nguồn, trang/vị trí và ít nhất một trường filter có ích.
3. Xây ít nhất ba cấu hình; ví dụ A fixed-size, B theo đoạn, C như B nhưng có filter. Cần cùng corpus, model và benchmark; nạp lại không nhân đôi và xử lý chunk cũ khi dữ liệu đổi.
4. Tự viết ít nhất 20 câu hỏi kèm evidence, tách dev/test trước khi thử theo [BENCHMARK.md](../BENCHMARK.md). Lưu trace top-3 và báo cáo đủ năm tiêu chí.
5. Sau khi hoàn thiện, chạy `python -m src.run` từ thư mục `starter/`. Trước khi làm TODO, lệnh này **chủ động báo `NotImplementedError`**.

Lưu code, cấu hình, kết quả và lệnh chạy để người chấm tái lập; không commit key, dữ liệu mật hoặc dữ liệu không có quyền chia sẻ.

## 4. Cách chạy bài này (đã hiện thực)

Embedding: `embeddinggemma-300m` chạy local bằng CPU (768 chiều, vector đã chuẩn hóa, có prompt riêng cho query và document). Vector store: PostgreSQL 16 + pgvector 0.8.7, khoảng cách cosine, tìm kiếm chính xác (exact search). Chi phí 0.

```bash
cd starter
python -m venv .venv
.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env        # EMBEDDING_MODEL = HF id hoặc thư mục model local
docker compose -p day6_student_starter up -d --wait
.venv\Scripts\python scripts/check_setup.py
.venv\Scripts\python scripts/verify_benchmark.py   # kiểm chứng evidence trước khi chạy
.venv\Scripts\python -m src.run --ingest-only   # nạp; chạy lại lần 2 phải báo embedded 0, rows không đổi
.venv\Scripts\python -m src.run --split dev     # chạy dev, áp tiêu chí chọn -> results/selection.json
.venv\Scripts\python -m src.run --split test    # chỉ chạy được sau dev; tạo các bảng chấm tay
```

| Cấu hình | Chunk | Truy xuất |
|---|---|---|
| A | Cửa sổ 800 ký tự, overlap 100, trong từng trang | Không lọc |
| B | Gộp các đoạn văn tối đa 800 ký tự; tách chunk ở heading và khi `function` đổi | Không lọc |
| C | Dùng chung chunk với B | `WHERE function = …` chỉ khi câu hỏi có filter |

Kết quả nằm trong `results/`:

- `summary_{dev,test}.md`: bảng chỉ số.
- `traces_*.jsonl`: top-3 đầy đủ của từng câu.
- `run_*.json` và `runs/`: model, phiên bản thư viện, thời gian, thống kê chunk.
- `ingest_log.json`: trang bị loại hoặc rỗng, header và footer đã bỏ.
- `selection.json`: cấu hình được chọn trên dev.
- `audit/*.csv`: bảng audit coherence, grounding và metadata đã được điền nhãn và lý do sau khi rà soát trace/PDF. Đây là bản đánh giá thủ công có thể chủ quan; xem các ghi chú từng dòng và đối chiếu nguồn khi cần.
