# Bảo mật khi làm việc với lô seed 36

## 1. Ca USB khi hết giờ

Nếu còn việc kiểm tra lô `lab250_6112a1fce312`, lưu tiến độ trong CVAT hoặc thư mục dự án được cấp quyền rồi báo người phụ trách để sắp lịch làm tiếp. Chép lô ra USB, gửi qua email cá nhân hoặc nhờ người ngoài quyền truy cập làm hộ đưa ảnh và nhãn ra khỏi phạm vi kiểm soát. Khi cần làm từ xa, dùng máy và kênh truy cập do dự án phê duyệt.

## 2. Năm việc được hoặc không được làm

- **Được** mở job được giao trên máy công ty bằng tài khoản cá nhân đã được cấp quyền. Hệ thống ghi nhận ai đã truy cập và làm gì trên job.
- **Không được** chụp màn hình gửi người quen vì ảnh, nhãn và thông tin job có thể lộ ra ngoài nhóm được cấp quyền.
- **Không được** chép lô ra USB cá nhân vì ổ có thể thất lạc và bản sao nằm ngoài phạm vi quản lý của dự án.
- **Không được** dán nhãn thật của dự án vào chatbot chưa được phê duyệt vì dịch vụ có thể lưu nội dung đã gửi.
- **Không được** đưa tài khoản CVAT cho đồng nghiệp. Người tiếp nhận cần được cấp quyền riêng để thao tác được ghi đúng người.

## 3. Ca khuôn mặt khi guideline yêu cầu làm mờ

Ảnh `000000008532.jpg` trong lô seed 36 có khuôn mặt nhìn rõ. Nếu guideline của dự án yêu cầu làm mờ mà phát hiện một ảnh như vậy, đặt lô ở trạng thái **Hold**, dừng bàn giao và báo người phụ trách dữ liệu qua kênh nội bộ. Ghi mã lô, tên ảnh và mục guideline liên quan vào ticket để người có quyền xử lý và kiểm lại. Việc tự làm mờ hoặc xóa ảnh sẽ thay đổi dữ liệu, ảnh hưởng đến nhãn và hash. Sau khi xử lý theo quy trình, kiểm lại ảnh, nhãn và manifest trước khi bàn giao bản đã sửa.
