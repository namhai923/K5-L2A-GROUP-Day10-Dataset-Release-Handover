Release: lab250_6112a1fce312_v2
Parent: lab250_6112a1fce312
Số ảnh: 238
Số nhãn: 1678
Guideline: v1.2 (J01, J02, J03, J04), v1.3 (J05, J06, J07, J08, J09, J10)
QC v1: 22/250 = 8,8%
Kết luận v1: Hold — 8,8% ảnh lỗi > ngưỡng 2%
Kết luận v2: Release — tách 12 ảnh lỗi nhãn detection sang rework_queue; sửa split, hash, guideline trong v2; còn 6 ảnh lỗi panoptic (detection đúng) chờ team panoptic
Ghi chú: split: scene_374 dua ca canh ve mot split (000000009772 train->val) | hash: 000000001993 da mo anh kiem (mo duoc, dung kich thuoc va noi dung voi nhan), chi manifest v1 sai; manifest.csv ghi hash moi | guideline: truyvet.csv lay guideline theo job trong jobs.csv, khong theo metadata anh (000000000885, 000000015335 metadata ghi sai) | rework: 12 anh trong rework_queue.csv giao lai dung nguoi gan/kiem theo jobs.csv (A01/Q01: 1, A01/Q02: 1, A01/Q03: 1, A02/Q01: 2, A03/Q01: 1, A03/Q03: 2, A04/Q01: 4) | panoptic: 6 anh loi chi o panoptic, nhan detection dung nen o lai v2, bao team panoptic: 000000007386 (instance_merge), 000000008899 (invalid_category_id), 000000009483 (invalid_category_id), 000000014007 (thing_overlap), 000000018833 (category_swap), 000000020333 (category_swap)
