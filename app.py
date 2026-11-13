from datetime import datetime
import os
import sqlite3
import hashlib
from fastapi.responses import JSONResponse

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "submission_review.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-key-before-deployment")

app = FastAPI(title="投稿審查系統")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('author', 'editor'))
        );
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '編輯中'
                CHECK(status IN ('編輯中', '審查中', '已通過')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            submitted_at TEXT,
            reviewed_at TEXT,
            FOREIGN KEY(author_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS review_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            reviewer_id INTEGER NOT NULL,
            decision TEXT NOT NULL CHECK(decision IN ('approve', 'return')),
            decided_at TEXT NOT NULL,
            FOREIGN KEY(submission_id) REFERENCES submissions(id) ON DELETE CASCADE,
            FOREIGN KEY(reviewer_id) REFERENCES users(id)
        );
        """)
        for username, password, display_name, role in [
            ("author", "1234", "示範作者", "author"),
            ("editor", "1234", "示範編輯", "editor"),
        ]:
            if not db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
                db.execute("INSERT INTO users(username,password_hash,display_name,role) VALUES(?,?,?,?)",
                           (username, generate_password_hash(password), display_name, role))


def dashboard_version(request):
    role = request.session.get("role")
    user_id = request.session.get("user_id")
    with get_db() as db:
        if role == "author":
            rows = db.execute(
                "SELECT id, status, updated_at FROM submissions WHERE author_id=? ORDER BY id",
                (user_id,),
            ).fetchall()
        elif role == "editor":
            rows = db.execute(
                "SELECT id, status, updated_at FROM submissions ORDER BY id"
            ).fetchall()
        else:
            rows = []
    payload = "|".join(f"{row['id']}:{row['status']}:{row['updated_at']}" for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def page(request, template, **context):
    messages = request.session.pop("_flashes", [])
    sync_enabled = template in {"author_dashboard.html", "editor_dashboard.html", "approved_submissions.html"}
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "request": request,
            "session": request.session,
            "current_year": datetime.now().year,
            "messages": messages,
            "sync_enabled": sync_enabled,
            "sync_version": dashboard_version(request) if sync_enabled and request.session.get("user_id") else "",
            **context,
        },
    )


def flash(request, message, category="info"):
    request.session.setdefault("_flashes", []).append((category, message))


def require_role(request, role=None):
    if not request.session.get("user_id"):
        flash(request, "請先登入系統。", "warning")
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    if role and request.session.get("role") != role:
        raise HTTPException(status_code=403, detail="你沒有權限使用此功能。")


def go(path):
    return RedirectResponse(path, status_code=303)




@app.get("/favicon.ico")
def favicon():
    return HTMLResponse(status_code=204)

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not request.session.get("user_id"):
        return go("/login")
    return go("/editor" if request.session.get("role") == "editor" else "/author")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return page(request, "login.html")


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    username, password = str(form.get("username", "")).strip(), str(form.get("password", ""))
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if user and check_password_hash(user["password_hash"], password):
        request.session.clear()
        request.session.update(user_id=user["id"], username=user["username"],
                               display_name=user["display_name"], role=user["role"])
        flash(request, f"歡迎回來，{user['display_name']}！", "success")
        return go("/")
    flash(request, "帳號或密碼錯誤，請重新輸入。", "danger")
    return go("/login")


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return page(request, "register.html")


@app.post("/register")
async def register(request: Request):
    form = await request.form()
    username = str(form.get("username", "")).strip()
    display_name = str(form.get("display_name", "")).strip()
    password, confirm = str(form.get("password", "")), str(form.get("confirm", ""))
    if not username or not display_name or not password:
        flash(request, "所有欄位皆為必填。", "danger")
    elif len(password) < 4:
        flash(request, "密碼至少需要 4 個字元。", "danger")
    elif password != confirm:
        flash(request, "兩次輸入的密碼不一致。", "danger")
    else:
        try:
            with get_db() as db:
                db.execute("INSERT INTO users(username,password_hash,display_name,role) VALUES(?,?,?,'author')",
                           (username, generate_password_hash(password), display_name))
            flash(request, "作者帳號建立成功，請登入。", "success")
            return go("/login")
        except sqlite3.IntegrityError:
            flash(request, "此帳號已有人使用，請更換帳號名稱。", "danger")
    return go("/register")


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return go("/login")


@app.get("/author", response_class=HTMLResponse)
def author_dashboard(request: Request):
    require_role(request, "author")
    with get_db() as db:
        rows = db.execute("SELECT * FROM submissions WHERE author_id=? ORDER BY updated_at DESC",
                           (request.session["user_id"],)).fetchall()
    return page(request, "author_dashboard.html", submissions=rows)


@app.get("/submission/new", response_class=HTMLResponse)
def new_submission_page(request: Request):
    require_role(request, "author")
    return page(request, "submission_form.html", submission=None)


@app.post("/submission/new")
async def new_submission(request: Request):
    require_role(request, "author")
    form = await request.form()
    category, title, content = [str(form.get(k, "")).strip() for k in ("category", "title", "content")]
    if not category or not title or not content:
        flash(request, "類別、標題及文章內容皆不可空白。", "danger")
        return go("/submission/new")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as db:
        db.execute("""INSERT INTO submissions(author_id,category,title,content,status,created_at,updated_at)
                      VALUES(?,?,?,?,'編輯中',?,?)""",
                   (request.session["user_id"], category, title, content, now, now))
    flash(request, "稿件已儲存為「編輯中」。", "success")
    return go("/author")


@app.get("/submission/{submission_id}/edit", response_class=HTMLResponse)
def edit_submission_page(request: Request, submission_id: int):
    require_role(request, "author")
    with get_db() as db:
        row = db.execute("SELECT * FROM submissions WHERE id=? AND author_id=?",
                         (submission_id, request.session["user_id"])).fetchone()
    if not row:
        raise HTTPException(404, "找不到稿件")
    if row["status"] != "編輯中":
        flash(request, "只有「編輯中」的稿件可以修改。", "warning")
        return go("/author")
    return page(request, "submission_form.html", submission=row)


@app.post("/submission/{submission_id}/edit")
async def edit_submission(request: Request, submission_id: int):
    require_role(request, "author")
    form = await request.form()
    category, title, content = [str(form.get(k, "")).strip() for k in ("category", "title", "content")]
    if not category or not title or not content:
        flash(request, "類別、標題及文章內容皆不可空白。", "danger")
        return go(f"/submission/{submission_id}/edit")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as db:
        result = db.execute("""UPDATE submissions SET category=?,title=?,content=?,updated_at=?
                               WHERE id=? AND author_id=? AND status='編輯中'""",
                            (category, title, content, now, submission_id, request.session["user_id"]))
    flash(request, "稿件修改完成。" if result.rowcount else "稿件不存在或已送出，無法修改。",
          "success" if result.rowcount else "warning")
    return go("/author")


@app.post("/submission/{submission_id}/delete")
def delete_submission(request: Request, submission_id: int):
    require_role(request, "author")
    with get_db() as db:
        result = db.execute("DELETE FROM submissions WHERE id=? AND author_id=? AND status='編輯中'",
                            (submission_id, request.session["user_id"]))
    flash(request, "編輯中的稿件已刪除。" if result.rowcount else "找不到稿件，或稿件已送出而不可刪除。",
          "success" if result.rowcount else "warning")
    return go("/author")


@app.post("/submission/{submission_id}/submit")
def submit_submission(request: Request, submission_id: int):
    require_role(request, "author")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as db:
        result = db.execute("""UPDATE submissions SET status='審查中',submitted_at=?,updated_at=?
                               WHERE id=? AND author_id=? AND status='編輯中'""",
                            (now, now, submission_id, request.session["user_id"]))
    flash(request, "投稿成功，稿件已送交編輯審查。" if result.rowcount else "無法送出，請確認稿件狀態。",
          "success" if result.rowcount else "warning")
    return go("/author")


@app.get("/editor", response_class=HTMLResponse)
def editor_dashboard(request: Request):
    require_role(request, "editor")
    with get_db() as db:
        rows = db.execute("""SELECT s.*,u.display_name AS author_name FROM submissions s
                             JOIN users u ON s.author_id=u.id WHERE s.status='審查中'
                             ORDER BY s.submitted_at ASC""").fetchall()
        counts = {
            "pending": db.execute("SELECT COUNT(*) FROM submissions WHERE status='審查中'").fetchone()[0],
            "approved": db.execute("SELECT COUNT(*) FROM submissions WHERE status='已通過'").fetchone()[0],
            "draft": db.execute("SELECT COUNT(*) FROM submissions WHERE status='編輯中'").fetchone()[0],
        }
    return page(request, "editor_dashboard.html", submissions=rows, counts=counts)


@app.get("/editor/approved", response_class=HTMLResponse)
def approved_submissions(request: Request):
    require_role(request, "editor")
    with get_db() as db:
        rows = db.execute("""SELECT s.*,u.display_name AS author_name,
                                    (SELECT reviewer.display_name
                                     FROM review_logs rl JOIN users reviewer ON reviewer.id=rl.reviewer_id
                                     WHERE rl.submission_id=s.id AND rl.decision='approve'
                                     ORDER BY rl.id DESC LIMIT 1) AS reviewer_name
                             FROM submissions s
                             JOIN users u ON s.author_id=u.id
                             WHERE s.status='已通過'
                             ORDER BY s.reviewed_at DESC""").fetchall()
    return page(request, "approved_submissions.html", submissions=rows)


@app.get("/editor/submission/{submission_id}", response_class=HTMLResponse)
def review_submission(request: Request, submission_id: int):
    require_role(request, "editor")
    with get_db() as db:
        row = db.execute("""SELECT s.*,u.display_name AS author_name,u.username AS author_username
                            FROM submissions s JOIN users u ON s.author_id=u.id WHERE s.id=?""",
                         (submission_id,)).fetchone()
        history = db.execute("""SELECT rl.decision,rl.decided_at,u.display_name AS reviewer_name
                                FROM review_logs rl JOIN users u ON rl.reviewer_id=u.id
                                WHERE rl.submission_id=? ORDER BY rl.id DESC""",
                             (submission_id,)).fetchall()
    if not row:
        raise HTTPException(404, "找不到稿件")
    return page(request, "review_submission.html", submission=row, history=history)


@app.post("/editor/submission/{submission_id}/decision")
async def review_decision(request: Request, submission_id: int):
    require_role(request, "editor")
    form = await request.form()
    decision = form.get("decision")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as db:
        row = db.execute("SELECT status FROM submissions WHERE id=?", (submission_id,)).fetchone()
        if not row:
            raise HTTPException(404, "找不到稿件")
        if row["status"] != "審查中":
            flash(request, "此稿件目前不是待審查狀態，無法再次處理。", "warning")
        elif decision == "approve":
            result = db.execute("UPDATE submissions SET status='已通過',reviewed_at=?,updated_at=? WHERE id=? AND status='審查中'",
                                (now, now, submission_id))
            if result.rowcount:
                db.execute("INSERT INTO review_logs(submission_id,reviewer_id,decision,decided_at) VALUES(?,?,?,?)",
                           (submission_id, request.session["user_id"], "approve", now))
            flash(request, "審查完成：稿件已通過。", "success")
        elif decision == "return":
            result = db.execute("UPDATE submissions SET status='編輯中',reviewed_at=NULL,updated_at=? WHERE id=? AND status='審查中'",
                                (now, submission_id))
            if result.rowcount:
                db.execute("INSERT INTO review_logs(submission_id,reviewer_id,decision,decided_at) VALUES(?,?,?,?)",
                           (submission_id, request.session["user_id"], "return", now))
            flash(request, "稿件已退回作者，狀態改為「編輯中」。", "info")
        else:
            flash(request, "無效的審查操作。", "danger")
    return go("/editor")


@app.get("/api/dashboard-version")
def api_dashboard_version(request: Request):
    if not request.session.get("user_id"):
        return JSONResponse({"detail": "請先登入"}, status_code=401)
    if request.session.get("role") not in ("author", "editor"):
        return JSONResponse({"detail": "無權限"}, status_code=403)
    return {"version": dashboard_version(request)}


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.status_code == 303:
        return RedirectResponse(exc.headers.get("Location", "/login"), status_code=303)
    if exc.status_code in (403, 404):
        msg = "你沒有權限使用此功能。" if exc.status_code == 403 else "找不到指定的頁面或稿件。"
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "request": request,
                "session": request.session,
                "current_year": datetime.now().year,
                "messages": [],
                "code": exc.status_code,
                "message": msg,
            },
            status_code=exc.status_code,
        )
    return HTMLResponse(str(exc.detail), status_code=exc.status_code)


@app.on_event("startup")
def startup():
    init_db()
