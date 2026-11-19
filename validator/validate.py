#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validator của nhóm: bắt lỗi luật và sinh ứng viên lỗi gán nhãn.

Cách chạy (giao diện cố định):
    python validator/validate.py <thư_mục_delivery> --out <errors.json> [--candidates <candidates.json>]

- Chỉ đọc thư mục delivery được truyền vào; không đọc _private/, data_source/, annotation COCO.
- Chỉ dùng thư viện chuẩn; đọc PNG bằng scripts/pngutil.py; không dùng mạng.
- errors.json chỉ chứa lỗi luật. Lỗi gán nhãn chỉ là ứng viên (candidates.json), phải xem ảnh rồi mới chốt.
"""

from __future__ import annotations  # cho phép ghi kiểu dữ liệu kiểu mới (list[str]) trên Python 3.10

import argparse  # đọc tham số dòng lệnh
import csv  # đọc jobs.csv
import hashlib  # tính sha256
import itertools  # groupby để gom các pixel liền nhau trên một hàng
import json  # đọc/ghi file JSON
import sys  # chỉnh sys.path và stdout
from pathlib import Path  # thao tác đường dẫn

# Thư mục scripts/ nằm cạnh thư mục validator/ trong repo
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"  # đường dẫn tới scripts/
sys.path.insert(0, str(SCRIPTS_DIR))  # thêm scripts/ vào đường tìm module để import pngutil
import pngutil  # noqa: E402  # hàm đọc PNG RGB 8-bit, chỉ dùng thư viện chuẩn

# ---------------------------------------------------------------------------
# Ngưỡng. Chọn theo định nghĩa lỗi trong docs/DELIVERY.md và đo nhiễu trên lô sạch
# (runs/clean), KHÔNG lấy từ tham số của inject_release.py.
# ---------------------------------------------------------------------------
NUM_CLASSES = 80  # detection có 80 lớp, id hợp lệ 0..79
OOB_EPS = 1e-4  # dung sai (đơn vị chuẩn hoá) cho sai số làm tròn 6 chữ số khi box chạm đúng mép
DUP_SIZE_TOL_PX = 0.6  # hai box "cùng kích thước": rộng/cao lệch nhau không quá 0,6 pixel
DUP_SHIFT_MAX_PX = 3.0  # box lặp chỉ lệch tâm 1–2 pixel; cho tối đa 3 pixel để có dư
MATCH_IOU = 0.5  # IoU tối thiểu để coi box và segment cùng lớp là một vật
SWAP_IOU = 0.7  # box và segment khác lớp phải trùng vị trí rất sát mới coi là nghi đổi lớp
DRIFT_COVER = 0.98  # lô sạch: cặp ghép đúng có ~100% pixel segment nằm trong box; dưới 98% thì nghi box lệch
BOX_PAD_PX = 1.0  # nới box thêm 1 pixel khi đếm pixel bên trong, bù sai số làm tròn
MERGE_SHARE = 0.15  # mỗi box phải chứa ít nhất 15% pixel của segment thì mới tính là "một phần" của segment
MERGE_FILL = 0.30  # và box đó phải được segment lấp ít nhất 30% diện tích
MERGE_TOTAL = 0.80  # các box đó cộng lại phải chứa ít nhất 80% pixel của segment
MISSING_MIN_FRAC = 0.001  # segment thing không có box: chỉ tính nếu chiếm ít nhất 0,1% ảnh
MISSING_MIN_PX = 300  # và ít nhất 300 pixel ("vật đáng kể"; vật nhỏ hơn thì nhiễu tự nhiên nhiều)


def sha256_file(path: Path) -> str:
    """Tính sha256 trên bytes của file (đọc chế độ nhị phân)."""
    h = hashlib.sha256()  # tạo bộ băm sha256
    with path.open("rb") as f:  # mở file ở chế độ rb để băm đúng bytes
        for chunk in iter(lambda: f.read(1 << 20), b""):  # đọc từng khối 1 MB đến hết file
            h.update(chunk)  # đưa khối vào bộ băm
    return h.hexdigest()  # trả về chuỗi hex 64 ký tự


def load_json(path: Path):
    """Đọc file JSON theo UTF-8."""
    return json.loads(path.read_text(encoding="utf-8"))  # đọc text rồi parse JSON


def stem_of(name: str) -> str:
    """Lấy tên ảnh không có đuôi và không có thư mục, ví dụ 'images/a.jpg' -> 'a'."""
    return Path(name).stem  # Path.stem bỏ thư mục và phần mở rộng


# ---------------------------------------------------------------------------
# Đọc nhãn detection
# ---------------------------------------------------------------------------
def parse_labels(path: Path) -> list[dict]:
    """Đọc file YOLO. Mỗi dòng: class_id x_center y_center width height (chuẩn hoá 0-1)."""
    boxes = []  # danh sách box của ảnh
    text = path.read_text(encoding="utf-8", errors="replace")  # đọc file nhãn, ký tự lạ thay bằng '?'
    for line_no, line in enumerate(text.splitlines()):  # duyệt từng dòng kèm số thứ tự
        parts = line.split()  # tách theo khoảng trắng
        if not parts:  # dòng trống
            continue  # bỏ qua
        box = {"line": line_no, "raw": line.strip()}  # lưu số dòng và nội dung gốc để báo cáo
        try:  # thử đọc class_id là số nguyên
            box["cls"] = int(parts[0])  # class_id
        except ValueError:  # class_id không phải số nguyên (ví dụ '3.5' hoặc chữ)
            box["cls"] = None  # đánh dấu class không hợp lệ
        try:  # thử đọc 4 toạ độ
            xc, yc, w, h = (float(v) for v in parts[1:5])  # tâm x, tâm y, rộng, cao
            if len(parts) != 5:  # thừa hoặc thiếu cột
                raise ValueError  # coi như toạ độ hỏng
            box.update(xc=xc, yc=yc, w=w, h=h, ok=True)  # lưu toạ độ, đánh dấu đọc được
        except ValueError:  # thiếu cột hoặc không phải số
            box.update(xc=0.0, yc=0.0, w=0.0, h=0.0, ok=False)  # toạ độ hỏng
        boxes.append(box)  # thêm box vào danh sách
    return boxes  # trả về mọi box của ảnh


def box_to_px(box: dict, width: int, height: int) -> tuple[float, float, float, float]:
    """Đổi box YOLO chuẩn hoá sang pixel (x1, y1, x2, y2)."""
    x1 = (box["xc"] - box["w"] / 2) * width  # mép trái
    y1 = (box["yc"] - box["h"] / 2) * height  # mép trên
    x2 = (box["xc"] + box["w"] / 2) * width  # mép phải
    y2 = (box["yc"] + box["h"] / 2) * height  # mép dưới
    return x1, y1, x2, y2  # trả về 4 toạ độ pixel


def iou(a: tuple, b: tuple) -> float:
    """IoU của hai hình chữ nhật (x1, y1, x2, y2)."""
    iw = min(a[2], b[2]) - max(a[0], b[0])  # chiều rộng phần giao
    ih = min(a[3], b[3]) - max(a[1], b[1])  # chiều cao phần giao
    if iw <= 0 or ih <= 0:  # không giao nhau
        return 0.0  # IoU bằng 0
    inter = iw * ih  # diện tích phần giao
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter  # diện tích hợp
    return inter / union if union > 0 else 0.0  # chia, tránh chia cho 0


# ---------------------------------------------------------------------------
# Đọc mask panoptic
# ---------------------------------------------------------------------------
def read_mask_runs(path: Path) -> tuple[int, int, dict]:
    """Đọc mask PNG, trả về (rộng, cao, {segment_id: thông tin}).

    Mỗi segment lưu: số pixel, bbox thật từ mask, và danh sách 'run' (y, x_đầu, x_cuối)
    để đếm nhanh số pixel nằm trong một box bất kỳ.
    """
    width, height, pixels = pngutil.read_rgb(path)  # giải mã PNG thành bytes RGB liên tiếp
    stride = width * 3  # số byte của một hàng
    segs: dict[int, dict] = {}  # kết quả theo segment id
    for y in range(height):  # duyệt từng hàng
        row = pixels[y * stride:(y + 1) * stride]  # bytes của hàng y
        triples = zip(row[0::3], row[1::3], row[2::3])  # ghép (R, G, B) cho từng pixel (chạy ở C, nhanh)
        x = 0  # cột hiện tại
        for rgb, group in itertools.groupby(triples):  # gom các pixel liền nhau cùng màu thành một run
            n = sum(1 for _ in group)  # độ dài run
            sid = rgb[0] + rgb[1] * 256 + rgb[2] * 65536  # id segment = R + G*256 + B*256^2
            seg = segs.get(sid)  # lấy thông tin segment nếu đã gặp
            if seg is None:  # lần đầu gặp segment này
                seg = {"count": 0, "x1": x, "y1": y, "x2": x + n, "y2": y + 1, "runs": []}  # khởi tạo
                segs[sid] = seg  # lưu lại
            seg["count"] += n  # cộng số pixel
            seg["runs"].append((y, x, x + n))  # lưu run [x, x+n) trên hàng y
            seg["x1"] = min(seg["x1"], x)  # cập nhật mép trái bbox
            seg["x2"] = max(seg["x2"], x + n)  # cập nhật mép phải bbox (không gồm)
            seg["y2"] = y + 1  # hàng cuối cùng gặp segment (duyệt từ trên xuống nên luôn tăng)
            x += n  # sang run tiếp theo
    return width, height, segs  # trả kết quả


def pixels_in_box(seg: dict, box: tuple, pad: float = BOX_PAD_PX) -> int:
    """Đếm số pixel của segment nằm trong box (đã nới thêm 'pad' pixel mỗi phía)."""
    bx1, by1, bx2, by2 = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad  # box sau khi nới
    total = 0  # số pixel đếm được
    for y, x0, x1 in seg["runs"]:  # duyệt từng run của segment
        if y + 0.5 < by1 or y + 0.5 > by2:  # tâm pixel của hàng này nằm ngoài box theo chiều dọc
            continue  # bỏ qua run
        lo = max(x0, bx1)  # mép trái phần giao (theo toạ độ liên tục)
        hi = min(x1, bx2)  # mép phải phần giao
        if hi > lo:  # có phần giao
            total += int(round(hi)) - int(round(lo))  # cộng số pixel trong phần giao (làm tròn về pixel)
    return total  # trả về số pixel


# ---------------------------------------------------------------------------
# Lỗi luật
# ---------------------------------------------------------------------------
def check_rules(root: Path) -> tuple[list[dict], dict]:
    """Chạy 9 luật. Trả về (danh sách lỗi, ngữ cảnh dùng lại cho phần đối chiếu)."""
    manifest = load_json(root / "manifest.json")  # manifest: đường dẫn + sha256 từng file
    metadata = load_json(root / "metadata.json")  # metadata: scene, split, job, guideline từng ảnh
    panoptic = load_json(root / "panoptic.json")  # nhãn panoptic
    items = manifest.get("items", {})  # các ảnh trong manifest, khoá là tên ảnh
    num_classes = int(manifest.get("num_classes", NUM_CLASSES))  # số lớp detection (mặc định 80)

    findings: dict[str, list[str]] = {}  # lỗi theo từng ảnh: {tên ảnh: [loại lỗi, ...]}
    scene_findings: list[dict] = []  # lỗi scene_leak (target là scene_id)

    def add(image: str, kind: str) -> None:  # hàm phụ: ghi một lỗi cho một ảnh
        findings.setdefault(image, [])  # tạo danh sách nếu chưa có
        if kind not in findings[image]:  # không ghi trùng
            findings[image].append(kind)  # thêm loại lỗi

    # Kích thước ảnh lấy từ panoptic.json (khoá theo tên ảnh không đuôi)
    sizes = {stem_of(im["file_name"]): (int(im["width"]), int(im["height"])) for im in panoptic.get("images", [])}  # {tên: (rộng, cao)}

    # --- 1. File: missing_image, wrong_hash ---
    for image, entry in items.items():  # duyệt từng ảnh trong manifest
        img_path = root / entry.get("image", f"images/{image}.jpg")  # đường dẫn ảnh ghi trong manifest
        if not img_path.is_file():  # manifest có ảnh nhưng thiếu file
            add(image, "missing_image")  # ghi lỗi thiếu ảnh
            continue  # không kiểm hash của ảnh đã thiếu
        for key in ("image", "label", "mask"):  # kiểm hash của cả ảnh, nhãn và mask
            rel = entry.get(key)  # đường dẫn tương đối của file
            expected = entry.get(f"{key}_sha256")  # sha256 ghi trong manifest
            if not rel or not expected:  # manifest không ghi file/hash này
                continue  # không có gì để so
            path = root / rel  # đường dẫn đầy đủ
            if path.is_file() and sha256_file(path) != str(expected).lower():  # tự tính sha256 rồi so
                add(image, "wrong_hash")  # hash không khớp
                break  # một ảnh chỉ cần ghi một lần

    # --- 2. Nhãn detection: invalid_class, bbox_out_of_bounds, duplicate_box ---
    labels: dict[str, list[dict]] = {}  # giữ box của từng ảnh để dùng lại khi đối chiếu
    for image, entry in items.items():  # duyệt từng ảnh
        lbl_path = root / entry.get("label", f"labels/{image}.txt")  # đường dẫn file nhãn
        if not lbl_path.is_file():  # không có file nhãn
            continue  # bỏ qua
        boxes = parse_labels(lbl_path)  # đọc các box
        labels[image] = boxes  # lưu lại
        if any(b["cls"] is None or not (0 <= b["cls"] < num_classes) for b in boxes):  # class_id ngoài 0..79
            add(image, "invalid_class")  # ghi lỗi lớp không hợp lệ
        for b in boxes:  # kiểm từng box có nằm trong ảnh không
            x1 = b["xc"] - b["w"] / 2  # mép trái (chuẩn hoá)
            y1 = b["yc"] - b["h"] / 2  # mép trên
            x2 = b["xc"] + b["w"] / 2  # mép phải
            y2 = b["yc"] + b["h"] / 2  # mép dưới
            outside = x1 < -OOB_EPS or y1 < -OOB_EPS or x2 > 1 + OOB_EPS or y2 > 1 + OOB_EPS  # tràn mép, dù chỉ một chút
            degenerate = b["w"] <= 0 or b["h"] <= 0  # box rộng/cao âm hoặc bằng 0 cũng không nằm trong ảnh
            if not b["ok"] or outside or degenerate:  # toạ độ hỏng, tràn mép hoặc suy biến
                add(image, "bbox_out_of_bounds")  # ghi lỗi box ngoài ảnh
                break  # một ảnh chỉ cần ghi một lần
        width, height = sizes.get(image, (0, 0))  # kích thước ảnh để đổi sang pixel
        if width and height:  # chỉ kiểm box lặp khi biết kích thước ảnh
            for i in range(len(boxes)):  # duyệt mọi cặp box (i, j)
                for j in range(i + 1, len(boxes)):  # j luôn sau i để không xét một cặp hai lần
                    a, c = boxes[i], boxes[j]  # hai box đang xét
                    if a["cls"] != c["cls"] or not (a["ok"] and c["ok"]):  # khác lớp hoặc toạ độ hỏng
                        continue  # không phải box lặp
                    dw = abs(a["w"] - c["w"]) * width  # chênh lệch chiều rộng (pixel)
                    dh = abs(a["h"] - c["h"]) * height  # chênh lệch chiều cao (pixel)
                    dx = abs(a["xc"] - c["xc"]) * width  # độ lệch tâm theo x (pixel)
                    dy = abs(a["yc"] - c["yc"]) * height  # độ lệch tâm theo y (pixel)
                    if dw <= DUP_SIZE_TOL_PX and dh <= DUP_SIZE_TOL_PX and max(dx, dy) <= DUP_SHIFT_MAX_PX:  # cùng kích thước, lệch 1–2 pixel
                        add(image, "duplicate_box")  # ghi lỗi box lặp
                        break  # thoát vòng j
                if "duplicate_box" in findings.get(image, []):  # đã thấy box lặp
                    break  # thoát vòng i

    # --- 3. Metadata: scene_leak, guideline_mismatch ---
    job_guideline: dict[str, str] = {}  # guideline ghi ở đầu mỗi job
    with (root / "jobs.csv").open(encoding="utf-8", newline="") as f:  # mở jobs.csv
        for row in csv.DictReader(f):  # đọc từng dòng thành dict theo tiêu đề cột
            job_guideline[row["job_id"].strip()] = row["guideline"].strip()  # job_id -> guideline
    meta_items = metadata.get("items", [])  # danh sách ảnh trong metadata
    if isinstance(meta_items, dict):  # phòng khi metadata là dict {tên: thông tin}
        meta_items = [dict(v, image=k) for k, v in meta_items.items()]  # đổi về dạng danh sách
    scene_splits: dict[str, set[str]] = {}  # các split mà mỗi cảnh xuất hiện
    meta_by_image: dict[str, dict] = {}  # metadata theo tên ảnh, dùng lại sau
    for m in meta_items:  # duyệt từng ảnh trong metadata
        image = stem_of(str(m["image"]))  # tên ảnh không đuôi
        meta_by_image[image] = m  # lưu lại
        scene_splits.setdefault(str(m["scene_id"]), set()).add(str(m["split"]))  # gom split theo cảnh
        job = str(m.get("job_id", "")).strip()  # job của ảnh
        gl = str(m.get("guideline_version", "")).strip()  # guideline ghi ở ảnh
        if job in job_guideline and gl != job_guideline[job]:  # guideline của ảnh khác guideline của job
            add(image, "guideline_mismatch")  # ghi lỗi lệch guideline
    for scene, splits in sorted(scene_splits.items()):  # duyệt từng cảnh
        if len(splits) > 1:  # một cảnh có ảnh ở cả train và val
            scene_findings.append({"type": "scene_leak", "target": scene})  # target là scene_id

    # --- 4. Panoptic: invalid_category_id, thing_overlap ---
    categories = {int(c["id"]): c for c in panoptic.get("categories", [])}  # category_id hợp lệ -> thông tin lớp
    masks: dict[str, tuple] = {}  # giữ mask đã đọc để dùng lại khi đối chiếu
    for ann in panoptic.get("annotations", []):  # duyệt annotation của từng ảnh
        image = stem_of(ann["file_name"])  # tên ảnh lấy từ tên file mask
        segs_info = ann.get("segments_info", [])  # danh sách segment khai trong JSON
        if any(int(s["category_id"]) not in categories for s in segs_info):  # category_id không có trong categories
            add(image, "invalid_category_id")  # ghi lỗi lớp panoptic không hợp lệ
        entry = items.get(image, {})  # mục manifest của ảnh (nếu có)
        mask_path = root / entry.get("mask", f"masks/{ann['file_name']}")  # đường dẫn mask
        if not mask_path.is_file():  # thiếu mask
            continue  # không đếm được pixel
        try:  # đọc mask có thể lỗi nếu file hỏng
            mw, mh, segs = read_mask_runs(mask_path)  # đếm pixel từng segment
        except Exception:  # file hỏng hoặc định dạng lạ (zlib, struct, ValueError...)
            continue  # bỏ qua ảnh này (hash sai sẽ được luật wrong_hash bắt)
        masks[image] = (mw, mh, segs)  # lưu để dùng lại
        if image not in sizes:  # panoptic.json không ghi kích thước ảnh
            sizes[image] = (mw, mh)  # lấy kích thước từ mask
        for s in segs_info:  # so từng segment
            real = segs.get(int(s["id"]), {}).get("count", 0)  # số pixel thật của segment trong mask
            if int(s.get("area", 0)) > real:  # area khai nhiều hơn số pixel thật (bị vật khác đè)
                add(image, "thing_overlap")  # ghi lỗi
                break  # một ảnh chỉ cần ghi một lần

    # Gom kết quả: mỗi ảnh mang nhiều nhất một lỗi, nên nếu nhiều luật cùng kêu thì giữ loại
    # theo thứ tự ưu tiên (lỗi file trước, vì nó làm các kiểm tra khác không đáng tin).
    priority = ["missing_image", "invalid_class", "bbox_out_of_bounds", "duplicate_box",
                "invalid_category_id", "thing_overlap", "guideline_mismatch", "wrong_hash"]  # thứ tự ưu tiên
    errors = []  # danh sách lỗi cuối
    for image in sorted(findings):  # duyệt ảnh theo thứ tự tên
        kinds = sorted(findings[image], key=priority.index)  # sắp các lỗi của ảnh theo ưu tiên
        errors.append({"type": kinds[0], "target": image})  # chỉ giữ lỗi ưu tiên nhất
        if len(kinds) > 1:  # có nhiều luật cùng kêu: báo ra stderr để nhóm biết
            print(f"[canh bao] {image}: nhieu luat cung bao {kinds}, giu {kinds[0]}", file=sys.stderr)  # in cảnh báo
    errors.extend(scene_findings)  # thêm lỗi scene_leak

    context = {  # ngữ cảnh dùng lại cho phần đối chiếu
        "items": items, "labels": labels, "masks": masks, "sizes": sizes,
        "panoptic": panoptic, "categories": categories, "flagged": set(findings),
    }
    return errors, context  # trả về lỗi luật và ngữ cảnh


# ---------------------------------------------------------------------------
# Ứng viên lỗi gán nhãn: ghép detection <-> panoptic
# ---------------------------------------------------------------------------
def load_class_names(root: Path) -> dict[int, str]:
    """Đọc classes.txt: mỗi dòng 'class_id tên' (tên có thể có dấu cách)."""
    names = {}  # class_id -> tên lớp
    for line in (root / "classes.txt").read_text(encoding="utf-8").splitlines():  # duyệt từng dòng
        parts = line.strip().split(maxsplit=1)  # tách id và phần tên còn lại
        if len(parts) == 2:  # dòng hợp lệ
            names[int(parts[0])] = parts[1].strip()  # lưu tên
    return names  # trả về bảng tên


def find_candidates(root: Path, ctx: dict) -> list[dict]:
    """Ghép box detection với segment thing của cùng ảnh, sinh ứng viên kèm bằng chứng."""
    det_names = load_class_names(root)  # tên lớp detection
    categories = ctx["categories"]  # category panoptic
    out = []  # danh sách ứng viên
    for ann in ctx["panoptic"].get("annotations", []):  # duyệt từng ảnh panoptic
        image = stem_of(ann["file_name"])  # tên ảnh
        if image in ctx["flagged"]:  # ảnh đã có lỗi luật: mỗi ảnh chỉ một lỗi
            continue  # không sinh ứng viên
        if image not in ctx["masks"] or image not in ctx["labels"]:  # thiếu mask hoặc nhãn
            continue  # không ghép được
        width, height, segs = ctx["masks"][image]  # mask đã đọc ở bước luật
        img_area = width * height  # diện tích ảnh

        # Box detection đổi sang pixel, kèm tên lớp
        boxes = []  # box của ảnh
        for b in ctx["labels"][image]:  # duyệt box
            if b["cls"] in det_names and b["ok"]:  # chỉ lấy box có lớp và toạ độ hợp lệ
                boxes.append({"idx": b["line"], "name": det_names[b["cls"]], "px": box_to_px(b, width, height)})  # lưu box

        # Segment thing (không crowd) có pixel thật trong mask
        things = []  # segment thing
        crowd = []  # segment crowd: COCO vốn không có box riêng cho từng vật trong crowd
        for s in ann.get("segments_info", []):  # duyệt segment khai trong JSON
            cat = categories.get(int(s["category_id"]))  # thông tin lớp
            seg = segs.get(int(s["id"]))  # pixel của segment trong mask
            if cat is None or seg is None or not cat.get("isthing"):  # lớp lạ, không có pixel, hoặc là stuff
                continue  # bỏ qua
            rec = {"id": int(s["id"]), "name": cat["name"], "seg": seg,
                   "bbox": (seg["x1"], seg["y1"], seg["x2"], seg["y2"])}  # bbox lấy từ pixel thật
            (crowd if s.get("iscrowd") else things).append(rec)  # chia vào crowd hoặc thing

        # Ma trận đo giữa mọi box và mọi segment thing
        stats = {}  # (i box, j segment) -> số đo
        for i, b in enumerate(boxes):  # duyệt box
            for j, t in enumerate(things):  # duyệt segment
                ov = iou(b["px"], t["bbox"])  # IoU box với bbox của mask
                if ov <= 0:  # không chạm nhau
                    continue  # bỏ qua cho nhanh
                inside = pixels_in_box(t["seg"], b["px"])  # số pixel segment nằm trong box
                box_area = max(1.0, (b["px"][2] - b["px"][0]) * (b["px"][3] - b["px"][1]))  # diện tích box
                stats[(i, j)] = {"iou": ov, "cover": inside / t["seg"]["count"],  # tỉ lệ pixel segment nằm trong box
                                 "fill": inside / box_area}  # tỉ lệ box được segment lấp

        # Ghép 1-1 cùng lớp, tham lam theo IoU giảm dần
        pairs = sorted(((s["iou"], i, j) for (i, j), s in stats.items()
                        if boxes[i]["name"] == things[j]["name"] and s["iou"] >= MATCH_IOU), reverse=True)  # cặp cùng lớp đủ IoU
        box_match: dict[int, int] = {}  # box -> segment đã ghép
        seg_match: dict[int, int] = {}  # segment -> box đã ghép
        for _, i, j in pairs:  # duyệt cặp từ tốt nhất
            if i not in box_match and j not in seg_match:  # cả hai chưa được ghép
                box_match[i], seg_match[j] = j, i  # ghép

        found = []  # ứng viên của ảnh này
        used_seg: set[int] = set()  # segment đã được giải thích bởi một ứng viên
        used_box: set[int] = set()  # box đã được giải thích bởi một ứng viên

        def emit(kind, score, evidence, options=None):  # hàm phụ: thêm một ứng viên
            found.append({"image": image, "type": kind, "type_options": options or [kind],
                          "score": round(score, 3), "evidence": evidence})  # lưu ứng viên

        # (a) Gộp vật: một segment có pixel nằm trong >= 2 box cùng lớp, và các box đó không có segment riêng
        for j, t in enumerate(things):  # duyệt segment
            hits = [i for i in range(len(boxes))
                    if (i, j) in stats and boxes[i]["name"] == t["name"]
                    and stats[(i, j)]["cover"] >= MERGE_SHARE and stats[(i, j)]["fill"] >= MERGE_FILL
                    and box_match.get(i, j) == j]  # box cùng lớp chứa nhiều pixel segment, chưa ghép với segment khác
            if len(hits) < 2:  # cần ít nhất hai box
                continue  # không phải gộp
            share = sum(stats[(i, j)]["cover"] for i in hits)  # tổng tỉ lệ pixel segment nằm trong các box đó
            if share < MERGE_TOTAL:  # các box không giải thích được phần lớn segment
                continue  # không phải gộp
            emit("instance_merge", min(1.0, share / 2 + 0.5), {"class": t["name"], "segment_id": t["id"],
                 "box_lines": [boxes[i]["idx"] for i in hits],
                 "share_per_box": [round(stats[(i, j)]["cover"], 3) for i in hits]})  # ghi bằng chứng
            used_seg.add(j)  # segment đã được giải thích
            used_box.update(hits)  # các box đã được giải thích

        # (b) Cặp đã ghép cùng lớp nhưng một phần pixel rơi ra ngoài box -> bbox_drift
        for i, j in box_match.items():  # duyệt cặp đã ghép
            if i in used_box or j in used_seg:  # đã giải thích ở bước gộp
                continue  # bỏ qua
            s = stats[(i, j)]  # số đo của cặp
            if s["cover"] < DRIFT_COVER:  # box khớp với vật thì gần như 100% pixel nằm trong box
                emit("bbox_drift", 1 - s["cover"], {"box_line": boxes[i]["idx"], "class": boxes[i]["name"],
                     "segment_id": things[j]["id"], "cover": round(s["cover"], 3), "iou": round(s["iou"], 3)})  # ghi bằng chứng
                used_seg.add(j)  # segment đã được giải thích
                used_box.add(i)  # box đã được giải thích

        # (c) Box chưa ghép: thử giải thích theo thứ tự đổi lớp -> lệch mạnh
        for i, b in enumerate(boxes):  # duyệt box
            if i in box_match or i in used_box:  # box đã ghép hoặc đã được giải thích
                continue  # bỏ qua
            # Đổi lớp: segment khác lớp, chưa ghép, trùng vị trí rất sát
            best = max(((stats[(i, j)]["iou"], j) for j in range(len(things))
                        if (i, j) in stats and j not in seg_match and j not in used_seg
                        and things[j]["name"] != b["name"]), default=(0.0, None))  # segment khác lớp có IoU cao nhất
            if best[1] is not None and best[0] >= SWAP_IOU:  # đủ sát để coi là cùng một vật
                j = best[1]  # segment đó
                emit("class_swap", best[0], {"box_line": b["idx"], "det_class": b["name"],
                     "segment_id": things[j]["id"], "pan_class": things[j]["name"], "iou": round(best[0], 3),
                     "hint": "mo anh: vat dung la pan_class -> class_swap; vat dung la det_class -> category_swap"},
                     options=["class_swap", "category_swap"])  # chưa biết bên nào sai, cần xem ảnh
                used_seg.add(j)  # segment đã được giải thích
                used_box.add(i)  # box đã được giải thích
                continue  # sang box khác
            # Lệch mạnh: segment cùng lớp chưa ghép, có chạm box nhưng IoU dưới ngưỡng ghép
            drift = max(((stats[(i, j)]["iou"], j) for j in range(len(things))
                         if (i, j) in stats and j not in seg_match and j not in used_seg
                         and things[j]["name"] == b["name"]), default=(0.0, None))  # segment cùng lớp gần nhất
            if drift[1] is not None:  # có segment cùng lớp chạm box
                j = drift[1]  # segment đó
                emit("bbox_drift", 1 - stats[(i, j)]["cover"], {"box_line": b["idx"], "class": b["name"],
                     "segment_id": things[j]["id"], "cover": round(stats[(i, j)]["cover"], 3),
                     "iou": round(drift[0], 3)})  # ghi bằng chứng
                used_seg.add(j)  # segment đã được giải thích
                used_box.add(i)  # box đã được giải thích
            # Box không giải thích được (không có segment nào): thường là lệch tự nhiên của COCO, không báo

        # (d) Segment thing đáng kể không có box -> missing_box (hoặc box bị lệch sang chỗ khác)
        for j, t in enumerate(things):  # duyệt segment
            if j in seg_match or j in used_seg:  # đã ghép hoặc đã được giải thích
                continue  # bỏ qua
            if t["seg"]["count"] < max(MISSING_MIN_PX, MISSING_MIN_FRAC * img_area):  # vật nhỏ, không "đáng kể"
                continue  # bỏ qua
            covered = max((stats[(i, j)]["cover"] for i in range(len(boxes))
                           if (i, j) in stats and boxes[i]["name"] == t["name"]), default=0.0)  # phần segment đã nằm trong box cùng lớp
            if covered >= DRIFT_COVER:  # segment nằm gọn trong một box cùng lớp (vật bị che, box của vật lớn hơn)
                continue  # không phải thiếu box
            options = ["missing_box", "bbox_drift"] if covered >= 0.1 else ["missing_box"]  # có box cùng lớp chạm một phần: có thể là box lệch
            emit("missing_box", (1 - covered) * min(1.0, t["seg"]["count"] / (0.02 * img_area)),
                 {"segment_id": t["id"], "class": t["name"], "pixels": t["seg"]["count"],
                  "bbox_px": list(t["bbox"]), "best_same_class_cover": round(covered, 3)}, options=options)  # ghi bằng chứng

        # Mỗi ảnh mang nhiều nhất một lỗi: giữ mọi ứng viên để người xem, nhưng sắp theo điểm
        found.sort(key=lambda c: -c["score"])  # ứng viên mạnh nhất lên đầu
        for rank, c in enumerate(found):  # đánh dấu thứ hạng trong ảnh
            c["rank_in_image"] = rank  # 0 là ứng viên mạnh nhất của ảnh
        out.extend(found)  # gộp vào kết quả chung
    out.sort(key=lambda c: (c["rank_in_image"], -c["score"], c["image"]))  # hàng đợi: ứng viên mạnh nhất mỗi ảnh trước
    return out  # trả về danh sách ứng viên


def main() -> int:
    """Điểm vào: đọc tham số, chạy luật, ghi errors.json và (tuỳ chọn) candidates.json."""
    try:  # Windows console có thể không in được UTF-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ép stdout sang UTF-8
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # ép stderr sang UTF-8
    except AttributeError:  # Python cũ không có reconfigure
        pass  # bỏ qua
    ap = argparse.ArgumentParser(description="Validator lo delivery (detection + panoptic)")  # bộ đọc tham số
    ap.add_argument("delivery", help="thu muc delivery")  # tham số vị trí: thư mục delivery
    ap.add_argument("--out", required=True, help="file errors.json (chi loi luat)")  # nơi ghi lỗi luật
    ap.add_argument("--candidates", help="file candidates.json (ung vien loi gan nhan)")  # nơi ghi ứng viên (tuỳ chọn)
    args = ap.parse_args()  # đọc tham số

    root = Path(args.delivery)  # thư mục delivery
    if not (root / "manifest.json").is_file():  # không phải thư mục delivery hợp lệ
        print(f"Khong thay manifest.json trong {root}", file=sys.stderr)  # báo lỗi
        return 2  # mã lỗi

    errors, ctx = check_rules(root)  # chạy 9 luật
    out_path = Path(args.out)  # đường dẫn errors.json
    out_path.parent.mkdir(parents=True, exist_ok=True)  # tạo thư mục cha nếu chưa có
    out_path.write_text(json.dumps({"errors": errors}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")  # ghi errors.json
    counts: dict[str, int] = {}  # đếm lỗi theo loại để in tóm tắt
    for e in errors:  # duyệt lỗi
        counts[e["type"]] = counts.get(e["type"], 0) + 1  # cộng dồn
    print(f"{len(errors)} loi luat -> {out_path}: {dict(sorted(counts.items()))}")  # in tóm tắt

    if args.candidates:  # có yêu cầu ghi ứng viên
        cands = find_candidates(root, ctx)  # sinh ứng viên
        c_path = Path(args.candidates)  # đường dẫn candidates.json
        c_path.parent.mkdir(parents=True, exist_ok=True)  # tạo thư mục cha
        c_path.write_text(json.dumps({"candidates": cands}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")  # ghi file
        per_type: dict[str, int] = {}  # đếm ứng viên theo loại
        for c in cands:  # duyệt ứng viên
            per_type[c["type"]] = per_type.get(c["type"], 0) + 1  # cộng dồn
        n_img = len({c["image"] for c in cands})  # số ảnh cần mở
        print(f"{len(cands)} ung vien tren {n_img} anh -> {c_path}: {dict(sorted(per_type.items()))}")  # in tóm tắt
    return 0  # thành công


if __name__ == "__main__":  # chạy trực tiếp
    raise SystemExit(main())  # gọi main và trả mã thoát
