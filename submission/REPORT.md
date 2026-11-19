# Báo cáo nhóm GROUP

## 1. Số liệu luyện tập
F1 rule / cross_check / overall (`score_findings.py`):

| Seed | Chỉ luật | Luật + mọi ứng viên | Sau review |
|---|---|---|---|
| 36 | 1.0 / — / 0.8 | 1.0 / 0.7 / 0.9 | 1.0 / 0.9 / 1.0 |
| 101 | 1.0 / — / 0.8 | 1.0 / 0.4 / 0.8 | |
| 202 | 1.0 / — / 0.7 | 1.0 / 0.7 / 0.9 | |
| 303 | 1.0 / — / 0.7 | 1.0 / 0.7 / 0.9 | |

- Ứng viên: lô sạch (`--no-faults`) **0**; seed 36 **11 / 10 ảnh**; 101: 8/8, 202: 11/11, 303: 13/12.
- Ngưỡng (không dùng `_private`), chỉnh trên `runs/clean` (50 ảnh) đến khi ra 0 ứng viên:
  - Ghép box ↔ segment cùng lớp: IoU bbox ≥ `MATCH_IOU = 0.5` (bbox segment lấy từ pixel mask).
  - `bbox_drift`: pixel segment trong box < `DRIFT_COVER = 0.98`.
  - `class_swap`/`category_swap`: khác lớp, IoU ≥ `SWAP_IOU = 0.7`.
  - `instance_merge`: segment có ≥ 15% pixel trong mỗi box (≥ 2 box cùng lớp), tổng ≥ 80%.
  - `missing_box`: segment thing ≥ 300 px và ≥ 0,1% ảnh, không box cùng lớp phủ ≥ 98%.

## 2. Vì sao báo hết ứng viên làm F1 giảm?
Ứng viên chỉ là nghi vấn. Nhận hết mà không xem ảnh gây hai loại sai:
- **Sai type:** validator không biết bên nào sai giữa `class_swap` và `category_swap`. Đoán sai = 1 FP + 1 FN.
- **Lệch tự nhiên của COCO:** ứng viên điểm thấp (`missing_box` phủ 0.94, `bbox_drift` cover 0.903) có thể không phải lỗi, làm giảm precision.

Nhận hết: cross_check ≈ 0.7 (0.4 ở seed 101). Theo RUBRIC, lỗi không có `confirmed` bị bỏ, nên điểm chỉ bằng kiểm luật. Seed 36 sau review: cross_check 0.7 → 0.9, chủ yếu nhờ đổi `000000020333` (bowl) và `000000018833` (cat) sang `category_swap`.

Minh bạch: `review_log.csv` seed 36 do Quang xem ảnh và ghi

## 3. Quyết định và lineage
- **QC v1** (`lab250_6112a1fce312`): **22/250 ảnh lỗi = 8,8% → HOLD** (ngưỡng 2%). Đã ghi `decision=HOLD` vào `runs/lineage.jsonl`.
  - Luật (12): `invalid_class` 2, `duplicate_box` 2, `guideline_mismatch` 2, `invalid_category_id` 2, `bbox_out_of_bounds` 1, `scene_leak` 1, `thing_overlap` 1, `wrong_hash` 1.
  - Gán nhãn (10): `missing_box` 4, `class_swap` 2, `category_swap` 2, `bbox_drift` 1, `instance_merge` 1.
- **Tính theo tỉ lệ ảnh, không theo số lỗi:** mỗi ảnh lỗi là một mẫu train sai; 22 lỗi trên 250 ảnh khác hẳn trên 25 000 ảnh.
- **R-021:** `lineage.py impact` → `affected=True action=review_or_retrain`. Model đã học nhãn sai, `scene_leak` làm số val/test tăng ảo. Sửa dataset không sửa trọng số: đánh giá lại trên dữ liệu sạch hoặc train lại trên v2.

## 4. Hash chứng minh gì, không chứng minh gì?
- **Chứng minh:** file nhận được giống từng byte lúc ghi hash.
  - `manifest.csv`: sha256 cho 476 file (238 ảnh + 238 nhãn).
  - `lab250_6112a1fce312_v2.sha256`: `4788ed7bc41af1ccf68d5b5bc5229c0d4f39418e64ebaae3dce65d8cfda79222`. `pack_release.py` đóng gói cố định thứ tự và thời gian; H15 đóng gói lại ra đúng mã.
- **Không chứng minh:** nhãn đúng, ảnh đúng nội dung, manifest gốc đúng. Ví dụ `000000001993`: hash v1 lệch file thật, nhưng hash không nói bên nào sai. Mở ảnh kiểm (640×419, khớp nhãn) → giữ trong v2, ghi hash mới.
- **Không ghi đè v1:** R-021 đã train trên v1, cần giữ để truy vết. v2 có `parent` = v1; H1 xác nhận `delivery/` không bị sửa.
- **v2 → Release:** 238 ảnh, 1678 nhãn.
  - 12 ảnh lỗi detection → `rework_queue.csv`, giao người gán/kiểm theo `jobs.csv`.
  - Sửa trong v2: `scene_374` về val (`000000009772`); guideline theo job (`000000000885`, `000000015335`); hash `000000001993`.
  - 6 ảnh chỉ lỗi panoptic ở lại, ghi trong README báo team panoptic.

## 5. Truy vết
- **Ticket:** model bỏ sót `bottle` bị che / ở mép (`scene_742`, `scene_768`). Guideline v1.3 bắt buộc gán, v1.2 cho bỏ qua → job v1.2: J01–J04.
  - **Tầng a** (cảnh ticket nêu): `000000005193` (J03), `000000007574` (J04).
  - **Tầng b** (cảnh khác): `000000002685` (J02), `000000006471` (J03), `000000008021` (J04), `000000009590` (J04).
  - **notify:** A02, A03, A05, Q01, Q02, Q03 (J02–J04; J01 không có `bottle`).
- **a khác b:** a đã được báo, chỉ cần xác nhận; b do nhóm tự tìm. Chỉ sửa a thì b vẫn dạy model bỏ sót.
- **Guideline theo job, không theo metadata:** `guideline_version` trong metadata có thể chính là lỗi `guideline_mismatch` (`000000000885`, `000000015335`).
- **Giới hạn:** ảnh không có box `bottle` nào thì không lọc được bằng nhãn, phải xem ảnh.
- **Kết quả:** tier_a 1.0 · tier_b 1.0 · notify 1.0; H16 PASS.

## 6. Bug hoặc điểm chưa rõ trong lab (nếu có)
<<>>