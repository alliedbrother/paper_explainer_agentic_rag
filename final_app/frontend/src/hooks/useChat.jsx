import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { generateId } from '@/lib/utils'
import { useAuth } from './useAuth'

const ChatContext = createContext(null)

export function ChatProvider({ children }) {
  const { user } = useAuth()
  const [conversations, setConversations] = useState([])
  const [currentConversation, setCurrentConversation] = useState(null)
  const [messages, setMessages] = useState([])
  const [threadId, setThreadId] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [loadingStatus, setLoadingStatus] = useState(null) // Current status message
  const [generationProgress, setGenerationProgress] = useState(null) // Progress for content generators
  const [embeddingProgress, setEmbeddingProgress] = useState(null) // Progress for document embedding
  const [conversationsLoading, setConversationsLoading] = useState(true)
  const [streamingMessage, setStreamingMessage] = useState(null) // For streaming text display
  const [sourcesNeedRefresh, setSourcesNeedRefresh] = useState(false) // Trigger sources refresh

  // Fetch conversations from backend on mount
  useEffect(() => {
    fetchConversations()
  }, [user?.id])

  const fetchConversations = async () => {
    setConversationsLoading(true)
    try {
      const url = user?.id
        ? `/api/v1/chat/conversations?user_id=${user.id}`
        : '/api/v1/chat/conversations'

      const response = await fetch(url)
      if (response.ok) {
        const data = await response.json()
        setConversations(data)
      }
    } catch (err) {
      console.error('Failed to fetch conversations:', err)
    } finally {
      setConversationsLoading(false)
    }
  }

  // Load a specific conversation from backend
  const loadConversation = useCallback(async (conversationId) => {
    try {
      const response = await fetch(`/api/v1/chat/${conversationId}/history`)
      if (response.ok) {
        const data = await response.json()

        // Transform backend messages to frontend format
        const transformedMessages = data.map(msg => ({
          id: msg.id,
          role: msg.role,
          content: msg.content,
          toolCalls: msg.tool_calls?.calls || null,
          timestamp: msg.created_at,
        }))

        setMessages(transformedMessages)
        setThreadId(conversationId)
        setCurrentConversation(conversations.find(c => c.id === conversationId))
      }
    } catch (err) {
      console.error('Failed to load conversation:', err)
    }
  }, [conversations])

  // Start a new conversation
  const newConversation = useCallback(() => {
    const newThreadId = generateId()
    setThreadId(newThreadId)
    setMessages([])
    setCurrentConversation(null)
  }, [])

  // Delete a conversation
  const deleteConversation = useCallback(async (conversationId) => {
    try {
      const response = await fetch(`/api/v1/chat/conversations/${conversationId}`, {
        method: 'DELETE',
      })

      if (response.ok) {
        setConversations(prev => prev.filter(c => c.id !== conversationId))

        // If deleting current conversation, start a new one
        if (conversationId === threadId) {
          newConversation()
        }
      }
    } catch (err) {
      console.error('Failed to delete conversation:', err)
    }
  }, [threadId, newConversation])

  const sendMessage = useCallback(async (content, selectedSources = null) => {
    if (!content.trim() || isLoading) return

    // Ensure we have a thread ID
    let currentThreadId = threadId
    if (!currentThreadId) {
      currentThreadId = generateId()
      setThreadId(currentThreadId)
    }

    const userMessage = {
      id: generateId(),
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    }

    setMessages(prev => [...prev, userMessage])
    setIsLoading(true)
    setLoadingStatus('Connecting...')

    try {
      // Use streaming endpoint for real-time status updates
      const response = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: content,
          thread_id: currentThreadId,
          user_id: user?.id,
          selected_sources: selectedSources,
          tenant_id: user?.tenant_id,
          department: user?.department,
        }),
      })

      if (response.ok) {
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })

          // Process complete SSE events
          const lines = buffer.split('\n\n')
          buffer = lines.pop() || '' // Keep incomplete data in buffer

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const event = JSON.parse(line.slice(6))

                if (event.type === 'status') {
                  setLoadingStatus(event.message)

                  // Handle content generator progress
                  if (event.status === 'tool_progress') {
                    setGenerationProgress({
                      tool: event.tool,
                      step: event.step,
                      iteration: event.iteration,
                      message: event.message,
                      qualityScore: event.quality_score,
                    })
                  } else if (event.status === 'tool' && event.tool) {
                    // Tool is being called - show progress for generators
                    if (event.tool === 'twitter_generator' || event.tool === 'linkedin_generator') {
                      setGenerationProgress({
                        tool: event.tool,
                        step: 'starting',
                        iteration: 1,
                        message: event.message,
                      })
                    }
                  } else {
                    // Clear generation progress for non-tool-progress status
                    setGenerationProgress(null)
                  }
                } else if (event.type === 'stream_start') {
                  // Start of streaming response - create placeholder message
                  setStreamingMessage({
                    id: generateId(),
                    role: 'assistant',
                    content: '',
                    isStreaming: true,
                    timestamp: new Date().toISOString(),
                  })
                  setLoadingStatus(null) // Clear loading status when streaming starts
                } else if (event.type === 'text_chunk') {
                  // Append text chunk to streaming message
                  setStreamingMessage(prev => prev ? {
                    ...prev,
                    content: prev.content + event.content,
                  } : null)
                } else if (event.type === 'stream_end') {
                  // Streaming complete - finalize the message
                  setStreamingMessage(prev => {
                    if (prev) {
                      const finalMessage = {
                        ...prev,
                        isStreaming: false,
                        toolCalls: event.tool_calls,
                        toolsUsed: event.tools_used,
                        ragContext: event.rag_context,
                        fromCache: event.from_cache || false,
                        cacheInfo: event.cache_info,
                        // HITL approval fields
                        requiresApproval: event.requires_approval,
                        approvalType: event.approval_type,
                        pendingContent: event.pending_content,
                      }
                      setMessages(msgs => [...msgs, finalMessage])
                      fetchConversations()
                    }
                    return null
                  })
                } else if (event.type === 'embedding_progress') {
                  // Handle document embedding progress
                  setEmbeddingProgress(event.data)
                } else if (event.type === 'queue') {
                  // Handle queue status updates (when system is busy)
                  setLoadingStatus(event.message)
                } else if (event.type === 'result') {
                  setGenerationProgress(null) // Clear progress on result
                  setEmbeddingProgress(null) // Clear embedding progress on result
                  const data = event.data
                  const assistantMessage = {
                    id: generateId(),
                    role: 'assistant',
                    content: data.response,
                    toolCalls: data.tool_calls,
                    toolsUsed: data.tools_used,
                    ragContext: data.rag_context,
                    requiresApproval: data.requires_approval,
                    approvalType: data.approval_type,
                    pendingContent: data.pending_content,
                    fromCache: data.from_cache || false,
                    cacheInfo: data.cache_info,
                    timestamp: new Date().toISOString(),
                  }
                  setMessages(prev => [...prev, assistantMessage])
                  fetchConversations()
                } else if (event.type === 'error') {
                  // Handle rate limit errors specially
                  if (event.rate_limit) {
                    const resetIn = event.reset_in || 60
                    const rateLimitMessage = event.message || 'rate limit hit'
                    const errorMessage = {
                      id: generateId(),
                      role: 'assistant',
                      content: `⚠️ **${rateLimitMessage}**\n\nPlease wait **${resetIn} seconds** before trying again.\n\n_Tip: Upgrade your tier for higher limits._`,
                      isError: true,
                      isRateLimit: true,
                      resetIn: resetIn,
                      timestamp: new Date().toISOString(),
                    }
                    setMessages(prev => [...prev, errorMessage])
                    setIsLoading(false)
                    setLoadingStatus(null)
                    return
                  } else if (event.queue_full) {
                    const errorMessage = {
                      id: generateId(),
                      role: 'assistant',
                      content: `⚠️ **System Busy**\n\nThe system is currently at capacity. Please try again in a few moments.`,
                      isError: true,
                      timestamp: new Date().toISOString(),
                    }
                    setMessages(prev => [...prev, errorMessage])
                    setIsLoading(false)
                    setLoadingStatus(null)
                    return
                  } else if (event.timeout) {
                    const errorMessage = {
                      id: generateId(),
                      role: 'assistant',
                      content: `⚠️ **Request Timeout**\n\nYour request timed out while waiting in queue. Please try again.`,
                      isError: true,
                      timestamp: new Date().toISOString(),
                    }
                    setMessages(prev => [...prev, errorMessage])
                    setIsLoading(false)
                    setLoadingStatus(null)
                    return
                  }
                  throw new Error(event.message)
                }
              } catch (parseError) {
                console.error('Failed to parse SSE event:', parseError)
              }
            }
          }
        }
      } else {
        throw new Error('API error')
      }
    } catch (e) {
      console.error('Chat error:', e)
      // Fallback to non-streaming endpoint
      try {
        const response = await fetch('/api/v1/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: content,
            thread_id: currentThreadId,
            user_id: user?.id,
            selected_sources: selectedSources,
            tenant_id: user?.tenant_id,
            department: user?.department,
          }),
        })

        if (response.ok) {
          const data = await response.json()
          const assistantMessage = {
            id: generateId(),
            role: 'assistant',
            content: data.response,
            toolCalls: data.tool_calls,
            toolsUsed: data.tools_used,
            ragContext: data.rag_context,
            requiresApproval: data.requires_approval,
            approvalType: data.approval_type,
            pendingContent: data.pending_content,
            timestamp: new Date().toISOString(),
          }
          setMessages(prev => [...prev, assistantMessage])
          fetchConversations()
        } else {
          throw new Error('Fallback API error')
        }
      } catch (fallbackError) {
        // Simulate response when API is not available
        const assistantMessage = {
          id: generateId(),
          role: 'assistant',
          content: getSimulatedResponse(content, user),
          timestamp: new Date().toISOString(),
        }
        setMessages(prev => [...prev, assistantMessage])
      }
    } finally {
      setIsLoading(false)
      setLoadingStatus(null)
      setGenerationProgress(null)
      setEmbeddingProgress(null)
      setStreamingMessage(null)
    }
  }, [threadId, user, isLoading])

  // Clear current chat (same as new conversation)
  const clearChat = useCallback(() => {
    newConversation()
  }, [newConversation])

  // Send message with attached file
  const sendMessageWithFile = useCallback(async (content, file, addToKnowledgeBase = false) => {
    if (!content.trim() || isLoading || !file) return

    // Ensure we have a thread ID
    let currentThreadId = threadId
    if (!currentThreadId) {
      currentThreadId = generateId()
      setThreadId(currentThreadId)
    }

    const userMessage = {
      id: generateId(),
      role: 'user',
      content,
      attachedFile: {
        name: file.name,
        size: file.size,
      },
      timestamp: new Date().toISOString(),
    }

    setMessages(prev => [...prev, userMessage])
    setIsLoading(true)
    setLoadingStatus('Uploading document...')

    try {
      // Create form data
      const formData = new FormData()
      formData.append('message', content)
      formData.append('thread_id', currentThreadId)
      formData.append('user_id', user?.id || '')
      formData.append('tenant_id', user?.tenant_id || 'default')
      formData.append('department', user?.department || 'general')
      formData.append('add_to_knowledge_base', addToKnowledgeBase.toString())
      formData.append('file', file)

      const response = await fetch('/api/v1/chat/stream-with-file', {
        method: 'POST',
        body: formData,
      })

      if (response.ok) {
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })

          // Process complete SSE events
          const lines = buffer.split('\n\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const event = JSON.parse(line.slice(6))

                if (event.type === 'status') {
                  setLoadingStatus(event.message)
                } else if (event.type === 'embedding_progress') {
                  setEmbeddingProgress(event.data)
                } else if (event.type === 'stream_start') {
                  // Start of streaming response
                  setStreamingMessage({
                    id: generateId(),
                    role: 'assistant',
                    content: '',
                    isStreaming: true,
                    timestamp: new Date().toISOString(),
                  })
                  setLoadingStatus(null)
                } else if (event.type === 'text_chunk') {
                  // Append text chunk to streaming message
                  setStreamingMessage(prev => prev ? {
                    ...prev,
                    content: prev.content + event.content,
                  } : null)
                } else if (event.type === 'stream_end') {
                  // Streaming complete - finalize the message
                  setStreamingMessage(prev => {
                    if (prev) {
                      const finalMessage = {
                        ...prev,
                        isStreaming: false,
                        toolCalls: event.tool_calls,
                        toolsUsed: event.tools_used,
                        attachedDocument: event.attached_document,
                      }
                      setMessages(msgs => [...msgs, finalMessage])
                      fetchConversations()
                      // Trigger sources refresh if document was added to KB
                      if (event.attached_document?.added_to_kb) {
                        setSourcesNeedRefresh(true)
                      }
                    }
                    return null
                  })
                } else if (event.type === 'result') {
                  // Fallback for non-streaming responses
                  setGenerationProgress(null)
                  setEmbeddingProgress(null)
                  const data = event.data
                  const assistantMessage = {
                    id: generateId(),
                    role: 'assistant',
                    content: data.response,
                    toolCalls: data.tool_calls,
                    toolsUsed: data.tools_used,
                    attachedDocument: data.attached_document,
                    timestamp: new Date().toISOString(),
                  }
                  setMessages(prev => [...prev, assistantMessage])
                  fetchConversations()
                  // Trigger sources refresh if document was added to KB
                  if (data.attached_document?.added_to_kb) {
                    setSourcesNeedRefresh(true)
                  }
                } else if (event.type === 'error') {
                  // Handle rate limit errors specially
                  if (event.rate_limit) {
                    const resetIn = event.reset_in || 60
                    const rateLimitMessage = event.message || 'rate limit hit'
                    const errorMessage = {
                      id: generateId(),
                      role: 'assistant',
                      content: `⚠️ **${rateLimitMessage}**\n\nPlease wait **${resetIn} seconds** before trying again.\n\n_Tip: Upgrade your tier for higher limits._`,
                      isError: true,
                      isRateLimit: true,
                      timestamp: new Date().toISOString(),
                    }
                    setMessages(prev => [...prev, errorMessage])
                    setIsLoading(false)
                    setLoadingStatus(null)
                    return
                  }
                  throw new Error(event.message)
                }
              } catch (parseError) {
                console.error('Failed to parse SSE event:', parseError)
              }
            }
          }
        }
      } else {
        throw new Error('Failed to process document')
      }
    } catch (e) {
      console.error('Chat with file error:', e)
      const errorMessage = {
        id: generateId(),
        role: 'assistant',
        content: `Error processing document: ${e.message}`,
        timestamp: new Date().toISOString(),
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
      setLoadingStatus(null)
      setGenerationProgress(null)
      setEmbeddingProgress(null)
      setStreamingMessage(null)
    }
  }, [threadId, user, isLoading])

  // Approve content (tweet or LinkedIn post) and store in database
  const approveContent = useCallback(async (messageId, approvalType, content, topic) => {
    try {
      const response = await fetch('/api/v1/content/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content_type: approvalType,
          content: content,
          topic: topic || 'Generated content',
          user_id: user?.id,
          thread_id: threadId,
        }),
      })

      if (response.ok) {
        const data = await response.json()
        // Update the message to mark it as approved
        setMessages(prev => prev.map(msg =>
          msg.id === messageId
            ? { ...msg, approved: true, contentId: data.content_id }
            : msg
        ))
        return { success: true, message: data.message, contentId: data.content_id }
      } else {
        const error = await response.json()
        return { success: false, message: error.detail || 'Failed to approve content' }
      }
    } catch (err) {
      console.error('Approve content error:', err)
      return { success: false, message: 'Failed to approve content' }
    }
  }, [user?.id, threadId])

  return (
    <ChatContext.Provider value={{
      messages,
      threadId,
      isLoading,
      loadingStatus,
      generationProgress,
      embeddingProgress,
      streamingMessage,
      sourcesNeedRefresh,
      clearSourcesRefresh: () => setSourcesNeedRefresh(false),
      conversations,
      conversationsLoading,
      currentConversation,
      sendMessage,
      sendMessageWithFile,
      clearChat,
      newConversation,
      loadConversation,
      deleteConversation,
      refreshConversations: fetchConversations,
      approveContent,
    }}>
      {children}
    </ChatContext.Provider>
  )
}

export function useChat() {
  const context = useContext(ChatContext)
  if (!context) {
    throw new Error('useChat must be used within a ChatProvider')
  }
  return context
}

function getSimulatedResponse(content, user) {
  const lower = content.toLowerCase()

  if (lower.includes('tweet')) {
    return `**Tweet Generator**

Here's a draft tweet about "${content.replace(/write a tweet about|create a tweet about|tweet about/gi, '').trim()}":

---

🚀 AI is transforming how we approach research and learning. The future is collaborative intelligence - humans and AI working together.

#AI #Innovation #Research

---

*Quality Score: 8.2/10*

Would you like me to refine this or generate a new version?`
  }

  if (lower.includes('linkedin')) {
    return `**LinkedIn Post Generated**

Here's your post about "${content.replace(/write a linkedin post about|create a linkedin post about|linkedin post about/gi, '').trim()}":

---

The landscape of AI is evolving rapidly.

Here's what I've observed:

→ Tools are becoming more accessible
→ The learning curve is flattening
→ But expertise still matters

The real opportunity isn't in replacing human judgment - it's in augmenting it.

What's your experience with AI tools in your work?

#AI #MachineLearning #FutureOfWork

---

*Quality Score: 8.5/10 | 2 iterations*`
  }

  if (lower.includes('expense') || lower.includes('spend')) {
    return `**Expense Manager**

Current expense summary for your account:

| Category | Total | Count |
|----------|-------|-------|
| Food | $0.00 | 0 |
| Transport | $0.00 | 0 |

*No expenses recorded yet. Try: "Add $25 expense for lunch in food category"*`
  }

  return `Hello! I'm your AI research assistant. I can help you with:

• 📚 **RAG Queries** - Search embedded research papers
• 🐦 **Tweet Generation** - Create engaging tweets with critique loop
• 💼 **LinkedIn Posts** - Generate professional content
• 💰 **Expense Tracking** - Manage your expenses
• 🧮 **Calculations** - Evaluate math expressions

**Your context:**
- Tenant: ${user?.tenant_id || 'Not set'}
- Department: ${user?.department || 'Not set'}
- Access Level: ${user?.accessLevel || 'public'}

Try asking me to write a tweet or create a LinkedIn post!`
}
