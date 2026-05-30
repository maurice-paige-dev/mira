import { useState, useRef, useEffect } from 'react';
import './ChatBot.css';

const API_URL = 'http://localhost:8000';

const SUGGESTED_QUESTIONS = [
  'What is the average shipping cost for Queso Cabrales?',
  'Which shipper is cheapest for shipping?',
  'Shipping costs for orders shipped to France',
  'What is the most expensive product to ship?',
  'How many third-party vendors does the company work with?',
  'Which third-party vendors supply Tofu?',
  'How does vendor warehouse proximity affect shipping costs?',
  'Compare shipping costs between Federal Shipping and Speedy Express',
];

function ChatBot() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(true);
  const [error, setError] = useState(null);
  const [expandedResult, setExpandedResult] = useState(null);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input on load
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function addMessage(role, content, results = null) {
    setMessages((prev) => [
      ...prev,
      { role, content, results, id: Date.now() + Math.random() },
    ]);
  }

  async function handleSend(userQuery) {
    const query = (userQuery || input).trim();
    if (!query || loading) return;

    setInput('');
    setShowSuggestions(false);
    setError(null);

    // Add user message
    addMessage('user', query);

    // Add a loading message placeholder
    setLoading(true);
    const loadingId = Date.now() + Math.random();
    setMessages((prev) => [
      ...prev,
      { role: 'assistant', content: '...', loading: true, id: loadingId },
    ]);

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, n_results: 7 }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server error: ${response.status}`);
      }

      const data = await response.json();

      // Remove the loading message
      setMessages((prev) => prev.filter((m) => m.id !== loadingId));

      // Add the actual response
      addMessage('assistant', data.answer, data.results);
    } catch (err) {
      // Remove loading message
      setMessages((prev) => prev.filter((m) => m.id !== loadingId));
      setError(err.message);
      addMessage(
        'assistant',
        `❌ Error: ${err.message}. Make sure the API server is running on port 8000.`
      );
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleSuggestionClick(q) {
    handleSend(q);
  }

  function toggleExpand(id) {
    setExpandedResult(expandedResult === id ? null : id);
  }

  function handleClearChat() {
    setMessages([]);
    setShowSuggestions(true);
    setError(null);
    setExpandedResult(null);
  }

  function formatAnswer(text) {
    // Convert markdown-like formatting
    let formatted = text
      .replace(/\n/g, '<br/>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    return formatted;
  }

  return (
    <div className="chatbot-container">
      {/* Header */}
      <div className="chatbot-header">
        <div className="chatbot-header-left">
          <div className="chatbot-avatar">
            <span>🤖</span>
          </div>
          <div>
            <h1 className="chatbot-title">Shipping Advisor</h1>
            <p className="chatbot-subtitle">
              Ask about inventory, purchases & shipping
            </p>
          </div>
        </div>
        <button
          className="chatbot-clear-btn"
          onClick={handleClearChat}
          title="Clear conversation"
        >
          ✕
        </button>
      </div>

      {/* Messages area */}
      <div className="chatbot-messages">
        {messages.length === 0 && showSuggestions && (
          <div className="chatbot-welcome">
            <div className="chatbot-welcome-icon">🚢</div>
            <h2>Welcome to the Shipping Cost Advisor!</h2>
            <p>
              I can answer questions about your inventory, purchase orders,
              shipping orders, and vendor data. Try one of the examples below
              or type your own question.
            </p>
            <div className="chatbot-suggestions">
              {SUGGESTED_QUESTIONS.map((q, i) => (
                <button
                  key={i}
                  className="suggestion-chip"
                  onClick={() => handleSuggestionClick(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`chatbot-message ${
              msg.role === 'user' ? 'message-user' : 'message-assistant'
            } ${msg.loading ? 'message-loading' : ''}`}
          >
            <div className="message-avatar">
              {msg.role === 'user' ? '👤' : '🤖'}
            </div>
            <div className="message-content">
              {msg.loading ? (
                <div className="loading-dots">
                  <span className="dot"></span>
                  <span className="dot"></span>
                  <span className="dot"></span>
                </div>
              ) : (
                <>
                  <div
                    className="message-text"
                    dangerouslySetInnerHTML={{
                      __html: formatAnswer(msg.content),
                    }}
                  />
                  {msg.results && msg.results.length > 0 && (
                    <div className="message-results">
                      <button
                        className="toggle-results-btn"
                        onClick={() => toggleExpand(msg.id)}
                      >
                        {expandedResult === msg.id
                          ? '▲ Hide Details'
                          : '▼ Show Details'}
                        <span className="result-count">
                          {msg.results.length} results
                        </span>
                      </button>
                      {expandedResult === msg.id && (
                        <div className="results-list">
                          {msg.results.map((r, i) => (
                            <div key={i} className="result-item">
                              <div className="result-header">
                                <span className="result-number">#{i + 1}</span>
                                <span className="result-source">
                                  {r.metadata?.source || 'unknown'}
                                </span>
                                <span className="result-similarity">
                                  {(r.similarity * 100).toFixed(1)}% match
                                </span>
                              </div>
                              <div className="result-meta">
                                {r.metadata?.product_name && (
                                  <span className="meta-tag product-tag">
                                    🏷️ {r.metadata.product_name}
                                  </span>
                                )}
                                {r.metadata?.shipper && (
                                  <span className="meta-tag shipper-tag">
                                    📦 {r.metadata.shipper}
                                  </span>
                                )}
                                {r.metadata?.vendor_name && (
                                  <span className="meta-tag vendor-tag">
                                    🏭 {r.metadata.vendor_name}
                                  </span>
                                )}
                                {r.metadata?.customer && (
                                  <span className="meta-tag customer-tag">
                                    👥 {r.metadata.customer}
                                  </span>
                                )}
                                {(r.metadata?.total_price ||
                                  r.metadata?.total_price === 0) && (
                                  <span className="meta-tag price-tag">
                                    💰 ${r.metadata.total_price}
                                  </span>
                                )}
                              </div>
                              <p className="result-text">{r.text}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        ))}

        {error && (
          <div className="chatbot-error-banner">
            ⚠️ {error}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="chatbot-input-area">
        <div className="input-wrapper">
          <textarea
            ref={inputRef}
            className="chatbot-input"
            placeholder="Ask about inventory, shipping costs, purchase orders..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={loading}
          />
          <button
            className="chatbot-send-btn"
            onClick={() => handleSend()}
            disabled={!input.trim() || loading}
          >
            {loading ? '⏳' : '➤'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ChatBot;