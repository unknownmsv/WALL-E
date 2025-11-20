// Configure marked for Markdown parsing
marked.setOptions({
    highlight: function(code, lang) {
        if (lang && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang }).value;
        }
        return hljs.highlightAuto(code).value;
    },
    breaks: true,
    gfm: true
});

// Application State
const state = {
    currentChatId: null,
    chats: new Map(),
    isWaitingForResponse: false,
    availableModels: [],
    modelsConfig: {},
    sidebarOpen: window.innerWidth > 768,
    currentEditingChat: null,
    currentFile: null,
    apiSettings: {
        useDefault: true,
        customUrl: '',
        customKey: ''
    },
    currentStreamResponse: '',
    isStreaming: false,
    currentStreamMessage: null
};

// DOM Elements
const elements = {
    sidebar: document.getElementById('sidebar'),
    mainContent: document.getElementById('mainContent'),
    overlay: document.getElementById('overlay'),
    menuBtn: document.getElementById('menuBtn'),
    newChatBtn: document.getElementById('newChatBtn'),
    quickNewChat: document.getElementById('quickNewChat'),
    chatHistory: document.getElementById('chatHistory'),
    chatContainer: document.getElementById('chatContainer'),
    welcomeState: document.getElementById('welcomeState'),
    textInput: document.getElementById('textInput'),
    modelSelector: document.getElementById('modelSelector'),
    sendBtn: document.getElementById('sendBtn'),
    attachmentBtn: document.getElementById('attachmentBtn'),
    fileInput: document.getElementById('fileInput'),
    fileInfo: document.getElementById('fileInfo'),
    renameModal: document.getElementById('renameModal'),
    renameInput: document.getElementById('renameInput'),
    closeRenameModal: document.getElementById('closeRenameModal'),
    cancelRename: document.getElementById('cancelRename'),
    confirmRename: document.getElementById('confirmRename')
};

// Get current API configuration
function getApiConfig() {
    return {
        url: 'http://127.0.0.1:5000',
        key: 'your-secret-key-here'
    };
}

// Initialize Application
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
    setupEventListeners();
    loadAvailableModels();
    loadChatsFromBackend();
    updateSidebarState();
});

function initializeApp() {
    // Auto-resize textarea
    elements.textInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        updateSendButtonState();
    });

    // Update send button state
    elements.textInput.addEventListener('input', updateSendButtonState);
}

function setupEventListeners() {
    // Sidebar toggle
    elements.menuBtn.addEventListener('click', toggleSidebar);
    elements.overlay.addEventListener('click', closeSidebar);

    // New chat buttons
    elements.newChatBtn.addEventListener('click', createNewChat);
    elements.quickNewChat.addEventListener('click', createNewChat);

    // Send message
    elements.sendBtn.addEventListener('click', sendMessage);
    elements.textInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // File upload
    elements.fileInput.addEventListener('change', handleFileUpload);

    // Model selector
    elements.modelSelector.addEventListener('change', function() {
        if (state.currentChatId) {
            const chat = state.chats.get(state.currentChatId);
            if (chat) {
                chat.model = this.value;
                saveChatToBackend(chat);
            }
        }
    });

    // Modal events
    elements.closeRenameModal.addEventListener('click', closeRenameModal);
    elements.cancelRename.addEventListener('click', closeRenameModal);
    elements.confirmRename.addEventListener('click', confirmRename);
    elements.renameInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            confirmRename();
        }
    });

    // Close modal on backdrop click
    elements.renameModal.addEventListener('click', function(e) {
        if (e.target === this) {
            closeRenameModal();
        }
    });
}

function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    // Check file extension
    const allowedExtensions = ['.py', '.js', '.html', '.rs', '.ts', '.css'];
    const fileExtension = '.' + file.name.split('.').pop().toLowerCase();
    
    if (!allowedExtensions.includes(fileExtension)) {
        alert('Please select a valid code file: .py, .js, .html, .rs, .ts, .css');
        elements.fileInput.value = '';
        return;
    }

    state.currentFile = file;
    
    // Show file info
    elements.fileInfo.textContent = `📄 ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    elements.fileInfo.classList.add('visible');

    // Read file content and add to message input
    const reader = new FileReader();
    reader.onload = function(e) {
        const fileContent = e.target.result;
        elements.textInput.value = `Please analyze this ${fileExtension} file:\n\`\`\`${fileExtension.substring(1)}\n${fileContent}\n\`\`\``;
        elements.textInput.style.height = 'auto';
        elements.textInput.style.height = (elements.textInput.scrollHeight) + 'px';
        updateSendButtonState();
    };
    reader.readAsText(file);
}

function toggleSidebar() {
    state.sidebarOpen = !state.sidebarOpen;
    updateSidebarState();
}

function openSidebar() {
    state.sidebarOpen = true;
    updateSidebarState();
}

function closeSidebar() {
    state.sidebarOpen = false;
    updateSidebarState();
}

function updateSidebarState() {
    if (window.innerWidth > 768) {
        // Desktop
        if (state.sidebarOpen) {
            elements.sidebar.classList.remove('collapsed');
            elements.mainContent.classList.remove('full-width');
        } else {
            elements.sidebar.classList.add('collapsed');
            elements.mainContent.classList.add('full-width');
        }
        elements.overlay.classList.remove('active');
    } else {
        // Mobile
        if (state.sidebarOpen) {
            elements.sidebar.classList.add('active');
            elements.overlay.classList.add('active');
        } else {
            elements.sidebar.classList.remove('active');
            elements.overlay.classList.remove('active');
        }
    }
}

function updateSendButtonState() {
    const hasText = elements.textInput.value.trim().length > 0;
    elements.sendBtn.disabled = !hasText || state.isWaitingForResponse || state.isStreaming;
}

// Load available models from API
async function loadAvailableModels() {
    try {
        const apiConfig = getApiConfig();
        const response = await fetch(`${apiConfig.url}/api/config`);
        const data = await response.json();
        
        if (data.models && data.models.available_models) {
            state.availableModels = Object.keys(data.models.available_models);
            state.modelsConfig = data.models.available_models;
            populateModelSelector();
        }
        
        // Load suggestions from config
        if (data.prompt && data.prompt.suggestions) {
            populateSuggestions(data.prompt.suggestions);
        }
        
        // Set default model if available
        if (data.models && data.models.default_model) {
            elements.modelSelector.value = data.models.default_model;
        }
    } catch (error) {
        console.error('Error loading config:', error);
        // Fallback models
        state.availableModels = ['openai/gpt-4o-mini', 'google/gemini-2.0-flash-001'];
        populateModelSelector();
    }
}

function populateModelSelector() {
    elements.modelSelector.innerHTML = '';
    
    state.availableModels.forEach(modelId => {
        const option = document.createElement('option');
        option.value = modelId;
        
        // استفاده از نام نمایشی اگر موجود باشد
        const modelConfig = state.modelsConfig && state.modelsConfig[modelId];
        if (modelConfig && modelConfig.name) {
            option.textContent = modelConfig.name;
            option.title = modelConfig.description || modelId;
        } else {
            option.textContent = modelId;
        }
        
        elements.modelSelector.appendChild(option);
    });
    
    // انتخاب مدل پیش‌فرض اگر تنظیم شده
    if (state.modelsConfig && state.modelsConfig.default_model) {
        elements.modelSelector.value = state.modelsConfig.default_model;
    } else if (state.availableModels.length > 0) {
        elements.modelSelector.value = state.availableModels[0];
    }
}

function populateSuggestions(suggestions) {
    const container = document.getElementById('suggestionChips');
    if (!container) return;
    
    container.innerHTML = '';
    suggestions.forEach(suggestion => {
        const chip = document.createElement('div');
        chip.className = 'chip';
        chip.textContent = suggestion;
        chip.dataset.prompt = suggestion;
        chip.addEventListener('click', function() {
            elements.textInput.value = this.dataset.prompt;
            elements.textInput.focus();
            updateSendButtonState();
        });
        container.appendChild(chip);
    });
}

// تابع جدید برای گرفتن اطلاعات مدل
function getModelInfo(modelId) {
    if (state.modelsConfig && state.modelsConfig[modelId]) {
        return state.modelsConfig[modelId];
    }
    return {
        name: modelId,
        description: modelId,
        provider: 'unknown',
        category: 'general',
        max_tokens: 8000
    };
}

async function createNewChat() {
    const chatId = 'chat_' + Date.now();
    const chat = {
        id: chatId,
        title: 'New Chat',
        messages: [],
        createdAt: new Date().toISOString(),
        model: elements.modelSelector.value,
        pinned: false
    };

    try {
        const savedChat = await saveChatToBackend(chat);
        state.chats.set(chatId, savedChat);
        state.currentChatId = chatId;
        
        renderChatHistory();
        renderCurrentChat();
        closeSidebar();
        
        elements.textInput.focus();
    } catch (error) {
        console.error('Error creating chat:', error);
        alert('Error creating new chat: ' + error.message);
    }
}

async function sendMessage() {
    const message = elements.textInput.value.trim();
    if (!message || state.isWaitingForResponse || state.isStreaming) return;

    // Add user message
    await addMessageToChat('user', message);
    elements.textInput.value = '';
    elements.textInput.style.height = 'auto';
    updateSendButtonState();

    // Clear file info
    if (state.currentFile) {
        state.currentFile = null;
        elements.fileInfo.classList.remove('visible');
        elements.fileInput.value = '';
    }

    // Show typing indicator
    showTypingIndicator();
    state.isWaitingForResponse = true;
    state.isStreaming = true;
    state.currentStreamResponse = '';

    try {
        // Create streaming message
        state.currentStreamMessage = {
            role: 'assistant',
            content: '',
            timestamp: new Date().toISOString(),
            liked: null
        };
        
        // Show empty streaming message
        const streamMessageElement = renderStreamingMessage(state.currentStreamMessage);

        // Prepare chat history for API
        let chatHistory = [];
        if (state.currentChatId) {
            const chat = state.chats.get(state.currentChatId);
            if (chat && chat.messages.length > 0) {
                // Send all messages except the new one we just added
                chatHistory = chat.messages.slice(0, -1).map(msg => ({
                    role: msg.role,
                    content: msg.content
                }));
            }
        }

        // Get model-specific max_tokens
        const modelInfo = getModelInfo(elements.modelSelector.value);
        const maxTokens = modelInfo.max_tokens || 8000;

        // Send streaming request with chat history
        const apiConfig = getApiConfig();
        const response = await fetch(`${apiConfig.url}/api/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': apiConfig.key
            },
            body: JSON.stringify({
                prompt: message,
                model: elements.modelSelector.value,
                stream: true,
                chat_history: chatHistory,
                max_tokens: maxTokens
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        // Remove typing indicator
        removeTypingIndicator();

        while (true) {
            const { value, done } = await reader.read();
            
            if (done) {
                break;
            }

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    
                    if (data === '') continue;
                    if (data === '[DONE]') continue;
                    
                    try {
                        const parsed = JSON.parse(data);
                        
                        if (parsed.done) {
                            // End of stream
                            state.isStreaming = false;
                            state.isWaitingForResponse = false;
                            
                            // Save final message
                            if (state.currentChatId && state.currentStreamMessage) {
                                const chat = state.chats.get(state.currentChatId);
                                if (chat) {
                                    // Add tools to final message
                                    addMessageTools(streamMessageElement, state.currentStreamMessage.timestamp);
                                    chat.messages.push(state.currentStreamMessage);
                                    await saveChatToBackend(chat);
                                    renderChatHistory();
                                }
                            }
                            
                            state.currentStreamMessage = null;
                            state.currentStreamResponse = '';
                            return;
                        }
                        
                        if (parsed.content) {
                            // Add new content
                            state.currentStreamResponse += parsed.content;
                            updateStreamingMessage(state.currentStreamResponse, streamMessageElement);
                        }
                    } catch (e) {
                        console.error('Error parsing stream data:', e);
                    }
                }
            }
        }

    } catch (error) {
        removeTypingIndicator();
        state.isStreaming = false;
        state.isWaitingForResponse = false;
        
        if (state.currentStreamMessage) {
            state.currentStreamMessage.content = `Connection error: ${error.message}`;
            updateStreamingMessage(state.currentStreamMessage.content);
            
            // Save error message
            if (state.currentChatId) {
                const chat = state.chats.get(state.currentChatId);
                if (chat) {
                    chat.messages.push(state.currentStreamMessage);
                    await saveChatToBackend(chat);
                    renderChatHistory();
                }
            }
        }
        
        state.currentStreamMessage = null;
        state.currentStreamResponse = '';
    }
}

function renderStreamingMessage(message) {
    elements.welcomeState.style.display = 'none';
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message assistant-message`;
    messageDiv.innerHTML = `
        <div class="message-bubble">
            <div class="message-content"></div>
        </div>
    `;
    
    elements.chatContainer.appendChild(messageDiv);
    elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
    
    return messageDiv;
}

function updateStreamingMessage(content, messageElement = null) {
    if (!state.currentStreamMessage) return;
    
    let targetElement = messageElement;
    if (!targetElement) {
        const messageElements = document.querySelectorAll('.message');
        targetElement = messageElements[messageElements.length - 1];
    }
    
    if (targetElement && targetElement.querySelector('.message-content')) {
        const messageContent = targetElement.querySelector('.message-content');
        state.currentStreamMessage.content = content;
        
        // Render markdown for new content
        let formattedContent = marked.parse(content);
        
        // Add copy buttons for code blocks
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = formattedContent;
        
        tempDiv.querySelectorAll('pre').forEach(pre => {
            const copyBtn = document.createElement('button');
            copyBtn.className = 'copy-code-btn';
            copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copy';
            copyBtn.onclick = function() {
                const code = pre.querySelector('code').textContent;
                navigator.clipboard.writeText(code).then(() => {
                    copyBtn.innerHTML = '<i class="fas fa-check"></i> Copied!';
                    setTimeout(() => {
                        copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copy';
                    }, 2000);
                });
            };
            pre.style.position = 'relative';
            if (!pre.querySelector('.copy-code-btn')) {
                pre.appendChild(copyBtn);
            }
        });
        
        messageContent.innerHTML = tempDiv.innerHTML;
        
        // Scroll to bottom
        elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
    }
}

function addMessageTools(messageElement, timestamp) {
    const messageBubble = messageElement.querySelector('.message-bubble');
    const toolsDiv = document.createElement('div');
    toolsDiv.className = 'message-tools';
    toolsDiv.innerHTML = `
        <button class="tool-btn like" onclick="rateMessage('${timestamp}', true)">
            <i class="fas fa-thumbs-up"></i>
        </button>
        <button class="tool-btn dislike" onclick="rateMessage('${timestamp}', false)">
            <i class="fas fa-thumbs-down"></i>
        </button>
        <button class="tool-btn" onclick="copyMessageToClipboard('${timestamp}')">
            <i class="fas fa-copy"></i>
        </button>
    `;
    messageBubble.appendChild(toolsDiv);
}

async function addMessageToChat(role, content) {
    if (!state.currentChatId) {
        await createNewChat();
    }

    const chat = state.chats.get(state.currentChatId);
    if (!chat) return;

    const message = {
        role: role,
        content: content,
        timestamp: new Date().toISOString(),
        liked: null
    };

    chat.messages.push(message);

    // Update chat title if first user message
    if (role === 'user' && chat.messages.length === 1) {
        chat.title = content.substring(0, 30) + (content.length > 30 ? '...' : '');
    }

    // Save to backend immediately
    await saveChatToBackend(chat);
    renderChatHistory();
    renderMessage(message);
}

function renderMessage(message) {
    elements.welcomeState.style.display = 'none';
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${message.role === 'user' ? 'user-message' : 'assistant-message'}`;
    
    let content = message.content;
    if (message.role === 'assistant') {
        content = marked.parse(content);
    } else {
        // Escape HTML for user messages
        content = content.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    
    messageDiv.innerHTML = `
        <div class="message-bubble">
            <div class="message-content">${content}</div>
            ${message.role === 'assistant' ? `
                <div class="message-tools">
                    <button class="tool-btn like" onclick="rateMessage('${message.timestamp}', true)">
                        <i class="fas fa-thumbs-up"></i>
                    </button>
                    <button class="tool-btn dislike" onclick="rateMessage('${message.timestamp}', false)">
                        <i class="fas fa-thumbs-down"></i>
                    </button>
                    <button class="tool-btn" onclick="copyMessageToClipboard('${message.timestamp}')">
                        <i class="fas fa-copy"></i>
                    </button>
                </div>
            ` : ''}
        </div>
    `;
    
    elements.chatContainer.appendChild(messageDiv);
    
    // Add copy buttons to code blocks
    if (message.role === 'assistant') {
        messageDiv.querySelectorAll('pre').forEach(pre => {
            const copyBtn = document.createElement('button');
            copyBtn.className = 'copy-code-btn';
            copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copy';
            copyBtn.onclick = function() {
                const code = pre.querySelector('code').textContent;
                navigator.clipboard.writeText(code).then(() => {
                    copyBtn.innerHTML = '<i class="fas fa-check"></i> Copied!';
                    setTimeout(() => {
                        copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copy';
                    }, 2000);
                });
            };
            pre.style.position = 'relative';
            pre.appendChild(copyBtn);
        });
    }
    
    elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
}

function showTypingIndicator() {
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message assistant-message';
    typingDiv.id = 'typingIndicator';
    
    typingDiv.innerHTML = `
        <div class="message-bubble">
            <div class="typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        </div>
    `;
    
    elements.chatContainer.appendChild(typingDiv);
    elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
}

function removeTypingIndicator() {
    const typingIndicator = document.getElementById('typingIndicator');
    if (typingIndicator) {
        typingIndicator.remove();
    }
}

async function rateMessage(timestamp, liked) {
    if (!state.currentChatId) return;
    
    const chat = state.chats.get(state.currentChatId);
    if (!chat) return;
    
    const message = chat.messages.find(msg => msg.timestamp === timestamp);
    if (message) {
        message.liked = liked;
        await saveChatToBackend(chat);
    }
}

function copyMessageToClipboard(timestamp) {
    if (!state.currentChatId) return;
    
    const chat = state.chats.get(state.currentChatId);
    if (!chat) return;
    
    const message = chat.messages.find(msg => msg.timestamp === timestamp);
    if (message) {
        navigator.clipboard.writeText(message.content).then(() => {
            // Show copy confirmation
            const originalText = event.target.innerHTML;
            event.target.innerHTML = '<i class="fas fa-check"></i>';
            setTimeout(() => {
                event.target.innerHTML = originalText;
            }, 2000);
        });
    }
}

function getTimeSection(date) {
    const now = new Date();
    const chatDate = new Date(date);
    const diffTime = now - chatDate;
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
    
    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays <= 3) return '3 days ago';
    if (diffDays <= 7) return '1 week ago';
    if (diffDays <= 30) return '1 month ago';
    if (diffDays <= 90) return '3 months ago';
    return 'Older';
}

function renderChatHistory() {
    elements.chatHistory.innerHTML = '';
    
    const chatsArray = Array.from(state.chats.values())
        .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    
    if (chatsArray.length === 0) {
        elements.chatHistory.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-secondary);">No chats yet</div>';
        return;
    }
    
    // Group chats by time section
    const timeSections = {
        'Today': [],
        'Yesterday': [],
        '3 days ago': [],
        '1 week ago': [],
        '1 month ago': [],
        '3 months ago': [],
        'Older': []
    };
    
    chatsArray.forEach(chat => {
        const section = getTimeSection(chat.createdAt);
        timeSections[section].push(chat);
    });
    
    // Render each time section
    Object.entries(timeSections).forEach(([sectionName, sectionChats]) => {
        if (sectionChats.length > 0) {
            const sectionDiv = document.createElement('div');
            sectionDiv.className = 'time-section';
            
            const sectionTitle = document.createElement('div');
            sectionTitle.className = 'time-section-title';
            sectionTitle.textContent = sectionName;
            sectionDiv.appendChild(sectionTitle);
            
            sectionChats.forEach(chat => {
                const chatItem = document.createElement('div');
                chatItem.className = `chat-item ${chat.id === state.currentChatId ? 'active' : ''} ${chat.pinned ? 'pinned' : ''}`;
                chatItem.innerHTML = `
                    <div style="font-weight: 500; margin-bottom: 4px;">${chat.title}</div>
                    <div style="font-size: 12px; color: var(--text-secondary);">
                        ${chat.messages.length} messages
                    </div>
                    <div class="chat-item-actions">
                        <button class="chat-action-btn" onclick="pinChat('${chat.id}')" title="${chat.pinned ? 'Unpin' : 'Pin'}">
                            <i class="fas fa-thumbtack"></i>
                        </button>
                        <button class="chat-action-btn" onclick="renameChat('${chat.id}')" title="Rename">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="chat-action-btn" onclick="deleteChat('${chat.id}')" title="Delete">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                `;
                chatItem.addEventListener('click', (e) => {
                    if (!e.target.closest('.chat-item-actions')) {
                        loadChat(chat.id);
                    }
                });
                
                sectionDiv.appendChild(chatItem);
            });
            
            elements.chatHistory.appendChild(sectionDiv);
        }
    });
}

async function loadChat(chatId) {
    try {
        const chat = await getChatFromBackend(chatId);
        if (chat) {
            state.chats.set(chatId, chat);
            state.currentChatId = chatId;
            renderChatHistory();
            renderCurrentChat();
            closeSidebar();
        }
    } catch (error) {
        console.error('Error loading chat:', error);
        alert('Error loading chat');
    }
}

function renderCurrentChat() {
    elements.chatContainer.innerHTML = '';
    
    if (!state.currentChatId) {
        elements.welcomeState.style.display = 'block';
        return;
    }
    
    const chat = state.chats.get(state.currentChatId);
    if (!chat) return;
    
    elements.welcomeState.style.display = 'none';
    
    // Update model selector
    elements.modelSelector.value = chat.model || state.availableModels[0];
    
    // Render messages
    chat.messages.forEach(message => renderMessage(message));
    
    elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
}

// Chat management functions
async function pinChat(chatId) {
    const chat = state.chats.get(chatId);
    if (chat) {
        chat.pinned = !chat.pinned;
        await saveChatToBackend(chat);
        renderChatHistory();
    }
}

function renameChat(chatId) {
    const chat = state.chats.get(chatId);
    if (chat) {
        state.currentEditingChat = chatId;
        elements.renameInput.value = chat.title;
        elements.renameModal.classList.add('active');
        elements.renameInput.focus();
    }
}

function closeRenameModal() {
    elements.renameModal.classList.remove('active');
    state.currentEditingChat = null;
}

async function confirmRename() {
    if (state.currentEditingChat) {
        const chat = state.chats.get(state.currentEditingChat);
        if (chat) {
            const newTitle = elements.renameInput.value.trim();
            if (newTitle) {
                chat.title = newTitle;
                await saveChatToBackend(chat);
                renderChatHistory();
            }
        }
    }
    closeRenameModal();
}

async function deleteChat(chatId) {
    if (confirm('Are you sure you want to delete this chat?')) {
        try {
            await deleteChatFromBackend(chatId);
            state.chats.delete(chatId);
            if (state.currentChatId === chatId) {
                state.currentChatId = null;
                renderCurrentChat();
            }
            renderChatHistory();
        } catch (error) {
            console.error('Error deleting chat:', error);
            alert('Error deleting chat');
        }
    }
}

function openSettings() {
    window.open('templates/settings.html', '_blank');
}

// Backend API Functions
async function loadChatsFromBackend() {
    try {
        const apiConfig = getApiConfig();
        const response = await fetch(`${apiConfig.url}/api/chats`);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const chats = await response.json();
        state.chats = new Map();
        
        // Load full chat data for each chat
        for (const chatSummary of chats) {
            try {
                const fullChat = await getChatFromBackend(chatSummary.id);
                if (fullChat) {
                    state.chats.set(chatSummary.id, fullChat);
                }
            } catch (error) {
                console.error(`Error loading chat ${chatSummary.id}:`, error);
            }
        }
        
        renderChatHistory();
        
        // Load first chat if available
        if (state.chats.size > 0) {
            const firstChat = Array.from(state.chats.values())[0];
            await loadChat(firstChat.id);
        }
    } catch (error) {
        console.error('Error loading chats from backend:', error);
        // Initialize with empty chats if backend fails
        state.chats = new Map();
        renderChatHistory();
    }
}

async function getChatFromBackend(chatId) {
    try {
        const apiConfig = getApiConfig();
        const response = await fetch(`${apiConfig.url}/api/chats/${chatId}`);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('Error getting chat from backend:', error);
        throw error;
    }
}

async function saveChatToBackend(chat) {
    try {
        const apiConfig = getApiConfig();
        const method = state.chats.has(chat.id) ? 'PUT' : 'POST';
        const url = method === 'POST' 
            ? `${apiConfig.url}/api/chats`
            : `${apiConfig.url}/api/chats/${chat.id}`;
        
        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(chat)
        });
        
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('Error saving chat to backend:', error);
        throw error;
    }
}

async function deleteChatFromBackend(chatId) {
    try {
        const apiConfig = getApiConfig();
        const response = await fetch(`${apiConfig.url}/api/chats/${chatId}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('Error deleting chat from backend:', error);
        throw error;
    }
}

// Make functions globally available for onclick handlers
window.rateMessage = rateMessage;
window.copyMessageToClipboard = copyMessageToClipboard;
window.pinChat = pinChat;
window.renameChat = renameChat;
window.deleteChat = deleteChat;
window.openSettings = openSettings;

// Handle window resize
window.addEventListener('resize', function() {
    updateSidebarState();
});