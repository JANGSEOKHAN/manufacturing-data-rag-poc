import React, { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './App.css'

const API_BASE = '/api'

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [chatHistory, setChatHistory] = useState([])
  const [currentChatId, setCurrentChatId] = useState(null)
  const [uploadStatus, setUploadStatus] = useState(null) // {filename, status, message, progress}
  const messagesEndRef = useRef(null)

  useEffect(() => {
    loadChatHistory()
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  const loadChatHistory = async () => {
    // 백엔드에서 채팅 히스토리 로드
    try {
      const res = await axios.get(`${API_BASE}/chat_history`)
      const history = res.data.history || []
      setChatHistory(history)
    } catch (e) {
      console.error('Failed to load chat history:', e)
      setChatHistory([])
    }
  }

  const saveChatToHistory = async (title, chatId = null, messagesToSave = null) => {
    const id = chatId || Date.now()
    const messagesToUse = messagesToSave !== null ? messagesToSave : messages
    
    try {
      console.log('[DEBUG] Saving chat history - id:', id, 'title:', title, 'messages count:', messagesToUse.length)
      await axios.post(`${API_BASE}/chat_history`, {
        chat_id: id,
        title: title,
        messages: messagesToUse,
        timestamp: new Date().toISOString()
      })
      console.log('[DEBUG] Chat history saved, reloading chat list in background')
      
      // 히스토리 목록 새로고침 (백그라운드에서 실행, await 안 함)
      loadChatHistory().catch(e => console.error('Failed to reload chat history:', e))
      return id
    } catch (e) {
      console.error('[ERROR] Failed to save chat history:', e)
      return id
    }
  }

  const loadChatMessages = async (chatId) => {
    try {
      const res = await axios.get(`${API_BASE}/chat_history/${chatId}`)
      const messages = res.data.messages || []
      if (messages.length > 0) {
        setMessages(messages)
        setCurrentChatId(chatId)
        return true
      }
    } catch (e) {
      console.error('Failed to load chat messages:', e)
    }
    return false
  }

  const deleteChat = async (chatId, e) => {
    e.stopPropagation()
    try {
      await axios.delete(`${API_BASE}/chat_history/${chatId}`)
      
      // 히스토리 목록 새로고침
      await loadChatHistory()
      
      if (currentChatId === chatId) {
        setMessages([])
        setCurrentChatId(null)
      }
    } catch (e) {
      console.error('Failed to delete chat:', e)
    }
  }

  const handleNewChat = async () => {
    setMessages([])
    setInput('')
    const newChatId = Date.now()
    setCurrentChatId(newChatId)
    // 새 채팅을 목록에 추가 (백엔드에 저장)
    const title = '새 채팅'
    await saveChatToHistory(title, newChatId, [])
  }

  const handleResetToHome = () => {
    // 새 채팅 생성하지 않고 메시지만 초기화
    setMessages([])
    setInput('')
    setCurrentChatId(null)
  }

  const handleChatClick = async (chatId) => {
    // 채팅 메시지 로드만 시도, 새 채팅 생성하지 않음
    await loadChatMessages(chatId)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!input.trim() || loading) return

    const userMessage = input.trim()
    setInput('')
    setLoading(true)

    // 첫 메시지면 히스토리에 저장 (이미 새 채팅으로 생성된 경우 제목 업데이트)
    let chatId = currentChatId
    if (messages.length === 0 && currentChatId) {
      // 새 채팅으로 이미 생성된 경우 제목만 업데이트
      const title = userMessage.length > 30 ? userMessage.substring(0, 30) + '...' : userMessage
      await saveChatToHistory(title, currentChatId, [])
    } else if (messages.length === 0) {
      // 새 채팅이 없는 경우 새로 생성
      const title = userMessage.length > 30 ? userMessage.substring(0, 30) + '...' : userMessage
      chatId = await saveChatToHistory(title, null, [])
      setCurrentChatId(chatId)
    }

    // 사용자 메시지 추가
    const newMessages = [...messages, { role: 'user', content: userMessage }]
    setMessages(newMessages)

    try {
      console.log('[DEBUG] Sending RAG query:', userMessage)
      const res = await axios.post(`${API_BASE}/rag_query`, {
        question: userMessage,
        k: 5
      })
      console.log('[DEBUG] Received RAG response:', res.data)

      const answer = res.data.answer || '답변을 생성할 수 없습니다.'
      const sources = res.data.sources || []
      const images = res.data.images || []

      const updatedMessages = [...newMessages, {
        role: 'assistant',
        content: answer,
        sources,
        images
      }]
      console.log('[DEBUG] Updating messages:', updatedMessages)
      setMessages(updatedMessages)
      
      // 메시지 저장 (백엔드)
      if (chatId) {
        console.log('[DEBUG] Saving chat to history, chatId:', chatId)
        // 제목 업데이트 (첫 메시지인 경우)
        const title = messages.length === 0 
          ? (userMessage.length > 30 ? userMessage.substring(0, 30) + '...' : userMessage)
          : chatHistory.find(ch => ch.id === chatId)?.title || '새 채팅'
        await saveChatToHistory(title, chatId, updatedMessages)
        console.log('[DEBUG] Chat saved successfully')
      }
    } catch (error) {
      console.error('Query error:', error)
      const errorMessages = [...newMessages, {
        role: 'assistant',
        content: '오류가 발생했습니다. 다시 시도해주세요.',
        error: true
      }]
      setMessages(errorMessages)
      
      // 에러 메시지도 저장 (백엔드)
      if (chatId) {
        const title = messages.length === 0 
          ? (userMessage.length > 30 ? userMessage.substring(0, 30) + '...' : userMessage)
          : chatHistory.find(ch => ch.id === chatId)?.title || '새 채팅'
        await saveChatToHistory(title, chatId, errorMessages)
      }
    } finally {
      console.log('[DEBUG] Setting loading to false')
      setLoading(false)
    }
  }

  return (
    <div className="app">
      {/* Top Bar */}
      <div className="top-bar">
        <div className="top-bar-left">
          <button 
            className="menu-toggle"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            aria-label="메뉴 토글"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
              <path
                d="M3 12H21M3 6H21M3 18H21"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <span 
            className="app-title-top"
            onClick={handleResetToHome}
            style={{ cursor: 'pointer' }}
          >
            AI KnowledgeOps
          </span>
        </div>
        <div className="top-bar-right">
        </div>
      </div>

      {/* Sidebar */}
      <div className={`sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
        <div className="sidebar-actions">
          <button className="new-chat-btn" onClick={handleNewChat}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
            </svg>
            <span>새 채팅</span>
          </button>
        </div>

        {chatHistory.length > 0 && (
          <div className="sidebar-section">
            <h3 className="sidebar-section-title">최근</h3>
            <div className="chat-history">
              {chatHistory.map((chat) => (
                <div
                  key={chat.id}
                  className={`chat-history-item ${currentChatId === chat.id ? 'active' : ''}`}
                  onClick={() => handleChatClick(chat.id)}
                >
                  <span className="chat-title">{chat.title}</span>
                  <button
                    className="delete-chat-btn"
                    onClick={(e) => deleteChat(chat.id, e)}
                    aria-label="채팅 삭제"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                      <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Main Content */}
      <div className={`main-content ${sidebarOpen ? 'sidebar-open' : 'sidebar-closed'}`}>
        <div className="chat-container">
          <div className="messages-container-wrapper">
            <div className="messages-container">
              {messages.length === 0 && (
                <div className="welcome-message">
                  <h1>AI KnowledgeOps</h1>
                  <p>궁금한 것이 있으면 질문해주세요.</p>
                </div>
              )}

              {messages.map((msg, idx) => (
                <div key={idx} className={`message ${msg.role}`}>
                  <div className="message-content">
                    {msg.role === 'user' ? (
                      <div className="user-message">{msg.content}</div>
                    ) : (
                      <div className="assistant-message">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {msg.content}
                        </ReactMarkdown>
                        
                        {msg.images && msg.images.length > 0 && (
                          <div className="message-images">
                            {msg.images.map((img, imgIdx) => (
                              <img
                                key={imgIdx}
                                src={img.data_uri || img}
                                alt={img.filename || `Reference ${imgIdx + 1}`}
                                className="reference-image"
                                title={img.filename}
                              />
                            ))}
                          </div>
                        )}

                        {msg.sources && msg.sources.length > 0 && (
                          <div className="message-sources">
                            <h4>📄 참조 문서</h4>
                            {msg.sources.map((source, srcIdx) => (
                              <div key={srcIdx} className="source-item">
                                <span className="source-file">{source.filename || source.file}</span>
                                {source.similarity_score && (
                                  <span className="similarity-score">
                                    유사도: {(source.similarity_score * 100).toFixed(1)}%
                                  </span>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {loading && (
                <div className="message assistant">
                  <div className="message-content">
                    <div className="loading-dots">
                      <span></span>
                      <span></span>
                      <span></span>
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          </div>

          <form className="input-container" onSubmit={handleSubmit}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="메시지를 입력하세요..."
              disabled={loading}
              className="message-input"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="send-button"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path
                  d="M18 2L9 11M18 2L12 18L9 11M18 2L2 8L9 11"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

export default App
