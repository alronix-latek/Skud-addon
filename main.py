import os
import sqlite3
import uuid
import requests
from datetime import datetime
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles  # <-- 1. Импортируем StaticFiles
from typing import List

MODE = os.getenv("MODE", "user")
DB_PATH = "data/doors.db"

app = FastAPI()

# <-- 2. Создаем папку static (если ее нет) и монтируем ее для раздачи CSS
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

def get_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('pragma journal_mode=wal') # WAL для параллельного доступа
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS doors (id TEXT PRIMARY KEY, name TEXT, ip TEXT);
            CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT, token TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS permissions (user_id TEXT, door_id TEXT, UNIQUE(user_id, door_id));
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
                user_name TEXT, door_name TEXT, status TEXT
            );
        """)
    conn.close()

init_db()

# ==========================================
# ЛОГИКА АДМИНА (Порт 8081)
# ==========================================
if MODE == "admin":
    @app.get("/", response_class=HTMLResponse)
    def admin_dashboard(request: Request):
        conn = get_db()
        try:
            doors = conn.execute("SELECT * FROM doors").fetchall()
            users_raw = conn.execute("SELECT * FROM users").fetchall()
            logs = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 50").fetchall()
            
            users = []
            for u in users_raw:
                perms = [row['door_id'] for row in conn.execute("SELECT door_id FROM permissions WHERE user_id=?", (u['id'],)).fetchall()]
                users.append({"id": u["id"], "name": u["name"], "token": u["token"], "permissions": perms})
        finally:
            conn.close()
            
        host_ip = request.url.hostname or "IP_СЕРВЕРА"
            
        return templates.TemplateResponse("admin.html", {
            "request": request, 
            "doors": doors, 
            "users": users, 
            "logs": logs,
            "host_ip": host_ip
        })

    @app.post("/admin_open/{door_id}")
    def admin_open_door(door_id: str):
        conn = get_db()
        try:
            door = conn.execute("SELECT * FROM doors WHERE id=?", (door_id,)).fetchone()
            if not door:
                return {"status": "error", "message": "Дверь не найдена"}
            try:
                response = requests.post(f"http://{door['ip']}/pulse", timeout=3)
                if response.status_code in [200, 303]:
                    conn.execute("INSERT INTO logs (user_name, door_name, status) VALUES (?, ?, ?)", ("Администратор", door['name'], "Успешно"))
                    return {"status": "success"}
                else:
                    conn.execute("INSERT INTO logs (user_name, door_name, status) VALUES (?, ?, ?)", ("Администратор", door['name'], f"Код {response.status_code}"))
                    return {"status": "error", "message": f"Ошибка ESP: код {response.status_code}"}
            except requests.exceptions.RequestException:
                conn.execute("INSERT INTO logs (user_name, door_name, status) VALUES (?, ?, ?)", ("Администратор", door['name'], "Ошибка связи"))
                return {"status": "error", "message": "Ошибка связи с ESP"}
        finally:
            conn.close()

    @app.post("/add_door")
    def add_door(name: str = Form(...), ip: str = Form(...)):
        door_id = uuid.uuid4().hex[:8]
        conn = get_db()
        try:
            conn.execute("INSERT INTO doors (id, name, ip) VALUES (?, ?, ?)", (door_id, name, ip))
        finally:
            conn.close()
        return RedirectResponse(url="/", status_code=303)

    @app.post("/delete_door/{door_id}")
    def delete_door(door_id: str):
        conn = get_db()
        try:
            conn.execute("DELETE FROM doors WHERE id=?", (door_id,))
            conn.execute("DELETE FROM permissions WHERE door_id=?", (door_id,))
        finally:
            conn.close()
        return RedirectResponse(url="/", status_code=303)

    @app.post("/add_user")
    def add_user(name: str = Form(...)):
        user_id = uuid.uuid4().hex[:8]
        token = uuid.uuid4().hex[:12]
        conn = get_db()
        try:
            conn.execute("INSERT INTO users (id, name, token) VALUES (?, ?, ?)", (user_id, name, token))
        finally:
            conn.close()
        return RedirectResponse(url="/", status_code=303)

    @app.post("/delete_user/{user_id}")
    def delete_user(user_id: str):
        conn = get_db()
        try:
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.execute("DELETE FROM permissions WHERE user_id=?", (user_id,))
        finally:
            conn.close()
        return RedirectResponse(url="/", status_code=303)

    @app.post("/update_permissions/{user_id}")
    def update_permissions(request: Request, user_id: str, door_ids: List[str] = Form(default=[])):
        conn = get_db()
        try:
            conn.execute("DELETE FROM permissions WHERE user_id=?", (user_id,))
            for d_id in door_ids:
                conn.execute("INSERT INTO permissions (user_id, door_id) VALUES (?, ?)", (user_id, d_id))
        finally:
            conn.close()
        return RedirectResponse(url="/", status_code=303)

# ==========================================
# ЛОГИКА ПОЛЬЗОВАТЕЛЯ (Порт 8080)
# ==========================================
if MODE == "user":
    @app.get("/u/{token}", response_class=HTMLResponse)
    def user_panel(request: Request, token: str):
        conn = get_db()
        try:
            user = conn.execute("SELECT * FROM users WHERE token=?", (token,)).fetchone()
            if not user:
                return HTMLResponse("<h1>Доступ запрещен</h1>", status_code=403)
                
            doors = conn.execute("""
                SELECT d.* FROM doors d 
                JOIN permissions p ON d.id = p.door_id 
                WHERE p.user_id = ?
            """, (user['id'],)).fetchall()
        finally:
            conn.close()
        
        return templates.TemplateResponse("user.html", {"request": request, "user": user, "doors": doors})

    @app.post("/u/{token}/open/{door_id}")
    def open_door_user(token: str, door_id: str):
        conn = get_db()
        try:
            user = conn.execute("SELECT * FROM users WHERE token=?", (token,)).fetchone()
            if not user:
                return {"status": "error", "message": "Неверный токен"}
                
            perm = conn.execute("SELECT 1 FROM permissions WHERE user_id=? AND door_id=?", (user['id'], door_id)).fetchone()
            if not perm:
                return {"status": "error", "message": "Нет прав доступа"}

            door = conn.execute("SELECT * FROM doors WHERE id=?", (door_id,)).fetchone()
            if not door:
                return {"status": "error", "message": "Дверь не найдена"}
            
            try:
                response = requests.post(f"http://{door['ip']}/pulse", timeout=3)
                if response.status_code in [200, 303]:
                    status_msg = "Успешно"
                    conn.execute("INSERT INTO logs (user_name, door_name, status) VALUES (?, ?, ?)", (user['name'], door['name'], status_msg))
                    return {"status": "success", "message": "Дверь открыта"}
                else:
                    status_msg = f"Ошибка ESP ({response.status_code})"
                    conn.execute("INSERT INTO logs (user_name, door_name, status) VALUES (?, ?, ?)", (user['name'], door['name'], status_msg))
                    return {"status": "error", "message": status_msg}
            except requests.exceptions.RequestException:
                status_msg = "Ошибка связи с ESP"
                conn.execute("INSERT INTO logs (user_name, door_name, status) VALUES (?, ?, ?)", (user['name'], door['name'], status_msg))
                return {"status": "error", "message": status_msg}
        finally:
            conn.close()