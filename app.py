"""
WALL•E - AI Assistant Platform Backend
--------------------------------------
Author: Sina & Code•Sage
Version: 2.0.0 (Refactored & Secured)
License: MIT

Description:
    This is the main backend entry point for the WALL•E platform.
    It handles API requests, manages chat history with SQLite,
    implements AES-256 encryption for data security, and proxies
    requests to AI providers.
"""

import os
import json
import sqlite3
import base64
import logging
from datetime import datetime
from typing import Dict, List, Optional, Generator, Union, Any

# Third-party imports
from flask import Flask, request, jsonify, Response, stream_with_context, render_template
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
        
        # Generate a new key if none exists (Note: Data will be lost on restart if not saved!)
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
            nonce = os.urandom(12)  # GCM standard nonce size
            data = plain_text.encode('utf-8')
            ciphertext = self.aesgcm.encrypt(nonce, data, None)
            # Combine nonce and ciphertext and encode to base64
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
            # Decode from base64
            raw_data = base64.b64decode(encrypted_text)
            nonce = raw_data[:12]
            ciphertext = raw_data[12:]
            
            decrypted_data = self.aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted_data.decode('utf-8')
        except Exception as e:
            logger.error(f"Decryption error (Possible key mismatch or data corruption): {e}")
            return "[Encrypted Data / Decryption Failed]"

# Initialize Security Service
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
# 💾 Database Service
# ==========================================

class DatabaseService:
    """
    Handles SQLite database operations with integrated encryption.
    """
    
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
                        content TEXT NOT NULL, -- This will be ENCRYPTED
                        liked INTEGER,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (chat_id) REFERENCES chats (id) ON DELETE CASCADE
                    )
                ''')
            logger.info("✅ Database schema initialized.")
        except Exception as e:
            logger.critical(f"Database initialization failed: {e}")

    def save_chat(self, chat_data: Dict[str, Any]):
        """
        Saves or updates a chat and its messages (Encrypts content).
        """
        conn = self._get_connection()
        try:
            # 1. Upsert Chat
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

            # 2. Sync Messages (Delete old, Insert new for simplicity)
            # Note: For massive scale, we should diff instead of delete/insert.
            conn.execute('DELETE FROM messages WHERE chat_id = ?', (chat_data['id'],))

            messages_to_insert = []
            for msg in chat_data.get('messages', []):
                # 🔒 ENCRYPT CONTENT BEFORE SAVING
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
            logger.info(f"💾 Chat saved: {chat_data['id']}")

        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving chat: {e}")
            raise e
        finally:
            conn.close()

    def get_chat(self, chat_id: str) -> Optional[Dict]:
        """
        Retrieves a chat and decrypts its messages.
        """
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
                # 🔓 DECRYPT CONTENT AFTER LOADING
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

# ==========================================
# 🚀 Flask Application Setup
# ==========================================

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

# Initialize Services
ConfigManager.ensure_directories()
db_service = DatabaseService()
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
        "version": "2.0.0",
        "encryption": "AES-256-GCM Enabled"
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
        # Defaults
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
        # Merge updates
        updated_chat = {**existing_chat, **data}
        updated_chat['id'] = chat_id # Ensure ID doesn't change
        
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
# 🤖 AI Chat Logic (Streaming & Proxy)
# ==========================================

def _prepare_proxy_payload(data: Dict, stream: bool) -> Dict:
    """Prepares the payload for the AI Proxy."""
    user_prompt = data.get("prompt", "").strip()
    chat_history = data.get("chat_history", [])
    
    # Construct Messages
    system_prompt = prompts_config.get("system_prompt", "")
    messages = [{"role": "system", "content": system_prompt}]
    
    for msg in chat_history:
        if msg.get("content"):
            messages.append({"role": msg.get("role"), "content": msg.get("content")})
            
    messages.append({"role": "user", "content": user_prompt})
    
    return {
        "model": data.get("model"),
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
    
    try:
        payload = _prepare_proxy_payload(data, stream)
        headers = {
            "Authorization": f"Bearer {PROXY_API_KEY}",
            "Content-Type": "application/json"
        }

        # Request to AI Proxy
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
            return jsonify({
                "model": payload['model'],
                "response": result["choices"][0]["message"]["content"],
                "status": "success"
            })

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
    logger.info("🚀 Starting WALL•E Backend v2.0.0...")
    app.run(debug=True, host='0.0.0.0', port=5000)
