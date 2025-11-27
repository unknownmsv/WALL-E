"""
WALL•E - AI Assistant Platform Backend
--------------------------------------
Author: Sina & Code•Sage
Version: 2.1.0 (Dynamic Prompts Logic Added)
License: MIT

Description:
    This is the main backend entry point for the WALL•E platform.
    It handles API requests, manages chat history with SQLite or Supabase,
    implements AES-256 encryption for data security, and proxies
    requests to AI providers with dynamic system prompt selection.
    Now it can also serve encrypted chat content while securely streaming
    audio files (MP3/OGG) from the local /Music directory.
"""

import os
import json
import sqlite3
import base64
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Generator, Any

# Third-party imports
from flask import (
    Flask,
    request,
    jsonify,
    Response,
    stream_with_context,
    render_template,
    send_file,
    url_for
)
from flask_cors import CORS
import requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("WALLE_Core")

# Load environment variables
load_dotenv()

# ==============================================================
# 🎵 Audio Configuration
# ==============================================================

MUSIC_DIRECTORY = Path(os.getenv("MUSIC_DIRECTORY", "/Music")).resolve()
ALLOWED_AUDIO_EXTENSIONS = {'.mp3', '.ogg'}

if not MUSIC_DIRECTORY.exists():
    logger.warning(f"🎵 Music directory '{MUSIC_DIRECTORY}' does not exist. Audio routes will be limited.")

# ==========================================
# 🔐 Security Service (AES-256)
# ==========================================

class SecurityService:
    """
    Handles AES-256-GCM encryption and decryption for sensitive data.
    """
    
    def __init__(self, key_str: Optional[str] = None):
        """
        Initialize the security service.
        
        Args:
            key_str (str): Base64 encoded 32-byte key. If None, loads from env or generates new.
        """
        self.key = self._load_or_generate_key(key_str)
        self.aesgcm = AESGCM(self.key)

    def _load_or_generate_key(self, key_str: Optional[str]) -> bytes:
        """Loads key from env or generates a valid AES-256 key."""
        env_key = key_str or os.getenv('ENCRYPTION_KEY')
        
        if env_key:
            try:
                return base64.b64decode(env_key)
            except Exception as e:
                logger.error(f"Invalid key format in env: {e}")
        
        logger.warning("⚠️ No valid ENCRYPTION_KEY found. Generating a temporary key.")
        new_key = AESGCM.generate_key(bit_length=256)
        print(f"\n🔑 NEW GENERATED KEY (Save this to .env): {base64.b64encode(new_key).decode('utf-8')}\n")
        return new_key

    def encrypt(self, plain_text: str) -> str:
        """
        Encrypts a string using AES-256-GCM.
        
        Args:
            plain_text (str): The text to encrypt.
            
        Returns:
            str: Base64 encoded string containing 'nonce + ciphertext'.
        """
        if not plain_text:
            return ""
        try:
            nonce = os.urandom(12)
            data = plain_text.encode('utf-8')
            ciphertext = self.aesgcm.encrypt(nonce, data, None)
            return base64.b64encode(nonce + ciphertext).decode('utf-8')
        except Exception as e:
            logger.error(f"Encryption error: {e}")
            raise e

    def decrypt(self, encrypted_text: str) -> str:
        """
        Decrypts a Base64 encoded string using AES-256-GCM.
        
        Args:
            encrypted_text (str): The encrypted string.
            
        Returns:
            str: Decrypted plain text.
        """
        if not encrypted_text:
            return ""
        try:
            raw_data = base64.b64decode(encrypted_text)
            nonce = raw_data[:12]
            ciphertext = raw_data[12:]
            decrypted_data = self.aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted_data.decode('utf-8')
        except Exception as e:
            logger.error(f"Decryption error (Possible key mismatch or data corruption): {e}")
            return "[Encrypted Data / Decryption Failed]"

security_service = SecurityService()

# ==========================================
# ⚙️ Configuration Manager
# ==========================================

class ConfigManager:
    """Manages loading and saving configuration files."""
    
    BASE_DIR = 'static'
    MODELS_PATH = os.path.join(BASE_DIR, 'models', 'config.json')
    PROMPTS_PATH = os.path.join(BASE_DIR, 'prompts', 'system.json')

    DEFAULT_MODELS = {
        "available_models": {
            "openai/gpt-4o-mini": {
                "name": "GPT-4o Mini",
                "description": "OpenAI GPT-4o Mini - Efficient",
                "provider": "openai",
                "max_tokens": 8000
            }
        },
        "default_model": "openai/gpt-4o-mini"
    }

    DEFAULT_PROMPTS = {
        "system_prompt": "You are WALL•E, a helpful AI assistant.",
        "model_specific_prompts": {},
        "welcome_message": "Hello! I'm WALL•E. How can I help?"
    }

    @staticmethod
    def ensure_directories():
        """Creates necessary directories if they don't exist."""
        dirs = ['templates', 'static/css', 'static/js', 'static/models', 'static/prompts', 'data']
        for d in dirs:
            os.makedirs(d, exist_ok=True)

    @staticmethod
    def load_json(path: str, default: Dict) -> Dict:
        """Loads JSON config with fallback to default."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning(f"Config not found or invalid at {path}. Creating default.")
            ConfigManager.save_json(path, default)
            return default

    @staticmethod
    def save_json(path: str, data: Dict):
        """Saves dictionary to JSON file."""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save config to {path}: {e}")

# ==========================================
# 💾 Database Services (SQLite / Supabase)
# ==========================================

class BaseDatabaseService(ABC):
    """Abstract base for database providers."""

    @abstractmethod
    def save_chat(self, chat_data: Dict[str, Any]):
        """Persists (upserts) chat metadata and messages."""

    @abstractmethod
    def get_chat(self, chat_id: str) -> Optional[Dict]:
        """Returns a single chat with decrypted messages."""

    @abstractmethod
    def get_all_chats(self) -> List[Dict]:
        """Lists all chats with metadata."""

    @abstractmethod
    def delete_chat(self, chat_id: str):
        """Deletes a chat and its messages."""


class SQLiteDatabaseService(BaseDatabaseService):
    """Handles SQLite database operations with integrated encryption."""
    
    DB_PATH = 'data/chats.db'

    def __init__(self):
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Creates a database connection with Row factory."""
        conn = sqlite3.connect(self.DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes database schema."""
        try:
            with self._get_connection() as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS chats (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        model TEXT NOT NULL,
                        pinned INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        liked INTEGER,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (chat_id) REFERENCES chats (id) ON DELETE CASCADE
                    )
                ''')
            logger.info("✅ SQLite schema initialized.")
        except Exception as e:
            logger.critical(f"Database initialization failed: {e}")

    def save_chat(self, chat_data: Dict[str, Any]):
        """Saves or updates a chat and its messages (Encrypts content)."""
        conn = self._get_connection()
        try:
            conn.execute('''
                INSERT OR REPLACE INTO chats (id, title, model, pinned, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                chat_data['id'],
                chat_data.get('title', 'New Chat'),
                chat_data.get('model', 'unknown'),
                int(chat_data.get('pinned', False)),
                chat_data.get('created_at', datetime.now().isoformat())
            ))

            conn.execute('DELETE FROM messages WHERE chat_id = ?', (chat_data['id'],))

            messages_to_insert = []
            for msg in chat_data.get('messages', []):
                encrypted_content = security_service.encrypt(msg['content'])
                messages_to_insert.append((
                    chat_data['id'],
                    msg['role'],
                    encrypted_content,
                    msg.get('liked'),
                    msg.get('timestamp', datetime.now().isoformat())
                ))

            if messages_to_insert:
                conn.executemany('''
                    INSERT INTO messages (chat_id, role, content, liked, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', messages_to_insert)

            conn.commit()
            logger.info(f"💾 Chat saved (SQLite): {chat_data['id']}")

        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving chat: {e}")
            raise e
        finally:
            conn.close()

    def get_chat(self, chat_id: str) -> Optional[Dict]:
        """Retrieves a chat and decrypts its messages."""
        conn = self._get_connection()
        try:
            chat_row = conn.execute('SELECT * FROM chats WHERE id = ?', (chat_id,)).fetchone()
            if not chat_row:
                return None

            msgs_rows = conn.execute(
                'SELECT role, content, liked, timestamp FROM messages WHERE chat_id = ? ORDER BY timestamp',
                (chat_id,)
            ).fetchall()

            messages = []
            for row in msgs_rows:
                decrypted_content = security_service.decrypt(row['content'])
                messages.append({
                    'role': row['role'],
                    'content': decrypted_content,
                    'liked': row['liked'],
                    'timestamp': row['timestamp']
                })

            return {
                'id': chat_row['id'],
                'title': chat_row['title'],
                'model': chat_row['model'],
                'pinned': bool(chat_row['pinned']),
                'created_at': chat_row['created_at'],
                'messages': messages
            }
        except Exception as e:
            logger.error(f"Error loading chat {chat_id}: {e}")
            return None
        finally:
            conn.close()

    def get_all_chats(self) -> List[Dict]:
        """Retrieves metadata for all chats."""
        conn = self._get_connection()
        try:
            cursor = conn.execute('''
                SELECT c.*, COUNT(m.id) as message_count
                FROM chats c
                LEFT JOIN messages m ON c.id = m.chat_id
                GROUP BY c.id
                ORDER BY c.created_at DESC
            ''')
            
            return [{
                'id': row['id'],
                'title': row['title'],
                'model': row['model'],
                'pinned': bool(row['pinned']),
                'created_at': row['created_at'],
                'message_count': row['message_count']
            } for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error listing chats: {e}")
            return []
        finally:
            conn.close()

    def delete_chat(self, chat_id: str):
        """Deletes a chat and its messages."""
        with self._get_connection() as conn:
            conn.execute('DELETE FROM chats WHERE id = ?', (chat_id,))
            conn.commit()
        logger.info(f"🗑️ Chat deleted (SQLite): {chat_id}")


class SupabaseDatabaseService(BaseDatabaseService):
    """Handles Supabase persistence via REST API (`requests`-based) with encryption."""

    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.api_key = os.getenv("SUPABASE_API_KEY")
        if not self.supabase_url or not self.api_key:
            raise ValueError("Supabase credentials (SUPABASE_URL & SUPABASE_API_KEY) are required.")
        self.rest_url = self._build_rest_url(self.supabase_url)
        self.session = requests.Session()
        self.base_headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        logger.info("✅ Supabase service initialized.")

    @staticmethod
    def _build_rest_url(url: str) -> str:
        """Ensures the REST endpoint is correctly formed."""
        if url.endswith("/rest/v1"):
            return url
        return f"{url}/rest/v1"

    def _with_prefer(self, *directives: str) -> Dict[str, str]:
        """Merges Prefer directives with base headers."""
        headers = dict(self.base_headers)
        cleaned = [d for d in directives if d]
        if cleaned:
            headers["Prefer"] = ",".join(cleaned)
        return headers

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Executes an HTTP request and raises informative errors on failure."""
        url = f"{self.rest_url}/{path.lstrip('/')}"
        headers = kwargs.pop('headers', self.base_headers)
        try:
            response = self.session.request(method=method.upper(), url=url, headers=headers, timeout=30, **kwargs)
        except requests.RequestException as exc:
            logger.error(f"Supabase network error: {exc}")
            raise RuntimeError("Supabase request failed") from exc

        if not response.ok:
            logger.error("Supabase responded with %s: %s", response.status_code, response.text)
            raise RuntimeError(f"Supabase error ({response.status_code})")
        return response

    def save_chat(self, chat_data: Dict[str, Any]):
        """Upserts chat and messages on Supabase (encrypted content)."""
        chat_payload = {
            "id": chat_data['id'],
            "title": chat_data.get('title', 'New Chat'),
            "model": chat_data.get('model', 'unknown'),
            "pinned": bool(chat_data.get('pinned', False)),
            "created_at": chat_data.get('created_at', datetime.now().isoformat())
        }
        try:
            self._request(
                "post",
                "chats",
                params={"on_conflict": "id"},
                headers=self._with_prefer("resolution=merge-duplicates"),
                json=[chat_payload]
            )

            self._request("delete", "messages", params={"chat_id": f"eq.{chat_data['id']}"})

            messages_to_insert = []
            for msg in chat_data.get('messages', []):
                encrypted_content = security_service.encrypt(msg['content'])
                messages_to_insert.append({
                    "chat_id": chat_data['id'],
                    "role": msg['role'],
                    "content": encrypted_content,
                    "liked": msg.get('liked'),
                    "timestamp": msg.get('timestamp', datetime.now().isoformat())
                })

            if messages_to_insert:
                self._request(
                    "post",
                    "messages",
                    headers=self._with_prefer("return=minimal"),
                    json=messages_to_insert
                )

            logger.info(f"💾 Chat saved (Supabase): {chat_data['id']}")
        except Exception as exc:
            logger.error(f"Supabase save failed: {exc}")
            raise

    def get_chat(self, chat_id: str) -> Optional[Dict]:
        """Fetches a single chat with decrypted messages from Supabase."""
        try:
            chat_resp = self._request(
                "get",
                "chats",
                params={"id": f"eq.{chat_id}", "select": "*", "limit": 1}
            ).json()

            if not chat_resp:
                return None

            chat_row = chat_resp[0]

            messages_resp = self._request(
                "get",
                "messages",
                params={
                    "chat_id": f"eq.{chat_id}",
                    "select": "role,content,liked,timestamp",
                    "order": "timestamp.asc"
                }
            ).json()

            messages = []
            for row in messages_resp:
                decrypted_content = security_service.decrypt(row['content'])
                messages.append({
                    "role": row['role'],
                    "content": decrypted_content,
                    "liked": row.get('liked'),
                    "timestamp": row.get('timestamp')
                })

            return {
                "id": chat_row['id'],
                "title": chat_row['title'],
                "model": chat_row['model'],
                "pinned": bool(chat_row['pinned']),
                "created_at": chat_row['created_at'],
                "messages": messages
            }
        except Exception as exc:
            logger.error(f"Supabase get_chat failed: {exc}")
            return None

    def get_all_chats(self) -> List[Dict]:
        """Lists chats along with aggregated message counts."""
        try:
            rows = self._request(
                "get",
                "chats",
                params={
                    "select": "id,title,model,pinned,created_at,message_count:messages(count)",
                    "order": "created_at.desc"
                }
            ).json()

            chats: List[Dict[str, Any]] = []
            for row in rows:
                message_summary = row.get('message_count', [])
                if isinstance(message_summary, list) and message_summary:
                    message_count = message_summary[0].get('count', 0)
                else:
                    message_count = row.get('message_count', 0)

                chats.append({
                    "id": row['id'],
                    "title": row['title'],
                    "model": row['model'],
                    "pinned": bool(row['pinned']),
                    "created_at": row['created_at'],
                    "message_count": message_count
                })
            return chats
        except Exception as exc:
            logger.error(f"Supabase get_all_chats failed: {exc}")
            return []

    def delete_chat(self, chat_id: str):
        """Deletes a chat (and ensures messages are removed)."""
        try:
            self._request("delete", "messages", params={"chat_id": f"eq.{chat_id}"})
            self._request("delete", "chats", params={"id": f"eq.{chat_id}"})
            logger.info(f"🗑️ Chat deleted (Supabase): {chat_id}")
        except Exception as exc:
            logger.error(f"Supabase delete_chat failed: {exc}")
            raise


def get_database_service() -> BaseDatabaseService:
    """
    Returns the correct database service implementation based on env.
    Accepts DB_PROVIDER=sqlite (default) or DB_PROVIDER=supabase.
    Falls back to SQLite if Supabase configuration fails.
    """
    provider = os.getenv("DB_PROVIDER", "sqlite").strip().lower()
    if provider == "supabase":
        try:
            logger.info("Attempting to initialize Supabase backend...")
            return SupabaseDatabaseService()
        except Exception as exc:
            logger.error(f"Supabase init failed ({exc}). Falling back to SQLite.")
    logger.info("Using SQLite backend.")
    return SQLiteDatabaseService()

# ==========================================
# 🎵 Audio Helpers
# ==========================================

def _resolve_music_file(filename: str) -> Path:
    """
    Validates and resolves a requested audio file inside MUSIC_DIRECTORY.
    
    Args:
        filename (str): Name of the audio file requested by the user.
    
    Returns:
        Path: Absolute, validated file path.
    
    Raises:
        ValueError: If filename or extension is invalid.
        FileNotFoundError: If the file does not exist.
        PermissionError: If the resolved path escapes MUSIC_DIRECTORY.
    """
    cleaned_name = filename.strip()
    if not cleaned_name:
        raise ValueError("Filename is required for audio playback.")
    candidate = (MUSIC_DIRECTORY / cleaned_name).resolve()
    if candidate.suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError("Only MP3 and OGG files are allowed.")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Audio file '{cleaned_name}' not found.")
    try:
        candidate.relative_to(MUSIC_DIRECTORY)
    except ValueError as exc:
        raise PermissionError("Invalid path. Access outside music directory is not allowed.") from exc
    return candidate

def _get_audio_mimetype(file_path: Path) -> str:
    """Maps audio extensions to proper MIME types."""
    return {
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg"
    }.get(file_path.suffix.lower(), "application/octet-stream")

# ==========================================
# 🚀 Flask Application Setup
# ==========================================

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

ConfigManager.ensure_directories()
db_service = get_database_service()
models_config = ConfigManager.load_json(ConfigManager.MODELS_PATH, ConfigManager.DEFAULT_MODELS)
prompts_config = ConfigManager.load_json(ConfigManager.PROMPTS_PATH, ConfigManager.DEFAULT_PROMPTS)

PROXY_URL = os.getenv('PROXY_URL')
PROXY_API_KEY = os.getenv('PROXY_API_KEY')

# ==========================================
# 🌐 API Routes
# ==========================================

@app.route('/')
def serve_index():
    return render_template('index.html')

@app.route('/api')
def api_status():
    return jsonify({
        "status": "WALL•E is online",
        "version": "2.1.0",
        "encryption": "AES-256-GCM Enabled",
        "dynamic_prompts": "Active",
        "db_provider": os.getenv("DB_PROVIDER", "sqlite"),
        "music_directory": str(MUSIC_DIRECTORY)
    })

@app.route('/api/config')
def get_config():
    return jsonify({
        "models": models_config,
        "prompt": prompts_config
    })

@app.route('/api/chats', methods=['GET'])
def get_chats():
    chats = db_service.get_all_chats()
    return jsonify(chats)

@app.route('/api/chats/<chat_id>', methods=['GET'])
def get_single_chat(chat_id):
    chat = db_service.get_chat(chat_id)
    if chat:
        return jsonify(chat)
    return jsonify({"error": "Chat not found"}), 404

@app.route('/api/chats', methods=['POST'])
def create_chat():
    data = request.get_json()
    if not data or 'id' not in data:
        return jsonify({"error": "Invalid data, ID required"}), 400
    
    try:
        data.setdefault('title', 'New Chat')
        data.setdefault('model', models_config.get("default_model"))
        data.setdefault('messages', [])
        
        db_service.save_chat(data)
        return jsonify(data), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/chats/<chat_id>', methods=['PUT'])
def update_chat(chat_id):
    data = request.get_json()
    existing_chat = db_service.get_chat(chat_id)
    
    if not existing_chat:
        return jsonify({"error": "Chat not found"}), 404
    
    try:
        updated_chat = {**existing_chat, **data}
        updated_chat['id'] = chat_id
        
        db_service.save_chat(updated_chat)
        return jsonify(updated_chat)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/chats/<chat_id>', methods=['DELETE'])
def delete_chat(chat_id):
    try:
        db_service.delete_chat(chat_id)
        return jsonify({"message": "Deleted successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==========================================
# 🎵 Audio Routes
# ==========================================

@app.route('/api/music/library', methods=['GET'])
def list_music():
    """
    Lists available audio files inside the configured music directory.
    """
    if not MUSIC_DIRECTORY.exists():
        return jsonify({"tracks": [], "message": "Music directory not found."})
    
    tracks = []
    for item in MUSIC_DIRECTORY.iterdir():
        if item.is_file() and item.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS:
            tracks.append({
                "filename": item.name,
                "size_bytes": item.stat().st_size,
                "mime_type": _get_audio_mimetype(item)
            })
    return jsonify({"tracks": tracks})

@app.route('/api/music/play', methods=['GET'])
def play_music():
    """
    Streams a requested audio file (mp3/ogg) to the client.
    The filename must exist under MUSIC_DIRECTORY and is validated to prevent traversal.
    """
    filename = request.args.get('filename', '').strip()
    if not filename:
        return jsonify({"error": "filename query parameter is required."}), 400
    try:
        audio_file = _resolve_music_file(filename)
        return send_file(
            audio_file,
            mimetype=_get_audio_mimetype(audio_file),
            as_attachment=False,
            conditional=True,
            download_name=audio_file.name
        )
    except FileNotFoundError:
        return jsonify({"error": "Audio file not found."}), 404
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"Audio streaming failed: {exc}")
        return jsonify({"error": "Internal error while streaming audio."}), 500

# ==========================================
# 🤖 AI Chat Logic (Streaming & Proxy)
# ==========================================

def _prepare_proxy_payload(data: Dict, stream: bool) -> Dict:
    """
    Prepares the payload for the AI Proxy.
    UPDATED: Now selects system prompt based on model category.
    """
    user_prompt = data.get("prompt", "").strip()
    chat_history = data.get("chat_history", [])
    model_name = data.get("model")
    
    available_models = models_config.get("available_models", {})
    current_model_config = available_models.get(model_name, {})
    model_category = current_model_config.get("category", "general")
    
    specific_prompts = prompts_config.get("model_specific_prompts", {})
    fallback_prompt = prompts_config.get("system_prompt", "You are a helpful AI assistant.")
    
    if model_category in specific_prompts:
        system_prompt = specific_prompts[model_category]
        logger.info(f"🧠 Selected Prompt: '{model_category}' for model '{model_name}'")
    else:
        system_prompt = fallback_prompt
        logger.info(f"🧠 Selected Prompt: 'Default/Fallback' for model '{model_name}'")
    
    messages = [{"role": "system", "content": system_prompt}]
    
    for msg in chat_history:
        if msg.get("content"):
            messages.append({"role": msg.get("role"), "content": msg.get("content")})
            
    messages.append({"role": "user", "content": user_prompt})
    
    return {
        "model": model_name,
        "messages": messages,
        "max_tokens": data.get("max_tokens", 4000),
        "stream": stream
    }

@app.route('/api/chat', methods=['POST'])
def chat_endpoint():
    data = request.get_json()
    if not data or not data.get("prompt"):
        return jsonify({"error": "Prompt is required"}), 400

    stream = data.get("stream", False)
    if data.get("music_file") and stream:
        return jsonify({"error": "Audio metadata cannot be returned while streaming responses."}), 400
    
    try:
        payload = _prepare_proxy_payload(data, stream)
        headers = {
            "Authorization": f"Bearer {PROXY_API_KEY}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            PROXY_URL, 
            headers=headers, 
            json=payload, 
            timeout=120, 
            stream=stream
        )
        response.raise_for_status()

        if stream:
            return Response(stream_with_context(_generate_stream(response, payload['model'])), content_type='text/plain')
        else:
            result = response.json()
            ai_message = result["choices"][0]["message"]["content"]

            audio_payload = None
            music_request = data.get("music_file")
            if music_request:
                try:
                    audio_path = _resolve_music_file(music_request)
                    audio_payload = {
                        "filename": audio_path.name,
                        "url": url_for('play_music', filename=audio_path.name, _external=True),
                        "mime_type": _get_audio_mimetype(audio_path)
                    }
                except (FileNotFoundError, PermissionError, ValueError) as audio_exc:
                    logger.error(f"Music request failed: {audio_exc}")
                    audio_payload = {"error": str(audio_exc)}

            response_body = {
                "model": payload['model'],
                "response": ai_message,
                "status": "success"
            }
            if audio_payload:
                response_body["audio"] = audio_payload

            return jsonify(response_body)

    except Exception as e:
        logger.error(f"AI API Error: {e}")
        return jsonify({"error": str(e)}), 500

def _generate_stream(response_obj, model_name: str) -> Generator[str, None, None]:
    """Yields Server-Sent Events (SSE) format data."""
    full_response = ""
    for line in response_obj.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith('data: '):
                data_str = decoded_line[6:]
                if data_str == '[DONE]':
                    yield f"data: {json.dumps({'done': True, 'full_response': full_response})}\n\n"
                    break
                try:
                    chunk = json.loads(data_str)
                    if 'choices' in chunk and chunk['choices']:
                        delta = chunk['choices'][0].get('delta', {})
                        if 'content' in delta:
                            content = delta['content']
                            full_response += content
                            yield f"data: {json.dumps({'content': content, 'model': model_name})}\n\n"
                except json.JSONDecodeError:
                    continue

if __name__ == "__main__":
    logger.info("🚀 Starting WALL•E Backend v2.1.0...")
    app.run(debug=True, host='0.0.0.0', port=5000)
