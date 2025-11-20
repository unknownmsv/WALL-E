from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context, render_template
from flask_cors import CORS
import requests
import json
import os
import sqlite3
import traceback
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, 
            template_folder='templates',
            static_folder='static')
CORS(app)

PROXY_URL = os.getenv('PROXY_URL')
PROXY_API_KEY = os.getenv('PROXY_API_KEY')

# Configuration paths
CONFIG_DIR = 'static'
MODELS_CONFIG_PATH = os.path.join(CONFIG_DIR, 'models', 'config.json')
PROMPTS_CONFIG_PATH = os.path.join(CONFIG_DIR, 'prompts', 'system.json')
DATABASE_PATH = 'data/chats.db'

# Ensure directories exist
os.makedirs('templates', exist_ok=True)
os.makedirs('static/css', exist_ok=True)
os.makedirs('static/js', exist_ok=True)
os.makedirs('static/models', exist_ok=True)
os.makedirs('static/prompts', exist_ok=True)
os.makedirs('data', exist_ok=True)

# Initialize SQLite database
def init_db():
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        
        # Create chats table
        c.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                model TEXT NOT NULL,
                pinned INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create messages table
        c.execute('''
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
        
        conn.commit()
        conn.close()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"❌ Database initialization error: {e}")
        print(traceback.format_exc())

# Initialize database on startup
init_db()

# Load configuration files
def load_config(file_path, default_config):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        print(f"✅ Config loaded successfully: {file_path}")
        return config
    except Exception as e:
        print(f"⚠️  Error loading {file_path}, using default: {e}")
        # Save default config
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            print(f"✅ Default config created: {file_path}")
        except Exception as write_error:
            print(f"❌ Error creating default config: {write_error}")
        return default_config

# Load models configuration
models_data = load_config(MODELS_CONFIG_PATH, {
    "available_models": {
        "openai/gpt-4o-mini": {
            "name": "GPT-4o Mini",
            "description": "OpenAI GPT-4o Mini model - Fast and efficient",
            "provider": "openai",
            "category": "general",
            "max_tokens": 8000,
            "context_window": 128000
        },
        "google/gemini-2.0-flash-001": {
            "name": "Gemini 2.0 Flash", 
            "description": "Google Gemini 2.0 Flash model - Ultra fast response",
            "provider": "google",
            "category": "general",
            "max_tokens": 8000,
            "context_window": 1000000
        }
    },
    "default_model": "openai/gpt-4o-mini",
    "model_categories": {
        "general": "General Purpose",
        "coding": "Code Specialized", 
        "creative": "Creative Writing",
        "analysis": "Data Analysis"
    },
    "providers": {
        "openai": "OpenAI",
        "google": "Google",
        "deepseek": "DeepSeek",
        "anthropic": "Anthropic",
        "meta": "Meta"
    }
})

# Load prompts configuration
prompt_data = load_config(PROMPTS_CONFIG_PATH, {
    "system_prompt": "You are WALL•E, a helpful AI assistant that specializes in coding, problem-solving, and creative tasks. Provide clear, concise, and helpful responses tailored to the user's needs.",
    "welcome_message": "Hello! I'm WALL•E, your AI assistant. How can I help you today?",
    "suggestions": [
        "Help me debug this Python code",
        "Explain machine learning concepts in simple terms",
        "Help me plan a project timeline",
        "Write a professional email to my team"
    ],
    "model_specific_prompts": {
        "coding": "You are an expert programming assistant. Focus on providing clean, efficient, and well-documented code solutions.",
        "creative": "You are a creative writing assistant. Help users with storytelling, content creation, and creative projects.",
        "analysis": "You are a data analysis specialist. Help users understand data, create visualizations, and draw insights."
    }
})

@app.route('/')
def serve_index():
    return render_template('index.html')

@app.route('/api')
def api_status():
    return jsonify({
        "status": "WALL•E is running",
        "available_models": list(models_data.get("available_models", {}).keys()),
        "proxy_url": PROXY_URL,
        "version": "1.0.0"
    })

@app.route('/api/config')
def get_config():
    """API endpoint to get configuration"""
    return jsonify({
        "models": models_data,
        "prompt": prompt_data,
        "app": {
            "name": "WALL•E",
            "version": "1.0.0",
            "description": "AI Assistant Platform"
        }
    })

# Database helper functions
def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def save_chat_to_db(chat_data):
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        print(f"💾 Saving chat to DB: {chat_data['id']}")
        
        # Insert or update chat
        c.execute('''
            INSERT OR REPLACE INTO chats (id, title, model, pinned, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            chat_data['id'], 
            chat_data['title'], 
            chat_data['model'], 
            int(chat_data.get('pinned', False)),
            chat_data.get('created_at', datetime.now().isoformat())
        ))
        
        # Delete existing messages for this chat
        c.execute('DELETE FROM messages WHERE chat_id = ?', (chat_data['id'],))
        
        # Insert new messages
        for message in chat_data.get('messages', []):
            c.execute('''
                INSERT INTO messages (chat_id, role, content, liked, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                chat_data['id'], 
                message['role'], 
                message['content'], 
                message.get('liked'),
                message.get('timestamp', datetime.now().isoformat())
            ))
        
        conn.commit()
        print(f"✅ Chat saved successfully: {chat_data['id']}")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error saving chat to DB: {e}")
        print(traceback.format_exc())
        raise e
    finally:
        conn.close()

def get_chat_from_db(chat_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Get chat info
        c.execute('SELECT * FROM chats WHERE id = ?', (chat_id,))
        chat_row = c.fetchone()
        
        if not chat_row:
            print(f"❌ Chat not found: {chat_id}")
            return None
        
        # Get messages
        c.execute('''
            SELECT role, content, liked, timestamp 
            FROM messages 
            WHERE chat_id = ? 
            ORDER BY timestamp
        ''', (chat_id,))
        messages_rows = c.fetchall()
        
        chat_data = {
            'id': chat_row['id'],
            'title': chat_row['title'],
            'model': chat_row['model'],
            'pinned': bool(chat_row['pinned']),
            'created_at': chat_row['created_at'],
            'messages': [
                {
                    'role': row['role'],
                    'content': row['content'],
                    'liked': row['liked'],
                    'timestamp': row['timestamp']
                }
                for row in messages_rows
            ]
        }
        
        print(f"✅ Chat loaded from DB: {chat_id}")
        return chat_data
        
    except Exception as e:
        print(f"❌ Error getting chat from DB: {e}")
        print(traceback.format_exc())
        return None
    finally:
        conn.close()

def get_all_chats_from_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('''
            SELECT c.*, COUNT(m.id) as message_count
            FROM chats c
            LEFT JOIN messages m ON c.id = m.chat_id
            GROUP BY c.id
            ORDER BY c.created_at DESC
        ''')
        
        chats_rows = c.fetchall()
        
        chats = []
        for row in chats_rows:
            chats.append({
                'id': row['id'],
                'title': row['title'],
                'model': row['model'],
                'pinned': bool(row['pinned']),
                'created_at': row['created_at'],
                'message_count': row['message_count']
            })
        
        print(f"✅ Loaded {len(chats)} chats from DB")
        return chats
        
    except Exception as e:
        print(f"❌ Error getting all chats from DB: {e}")
        print(traceback.format_exc())
        return []
    finally:
        conn.close()

def delete_chat_from_db(chat_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('DELETE FROM chats WHERE id = ?', (chat_id,))
        conn.commit()
        print(f"✅ Chat deleted from DB: {chat_id}")
        
    except Exception as e:
        print(f"❌ Error deleting chat from DB: {e}")
        print(traceback.format_exc())
        raise e
    finally:
        conn.close()

# API routes for chat management
@app.route('/api/chats', methods=['GET'])
def get_all_chats():
    try:
        print("📥 GET /api/chats")
        chats = get_all_chats_from_db()
        return jsonify(chats)
    except Exception as e:
        print(f"❌ Error in GET /api/chats: {e}")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/chats/<chat_id>', methods=['GET'])
def get_chat(chat_id):
    try:
        print(f"📥 GET /api/chats/{chat_id}")
        chat = get_chat_from_db(chat_id)
        if chat:
            return jsonify(chat)
        else:
            return jsonify({"error": "Chat not found"}), 404
    except Exception as e:
        print(f"❌ Error in GET /api/chats/{chat_id}: {e}")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/chats', methods=['POST'])
def create_chat():
    try:
        print("📥 POST /api/chats")
        data = request.get_json()
        print(f"📦 Request data: {data}")
        
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        if not data.get('id'):
            return jsonify({"error": "Chat ID is required"}), 400
            
        chat_data = {
            'id': data['id'],
            'title': data.get('title', 'New Chat'),
            'model': data.get('model', models_data.get("default_model", "openai/gpt-4o-mini")),
            'pinned': data.get('pinned', False),
            'created_at': data.get('created_at', datetime.now().isoformat()),
            'messages': data.get('messages', [])
        }
        
        save_chat_to_db(chat_data)
        return jsonify(chat_data)
        
    except Exception as e:
        print(f"❌ Error in POST /api/chats: {e}")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/chats/<chat_id>', methods=['PUT'])
def update_chat(chat_id):
    try:
        print(f"📥 PUT /api/chats/{chat_id}")
        data = request.get_json()
        print(f"📦 Request data: {data}")
        
        existing_chat = get_chat_from_db(chat_id)
        
        if not existing_chat:
            return jsonify({"error": "Chat not found"}), 404
        
        # Update only provided fields
        chat_data = {
            'id': chat_id,
            'title': data.get('title', existing_chat['title']),
            'model': data.get('model', existing_chat['model']),
            'pinned': data.get('pinned', existing_chat['pinned']),
            'created_at': existing_chat['created_at'],
            'messages': data.get('messages', existing_chat['messages'])
        }
        
        save_chat_to_db(chat_data)
        return jsonify(chat_data)
        
    except Exception as e:
        print(f"❌ Error in PUT /api/chats/{chat_id}: {e}")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/chats/<chat_id>', methods=['DELETE'])
def delete_chat(chat_id):
    try:
        print(f"📥 DELETE /api/chats/{chat_id}")
        delete_chat_from_db(chat_id)
        return jsonify({"message": "Chat deleted successfully"})
    except Exception as e:
        print(f"❌ Error in DELETE /api/chats/{chat_id}: {e}")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "Invalid JSON"}), 400

        user_prompt = data.get("prompt", "").strip()
        ai_model = data.get("model")
        stream = data.get("stream", False)
        chat_history = data.get("chat_history", [])
        max_tokens = data.get("max_tokens", 8000)

        if stream:
            return stream_chat(user_prompt, ai_model, chat_history, max_tokens)

        if not user_prompt:
            return jsonify({"error": "Prompt is required"}), 400
        
        if len(user_prompt) > 50000:
            return jsonify({"error": "Prompt too long (max 50,000 characters)"}), 400

        available_models = models_data.get("available_models", {})
        if ai_model not in available_models:
            return jsonify({"error": "Model not found"}), 400

        system_prompt = prompt_data.get("system_prompt", "")

        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        for msg in chat_history:
            messages.append({
                "role": msg.get("role"),
                "content": msg.get("content")
            })
        
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": ai_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": False
        }

        headers = {
            "Authorization": f"Bearer {PROXY_API_KEY}",
            "Content-Type": "application/json"
        }

        response = requests.post(PROXY_URL, headers=headers, json=payload, timeout=120)
        response.raise_for_status()

        result = response.json()
        ai_message = result["choices"][0]["message"]["content"]

        return jsonify({
            "model": ai_model,
            "response": ai_message,
            "status": "success"
        })

    except requests.exceptions.Timeout:
        return jsonify({"error": "Request timeout"}), 408
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Request failed: {str(e)}"}), 500
    except KeyError:
        return jsonify({"error": "Unexpected response format"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def stream_chat(user_prompt, ai_model, chat_history=[], max_tokens=8000):
    try:
        if not user_prompt:
            return jsonify({"error": "Prompt is required"}), 400
        
        if len(user_prompt) > 50000:
            return jsonify({"error": "Prompt too long (max 50,000 characters)"}), 400

        available_models = models_data.get("available_models", {})
        if ai_model not in available_models:
            return jsonify({"error": "Model not found"}), 400

        system_prompt = prompt_data.get("system_prompt", "")

        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        for msg in chat_history:
            messages.append({
                "role": msg.get("role"),
                "content": msg.get("content")
            })
        
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": ai_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True
        }

        headers = {
            "Authorization": f"Bearer {PROXY_API_KEY}",
            "Content-Type": "application/json"
        }

        response = requests.post(PROXY_URL, headers=headers, json=payload, timeout=120, stream=True)
        response.raise_for_status()

        def generate():
            full_response = ""
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            yield f"data: {json.dumps({'done': True, 'full_response': full_response})}\n\n"
                            break
                        try:
                            chunk_data = json.loads(data)
                            if 'choices' in chunk_data and len(chunk_data['choices']) > 0:
                                delta = chunk_data['choices'][0].get('delta', {})
                                if 'content' in delta:
                                    content = delta['content']
                                    full_response += content
                                    yield f"data: {json.dumps({'content': content, 'model': ai_model})}\n\n"
                        except json.JSONDecodeError:
                            continue

        return Response(stream_with_context(generate()), content_type='text/plain')

    except requests.exceptions.Timeout:
        return jsonify({"error": "Request timeout"}), 408
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Request failed: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000)