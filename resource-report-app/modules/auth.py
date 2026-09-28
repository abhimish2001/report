from typing import Optional, Dict, Any, List
import uuid
import datetime
from passlib.context import CryptContext
from modules.db import db_mgr, init_database

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_user(email: str, name: str, password: str, role: str, manager_id: Optional[int] = None) -> int:
    init_database()
    conn = db_mgr.get_raw_connection()
    try:
        cursor = conn.cursor()
        password_hash = get_password_hash(password)
        cursor.execute("""
            INSERT INTO users (email, name, password_hash, role, manager_id)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?)
        """, (email, name, password_hash, role, manager_id))
        user_id = cursor.fetchone()[0]
        conn.commit()
        return user_id
    finally:
        conn.close()

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    init_database()
    conn = db_mgr.get_raw_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, name, password_hash, role, manager_id FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "email": row[1],
            "name": row[2],
            "password_hash": row[3],
            "role": row[4],
            "manager_id": row[5]
        }
    finally:
        conn.close()

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    init_database()
    conn = db_mgr.get_raw_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, name, role, manager_id FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "email": row[1],
            "name": row[2],
            "role": row[3],
            "manager_id": row[4]
        }
    finally:
        conn.close()

def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    user = get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user

def create_session(user_id: int, days: int = 7) -> str:
    init_database()
    conn = db_mgr.get_raw_connection()
    try:
        cursor = conn.cursor()
        session_token = str(uuid.uuid4())
        expires_at = datetime.datetime.now() + datetime.timedelta(days=days)
        cursor.execute("""
            INSERT INTO user_sessions (session_token, user_id, expires_at)
            VALUES (?, ?, ?)
        """, (session_token, user_id, expires_at.strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        return session_token
    finally:
        conn.close()

def get_user_by_session(session_token: str) -> Optional[Dict[str, Any]]:
    init_database()
    conn = db_mgr.get_raw_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id, u.email, u.name, u.role, u.manager_id, s.expires_at 
            FROM user_sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.session_token = ?
        """, (session_token,))
        row = cursor.fetchone()
        if not row:
            return None
        
        # Check expiration
        expires_at = datetime.datetime.strptime(str(row[5]).split('.')[0], '%Y-%m-%d %H:%M:%S')
        if datetime.datetime.now() > expires_at:
            cursor.execute("DELETE FROM user_sessions WHERE session_token = ?", (session_token,))
            conn.commit()
            return None
            
        return {
            "id": row[0],
            "email": row[1],
            "name": row[2],
            "role": row[3],
            "manager_id": row[4]
        }
    finally:
        conn.close()

def delete_session(session_token: str) -> None:
    conn = db_mgr.get_raw_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE session_token = ?", (session_token,))
        conn.commit()
    finally:
        conn.close()

def get_team_members(manager_id: int) -> List[Dict[str, Any]]:
    init_database()
    conn = db_mgr.get_raw_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, name, role FROM users WHERE manager_id = ?", (manager_id,))
        rows = cursor.fetchall()
        return [{"id": r[0], "email": r[1], "name": r[2], "role": r[3]} for r in rows]
    finally:
        conn.close()
