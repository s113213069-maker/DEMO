# 投稿審查系統

## 使用方式

1. 解壓縮專案資料夾。
2. 點開「啟動系統.bat」，等待程式執行完成，直到畫面顯示 Uvicorn 已在 `http://0.0.0.0:8000` 啟動。
3. 開啟瀏覽器，在網址列輸入：

   `http://127.0.0.1:8000`

4. 使用完畢後，回到啟動系統的視窗，按 `Ctrl + C` 停止系統。

第一次啟動時，批次檔會自動建立 Python 虛擬環境並安裝所需套件，請保持網路連線並稍候。

## 使用技術

- **前端：** HTML5、CSS3、JavaScript、Jinja2 Templates
- **後端：** Python、FastAPI、Uvicorn
- **資料庫：** SQLite、Python sqlite3
- **登入與工作階段：** Starlette SessionMiddleware
- **密碼處理：** Werkzeug Password Hashing
