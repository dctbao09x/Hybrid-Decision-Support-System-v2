# Data Mapping & Normalization Rules

## 1. Salary Normalization
Mục tiêu: Chuyển đổi text sang range `[min, max]` (VND).

| Input Pattern | Logic | Example | Result (Min, Max) |
|---|---|---|---|
| `X - Y Triệu` | `X * 1M`, `Y * 1M` | "10 - 15 Triệu" | 10.000.000, 15.000.000 |
| `Tới X Triệu` | `0`, `X * 1M` | "Tới 20 Triệu" | 0, 20.000.000 |
| `Trên X Triệu` | `X * 1M`, `0` (unlimited) | "Trên 15 Triệu" | 15.000.000, 0 |
| `X - Y USD` | `X * 25k`, `Y * 25k` | "1000 - 2000 USD" | 25.000.000, 50.000.000 |
| `Thỏa thuận` | `0`, `0` | "Thỏa thuận" | 0, 0 |

## 2. Location Mapping
Mục tiêu: Gom nhóm địa điểm về mã tỉnh/thành phố chuẩn.

| Input Keyword (Case insensitive, Unidecode) | Province Code |
|---|---|
| ho chi minh, hcm, sai gon | `SG` |
| ha noi | `HN` |
| da nang | `DN` |
| binh duong | `BD` |
| remote, online | `REMOTE` |
| *Others* | `OTHER` |

## 3. Title Canonicalization
Mục tiêu: Chuẩn hóa để matching rule engine dễ dàng hơn.

*   Lowercase toàn bộ.
*   Loại bỏ ký tự đặc biệt (chỉ giữ alphanumeric và space).
*   Trim space thừa.

Example: `Senior Python Developer (HCM)` -> `senior python developer hcm`

## 4. Expiration Logic
*   Parse `posted_date` từ text (relative "2 ngày trước" hoặc absolute "12/05/2024").
*   Nếu `(Current Date - Posted Date) > 30 days` -> Flag `is_expired = True`.