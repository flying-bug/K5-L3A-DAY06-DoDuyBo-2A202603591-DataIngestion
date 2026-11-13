# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline

- **Chủ đề/nguồn:** NIST, *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*, NIST AI 100-1, bản tháng 1/2023. PDF lấy từ DOI `https://doi.org/10.6028/NIST.AI.100-1`; manifest ghi đây là tài liệu công khai của Chính phủ Hoa Kỳ/NIST, ngày truy cập 2026-11-13 và SHA-256.
- **Quy mô:** PDF có 48 trang vật lý; tính 41 trang nội dung (trang 6–15, 17–47). Loại bìa, trang tiêu đề, disclaimer/front matter, mục lục, trang hình chỉ có caption và bìa sau; chi tiết ở `data/manifest.csv` và `data/pages_manifest.csv`.
- **Chuẩn hóa:** `pypdf` trích xuất text; chuẩn hóa Unicode NFKC, gộp dòng bị xuống dòng/ngắt từ, bỏ running header/footer và chia block theo heading/đoạn. PDF có lớp text, không cần OCR. Giới hạn: chỉ thử trên một PDF có cấu trúc; extraction bảng/hình có thể không giữ bố cục như bản gốc.
- **Embedding:** `embeddinggemma-300m` chạy local CPU qua sentence-transformers, 768 chiều, vector chuẩn hóa; prompt document/query được ghi trong `results/run_dev.json`. Chi phí API: $0. Thời gian embedding lần đầu theo experiment log: A 28.3 giây, B 23.8 giây; chạy tái lập hiện tại bỏ qua chunk không đổi nên embedding 0 giây.
- **Vector store:** PostgreSQL 16.16 + pgvector 0.8.7, cosine distance, exact search (không ANN index), bảng `chunks`. Python 3.12.10; sentence-transformers 5.7.0, transformers 5.22.2, torch 2.15.0+cpu. Lệnh: từ `starter/`, `python -m src.run --split dev`; sau khi chốt cấu hình dev, `python -m src.run --split test`.
- **Metadata:** `document_id`, `source`, số trang PDF, số trang in, part, section và function (GOVERN/MAP/MEASURE/MANAGE); function được suy ra từ heading của tài liệu, dùng filter khi câu hỏi chỉ rõ function. Các chỉ số tự động báo 0 chunk trùng sau ingest lại.

## Cấu hình và benchmark

- **A:** cửa sổ ký tự cố định 800, overlap 100, trong từng trang, không filter.
- **B:** gom theo đoạn, tối đa 800 ký tự, ngắt tại heading/function; đoạn dài chia ở ranh giới câu, không filter.
- **C:** cùng chunk và metadata như B; thêm SQL filter theo function khi câu hỏi cung cấp function. B–C chỉ khác việc áp filter.
- Benchmark có 22 câu: 16 dev / 6 test, gồm câu trực tiếp, paraphrase, điều kiện và câu hỏi có filter. Evidence được xác minh tự động với script benchmark trước chạy. Bộ câu hỏi/split được giữ cố định.
- Quy tắc chọn đã đăng ký: ưu tiên dev Evidence Hit@3, rồi Hit@1, rồi ít chunk hơn. B và C hòa theo quy tắc này, vì vậy cả hai được mang sang test.

## Kết quả tự động

| Strategy | Split | Hit@1 | Evidence Hit@3 | Chunk count | Truy vấn trung bình | Thời gian embedding lần đầu | Chi phí |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | dev | 12/16 | 13/16 | 157 | 109.13 ms | 28.3 s | $0 |
| B | dev | 13/16 | 15/16 | 186 | 110.42 ms | 23.8 s | $0 |
| C | dev | 13/16 | 15/16 | 186 | 108.55 ms | dùng chung index B | $0 |
| A | test | 4/6 | 5/6 | 157 | 141.37 ms | không phát sinh | $0 |
| B | test | 4/6 | 4/6 | 186 | 131.13 ms | không phát sinh | $0 |
| C | test | 4/6 | 4/6 | 186 | 137.83 ms | không phát sinh | $0 |

Các thời gian truy vấn là trung bình trong run; test chỉ có sáu câu nên không đại diện cho hiệu năng tổng quát. Kết quả đầy đủ và trace ở `starter/results/summary_*.md`, `starter/results/run_*.json`, `starter/results/traces_*.jsonl`.

| Strategy | Coherence trung bình /2 | Metadata đúng/đủ | Filter tuân thủ | Grounding thủ công |
|---|---:|---:|---:|---:|
| A | Chưa chấm | Chưa chấm | dev 4/4; test 2/2 (tự động) | Chưa chấm |
| B | Chưa chấm | Chưa chấm | dev 4/4; test 2/2 (tự động) | Chưa chấm |
| C | Chưa chấm | Chưa chấm | dev 4/4; test 2/2 (tự động) | Chưa chấm |

**Audit thủ công còn cần hoàn tất:** các file `starter/results/audit/coherence.csv`, `metadata.csv`, `grounding.csv` hiện có các trường nhãn/lý do để trống. Không dùng chỉ số tự động thay cho đánh giá thủ công; cần đọc mẫu theo GUIDE và điền nhãn cùng lý do trước khi nộp báo cáo cuối.

## Phân tích và kết luận

- Trên dev, B/C tốt hơn A về Evidence Hit@3 (15/16 so với 13/16) và Hit@1 (13/16 so với 12/16). Việc giữ ranh giới đoạn giúp evidence dễ nằm trọn trong chunk; toàn bộ 22 evidence quote được xác định là có thể chứa trong chunk B/C. A cắt mất evidence q10 qua ranh giới cửa sổ.
- Trên test nhỏ, A đạt 5/6 Evidence Hit@3; B/C đạt 4/6. B/C bỏ lỡ q18 và q22; A bỏ lỡ q18. Đây là kết quả test trái chiều với lựa chọn theo dev, nên chưa có cơ sở khẳng định B/C tốt hơn ngoài benchmark này.
- B và C cho kết quả giống nhau trên dev/test. Với tập này, filter không cải thiện retrieval; mức tuân thủ tự động đều 4/4 dev và 2/2 test cho câu có filter. Câu q11 vẫn là miss ở dev cho cả cấu hình.
- Theo quy tắc đã định trước, B và C cùng được chọn trên dev. Nếu cần một cấu hình vận hành đơn giản cho corpus này, B đủ vì C không cho thấy lợi ích đo được; đây là nhận định giới hạn trong benchmark hiện tại.
- Hạn chế: một tài liệu, test chỉ sáu câu, embedding local CPU và không có audit thủ công hoàn tất. Chưa kết luận được chất lượng grounding/coherence/metadata thủ công. Cần hoàn thiện audit, đọc từng miss và thử thêm tài liệu/câu hỏi trước khi khái quát.

## Nhật ký và minh chứng

- Cấu hình/giả thuyết: `artifacts/experiment_log.csv`.
- Trace dev/test: `starter/results/traces_dev.jsonl`, `starter/results/traces_test.jsonl`.
- Nhãn audit cần hoàn thiện: `starter/results/audit/`.
- Kết quả benchmark và lựa chọn: `starter/results/summary_dev.md`, `starter/results/summary_test.md`, `starter/results/selection.json`.
