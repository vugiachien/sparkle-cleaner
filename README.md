# Sparkle Cleaner

Gỡ dấu sparkle (ngôi sao 4 cánh) của Gemini/Imagen khỏi ảnh, hàng loạt, có giao diện.
**macOS** có bộ cài `.dmg`; **Windows** thì chép nguyên thư mục sang là chạy, kể
cả khi máy đó không có mạng. Người dùng không cần biết gì về Python.

## Cài đặt

### macOS — file `.dmg`

1. Mở `SparkleCleaner-1.0.0-macOS.dmg`, kéo **Sparkle Cleaner** vào **Applications**.
2. Lần đầu mở, macOS sẽ chặn vì app chưa được Apple ký (cần tài khoản nhà phát
   triển trả phí). Mở một lần cho nó báo lỗi, rồi vào **System Settings → Privacy &
   Security**, cuộn xuống cuối, nhấn **Open Anyway** và xác nhận. Chỉ phải làm một
   lần. Cách khác: mở Terminal chạy `xattr -cr "/Applications/Sparkle Cleaner.app"`.
3. Toàn bộ thư viện đã nằm sẵn trong app: không cần mạng, không cần cài Python.
   Bản này dựng cho Mac chip Apple (M1 trở lên).

### Windows — chép thư mục rồi chạy, không cần mạng

Cách khuyến nghị để đưa tool sang máy Windows bằng USB, kể cả cho người không
rành máy tính.

**Chuẩn bị một lần, trên máy có mạng** (Mac, Linux hay Windows đều được):

```
python3 tools/fetch_windows_runtime.py
```

Lệnh này tải Python nhúng cho Windows và toàn bộ thư viện bản Windows (19
wheel, tổng 182 MB) vào thư mục `win-runtime/`. Nó tự dò và bổ sung cả các gói
mà **chỉ Windows mới cần** — ví dụ `colorama` mà `tqdm` đòi — rồi mới dừng;
`pip download --platform` một mình không làm được việc đó vì nó vẫn xét điều
kiện `platform_system` theo máy đang chạy.

**Đóng gói phần đi USB** (thư mục dự án đầy đủ nặng hơn 1 GB vì có `.venv`,
`dist`, `build` — toàn đồ của máy Mac, máy Windows không dùng):

```
python3 tools/fetch_windows_runtime.py --stage ~/Desktop/sparkle-win
```

Được một thư mục 183 MB gồm đúng những gì cần. Chép nó vào USB.

**Trên máy Windows:**

1. Chép **nguyên thư mục đó** (kèm cả `win-runtime/`) từ USB vào ổ C: hoặc
   ra Desktop. Đừng chạy thẳng trên USB: lần đầu chạy phải ghi khoảng 400 MB
   xuống cùng thư mục, chạy trên USB vừa rất chậm vừa hỏng nếu USB chống ghi.
2. Nhấn đúp `Sparkle Cleaner.bat`. Lần đầu hiện một cửa sổ đen chừng một phút
   để tự cài — **không cần mạng, không cần quyền admin, không cần cài Python
   trước**. Cài xong nó chạy `--selftest`, đạt rồi mới mở giao diện.
3. Các lần sau mở thẳng, không phải chờ.

Chép kèm file `HUONG DAN - Windows.txt` — đó là bản hướng dẫn viết sẵn cho
người dùng cuối.

Máy đích cần Windows 10 trở lên, 64-bit. **Không** cần cài "Visual C++
Redistributable": bộ Python nhúng kèm sẵn `vcruntime140.dll`, còn numpy/scipy
kèm `msvcp140.dll` trong thư mục `.libs` của chúng.

Nếu thư mục `win-runtime/` không có, file `.bat` tự chuyển sang nhánh dự phòng:
tải Python và thư viện từ Internet (~250 MB, cần mạng).

### Windows — file `Setup.exe`

Bộ cài NSIS cũ vẫn còn (`bash tools/build_windows_installer.sh`). Nó chỉ chép
mã nguồn rồi để file `.bat` tải Python và thư viện từ mạng lúc cài, nên không
dùng được offline — với kịch bản USB hãy dùng cách ở trên.

### Chạy từ mã nguồn (cho người muốn sửa code)

- **macOS**: chuột phải `Sparkle Cleaner.command` → Open. Cần Python 3.10+; lần đầu
  tự tạo `.venv` và cài thư viện (1–3 phút).
- **Windows**: nhấn đúp `Sparkle Cleaner.bat`. Không cần Python sẵn: nó dựng một
  bộ Python nhúng riêng trong thư mục `python` cạnh đó — lấy từ `win-runtime/`
  nếu có (offline), không thì tải từ mạng. Muốn xem lỗi thì chạy
  `"Sparkle Cleaner.bat" --selftest`.

Nếu app không mở được, xem file lỗi: `~/Library/Logs/Sparkle Cleaner/error.log`
(macOS) hoặc `%LOCALAPPDATA%\Sparkle Cleaner\error.log` (Windows).

### Tự dựng bộ cài

- **macOS `.dmg`** (chạy trên Mac đã có `.venv`): `bash tools/build_macos.sh`
  → `dist/SparkleCleaner-<phiên bản>-macOS.dmg`. Script dùng PyInstaller gói toàn
  bộ Python + thư viện vào `.app`, chạy `--selftest` đạt rồi mới đóng `.dmg`.
- **Windows offline** (dựng được ngay trên Mac): `python3 tools/fetch_windows_runtime.py`
  → `win-runtime/`. Chép cả thư mục dự án đi là chạy được, không cần mạng.
- **Windows `Setup.exe`** (dựng được ngay trên Mac): cần NSIS 3
  (`brew install makensis`), rồi `bash tools/build_windows_installer.sh`
  → `dist/SparkleCleaner-<phiên bản>-Setup.exe`. Bộ cài nhỏ (~1 MB) vì Python và
  thư viện được tải về lúc cài.
- Kiểm tra nhanh một bản cài bất kỳ: chạy app với tham số `--selftest`, phải in `OK`.

## Dùng

**1 · Nguồn ảnh** — kéo thẳng vào ô, hoặc dùng nút:

| Nguồn | Cách đưa vào |
| --- | --- |
| Ảnh lẻ | Kéo vào, hoặc *Thêm ảnh…* |
| Thư mục | Kéo vào — tự quét cả thư mục con |
| File ZIP | Kéo vào — tự giải nén, chỉ lấy ảnh |
| Google Drive | *Thêm link Drive…* rồi dán link — nhận thư mục, ảnh lẻ hoặc **file ZIP** (tự tải về và giải nén) |

Link Drive phải ở chế độ **"Bất kỳ ai có đường liên kết"**. Dạng link nào cũng
được: `…/drive/folders/ID`, `…/file/d/ID/view?usp=sharing`, `…/open?id=ID`.
Tool chỉ tải xuống, không ghi ngược lên Drive — kết quả nằm ở thư mục bạn chọn.

**2 · Nơi lưu** — chọn thư mục đích, hoặc "đặt cạnh ảnh gốc". Ảnh gốc không bao
giờ bị ghi đè: kết quả luôn có hậu tố (mặc định `_clean`), và nếu tên đã tồn tại
thì tự thêm `-1`, `-2`.

**3 · Tuỳ chọn**

- **Độ nhạy** — *Chặt* chỉ gỡ khi chắc chắn; *Nhạy* bắt cả dấu mờ nhưng tăng
  rủi ro nhận nhầm. Cứ để *Cân bằng*.
- **Bù vân hạt** — nên bật. JPEG làm bệt vân bề mặt dưới chỗ có dấu; bước này
  vay vân hạt từ vùng sạch gần đó đắp lại, nếu không vùng vừa gỡ sẽ hơi mịn
  khác xung quanh.
- **Xoá metadata** — bỏ EXIF/C2PA khi ghi file.
- **Số luồng** — mặc định đã đặt theo số nhân máy bạn.

**Nhật ký** ghi từng ảnh: gỡ được thì in luôn toạ độ, bán kính, độ phủ và độ
khớp mô hình. Nút *Lưu nhật ký…* xuất ra file text.

## Cách nó hoạt động

Dấu sparkle không phải logo đục đè — nó là **lớp trắng phủ bán trong suốt**
(độ phủ ~0.27) theo hình astroid. Nên thay vì vá đè (inpaint), vốn xoá luôn chi
tiết thật nằm dưới, tool **giải ngược phép trộn**:

```
quan sát = (1 − a) × gốc + a × 255   →   gốc = (quan sát − 255a) / (1 − a)
```

Nhờ vậy mọi đường nét, mạch vữa, vân bề mặt dưới dấu được khôi phục nguyên vẹn
thay vì bị bôi mờ.

Dò tìm chạy hai tầng: tương quan đa tỉ lệ để đề cử ứng viên, rồi bốn phép kiểm
định để loại nhiễu — vị trí phải sát góc dưới phải, lớp phủ phải nổi rõ trên
nền, **bốn khe lõm của hình sao phải là nền sạch** (đây là thứ loại được giọt
nước và ánh kim tròn), và cuối cùng mô hình astroid phải khớp dữ liệu với
R² ≥ 0.65.

Dấu Gemini đời mới có **hai sao**: sao lớn và một sao nhỏ chếch dưới-trái. Tool
tìm sao lớn trước, rồi dò sao nhỏ trong vùng đó; thấy thì khớp lại sao lớn với
sao nhỏ đã loại khỏi nền, và gỡ cả hai cùng lúc. Không thấy sao nhỏ thì xử lý
như dấu một sao cũ.

Bốn cổng chặn báo nhầm, rút ra từ đặc điểm bất biến của dấu:

- **Vị trí** — tâm dấu cách mép phải không quá 12% chiều rộng và cách mép dưới
  không quá 22% chiều cao. Phần lớn thứ bị nhận nhầm nằm giữa ảnh.
- **Màu** — lớp phủ là *trắng*, nên độ phủ tính riêng cho R, G, B phải xấp xỉ
  nhau (lệch dưới 0.12). Ngón tay, mặt gỗ, ánh đèn ấm đều lệch từ 0.15 trở lên.
  Trên ảnh xám chúng khớp hình sao rất tốt; chỉ màu mới phân biệt được.
- **Hình dạng** — gần tròn (tỉ lệ 0.65–1.55) và cạnh lõm rõ (số mũ ≤ 0.90).
- **Viền** — biên phải sắc (≤ 0.42). Dấu thật chuyển tiếp trong một hai pixel.

Ảnh nào không được nhận, chạy lệnh sau để xem từng bước vì sao bị loại:

```
python -m sparkle_cleaner --explain duong/dan/anh.jpg
```

## Đã kiểm thử

**Trên ảnh thật.** Quét hai thư mục ảnh do AI sinh trên máy, tổng 946 ảnh:

| Tập | Số ảnh | Nhận có dấu | Kiểm tra bằng mắt |
| --- | --- | --- | --- |
| Thư viện A (không có dấu) | 546 | 0 | — |
| Thư viện B | 400 | 22 | **22/22 đúng là dấu thật, 0 báo nhầm** |

Thư viện B là tập độc lập, không dùng để chỉnh ngưỡng. Trước khi siết bốn cổng
nói trên, cùng thư viện A cho **16 báo nhầm** — mép gỗ, nếp quần, bánh xe, cổ
tay áo, quân hàm, và một ngón tay bị "gỡ" thành vệt nâu đỏ. Đó là lý do các cổng
này tồn tại.

Đo mức gỡ trên một dấu thật nằm trên nền đen thuần (dễ đo nhất): chênh lệch so
với nền giảm từ 66,9 mức xám xuống 1,0 — gỡ được **98,5%**. Phần còn lại là một
vành mảnh chỉ thấy khi phóng to trên nền phẳng tuyệt đối.

**Trên ảnh tự tạo.** 5 loại nền × 3 kích thước × 3 độ phủ, mỗi tổ hợp dựng ba
phiên bản (một sao, hai sao, ảnh sạch), đều qua nén JPEG:

| Chỉ số | Bản một sao | Bản hiện tại |
| --- | --- | --- |
| Nhận dấu một sao | 17/45 | 17/45 |
| Nhận dấu hai sao | 5/45 | 18/45 |
| Nhận đủ cả hai sao | 4/45 | 16/45 |
| Báo nhầm trên ảnh sạch | 1/45 | 0/45 |

Ảnh không nhận được thì tool **giữ nguyên file** và ghi rõ trong nhật ký. Bộ nền
này cố tình nhiễu rất mạnh nên tỉ lệ nhận thấp hơn hẳn ảnh thật.

Tốc độ dò trên Mac mini M4, đo trực tiếp: 0,4 giây với ảnh 900×560, 1,8 giây
với ảnh 2000×1250, 2,4 giây với ảnh 4K. Bước tìm sao nhỏ không làm chậm thêm.
Chạy 6 luồng song song.

## Giới hạn cần biết

Tool chỉ gỡ **dấu nhìn thấy được**. Ảnh Gemini/Imagen còn mang **SynthID nhúng
trong pixel** — vô hình, phân tán khắp ảnh, sống sót qua thao tác này. Công cụ
kiểm tra của Google vẫn nhận ra ảnh do AI tạo. Không có cách nào gỡ phần đó mà
không cần GPU NVIDIA, và kể cả có cũng không ai xác nhận được là sạch.

Phần tải Google Drive (kể cả tải ZIP rồi giải nén) được viết theo API của
`gdown` và đã kiểm thử bằng gdown giả lập, nhưng chưa chạy thử với link thật
(môi trường dựng tool chặn Drive). Nếu gặp lỗi, gửi tôi dòng báo lỗi trong
nhật ký.

Phần Windows được dựng trên Mac và **chưa chạy thử trên máy Windows thật**.
Những gì đã kiểm chứng được từ máy Mac: bộ 19 wheel đúng là bản
`win_amd64`/`cp312` và đã đủ phụ thuộc; giải nén chúng vào `site-packages` cho
ra đủ `PySide6`, `cv2`, `numpy`, `scipy`, `PIL`, `gdown` kèm các file `.dll`
và `.pyd` của Windows; file `._pth` sinh ra không lẫn ký tự thừa; file `.bat`
toàn ASCII, xuống dòng CRLF, mọi nhãn `goto` đều có đích. Những gì **không**
kiểm chứng được nếu không có máy Windows: cmd.exe chạy đúng file `.bat`,
`pythonw.exe` đẻ tiến trình con qua `ProcessPoolExecutor`, và Qt vẽ giao diện.

Bước `--selftest` chạy tự động ngay sau khi cài chính là để bắt ba thứ đó — nó
nạp đủ thư viện, xử lý thử một ảnh **qua một tiến trình con thật**, rồi dựng và
đóng cửa sổ. Không đạt là báo ngay tại chỗ; chụp lại cửa sổ đó gửi tôi.
