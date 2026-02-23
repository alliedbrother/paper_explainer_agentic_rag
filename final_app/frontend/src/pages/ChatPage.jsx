import { useState, useRef, useEffect } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { useChat } from '@/hooks/useChat'
import { MessageContent } from '@/components/MessageContent'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Label } from '@/components/ui/label'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Send,
  RotateCcw,
  Sparkles,
  Copy,
  Check,
  Wrench,
  ChevronDown,
  ChevronLeft,
  FileText,
  Calculator,
  DollarSign,
  Search,
  MessageSquare,
  Twitter,
  Linkedin,
  BookOpen,
  Loader2,
  X,
  Upload,
  Eye,
  EyeOff,
  CheckCircle,
  AlertCircle,
  Terminal,
  Database,
  User,
  Building,
  Users,
  Type,
  Table,
  Image,
  Maximize2,
  Minimize2,
  Trash2,
} from 'lucide-react'
import { cn, formatTime } from '@/lib/utils'

// Tool icons mapping
const toolIcons = {
  calculator: Calculator,
  expense_manager: DollarSign,
  rag_retriever: Search,
  general_llm: MessageSquare,
  twitter_generator: Twitter,
  linkedin_generator: Linkedin,
  document_embedder: BookOpen,
}

// Tool display names
const toolNames = {
  calculator: 'Calculator',
  expense_manager: 'Expense Manager',
  rag_retriever: 'RAG Search',
  general_llm: 'General LLM',
  twitter_generator: 'Tweet Generator',
  linkedin_generator: 'LinkedIn Generator',
  document_embedder: 'Document Embedder',
}

function ToolBadge({ name }) {
  const Icon = toolIcons[name] || Wrench
  const displayName = toolNames[name] || name

  return (
    <Badge variant="secondary" className="gap-1 text-xs">
      <Icon className="h-3 w-3" />
      {displayName}
    </Badge>
  )
}

function RAGContextDisplay({ ragContext }) {
  const [isOpen, setIsOpen] = useState(false)

  if (!ragContext || !ragContext.chunks || ragContext.chunks.length === 0) return null

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen} className="mt-2">
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1 h-7 px-2">
          <Search className="h-3 w-3" />
          <span className="text-xs">{ragContext.chunks.length} RAG Chunk(s) Retrieved</span>
          <ChevronDown className={cn("h-3 w-3 transition-transform", isOpen && "rotate-180")} />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 space-y-2">
        <div className="p-3 rounded-lg bg-primary/10 border border-primary/20">
          <div className="flex items-center gap-2 mb-1">
            <Search className="h-3 w-3 text-primary" />
            <span className="text-xs font-medium text-primary">Query sent to Qdrant:</span>
          </div>
          <p className="text-sm font-mono bg-background/50 p-2 rounded">
            "{ragContext.query}"
          </p>
        </div>

        {ragContext.chunks.map((chunk, i) => (
          <div key={i} className="p-3 rounded-lg bg-muted/50 border text-sm">
            <div className="flex items-start justify-between gap-2 mb-2">
              <div className="flex-1">
                {chunk.paper_title && (
                  <p className="font-medium text-primary">{chunk.paper_title}</p>
                )}
                <div className="flex gap-2 flex-wrap mt-1">
                  {chunk.arxiv_id && (
                    <Badge variant="outline" className="text-xs">
                      arXiv: {chunk.arxiv_id}
                    </Badge>
                  )}
                  {chunk.section && (
                    <Badge variant="outline" className="text-xs">
                      {chunk.section}
                    </Badge>
                  )}
                  {chunk.relevance_score && (
                    <Badge variant="secondary" className="text-xs">
                      Score: {chunk.relevance_score.toFixed(2)}
                    </Badge>
                  )}
                </div>
              </div>
            </div>
            <p className="text-muted-foreground text-xs leading-relaxed">
              {chunk.content}
            </p>
          </div>
        ))}
      </CollapsibleContent>
    </Collapsible>
  )
}

function ToolsUsedDisplay({ tools }) {
  const [isOpen, setIsOpen] = useState(false)

  if (!tools || tools.length === 0) return null

  const uniqueTools = [...new Map(tools.map(t => [t.name, t])).values()]

  return (
    <div className="mt-2 pt-2 border-t border-border/50">
      <div className="flex flex-wrap gap-1 mb-1">
        {uniqueTools.map((tool, i) => (
          <ToolBadge key={i} name={tool.name} />
        ))}
      </div>

      {tools.some(t => t.result) && (
        <Collapsible open={isOpen} onOpenChange={setIsOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="gap-1 h-6 px-2 text-xs">
              View Tool Details
              <ChevronDown className={cn("h-3 w-3 transition-transform", isOpen && "rotate-180")} />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2 space-y-2">
            {tools.map((tool, i) => (
              <div key={i} className="p-2 rounded bg-muted/30 text-xs">
                <div className="flex items-center gap-1 font-medium mb-1">
                  <Wrench className="h-3 w-3" />
                  {toolNames[tool.name] || tool.name}
                </div>
                {tool.args && Object.keys(tool.args).length > 0 && (
                  <div className="text-muted-foreground mb-1">
                    Args: {JSON.stringify(tool.args)}
                  </div>
                )}
                {tool.result && (
                  <div className="text-muted-foreground max-h-20 overflow-y-auto">
                    Result: {tool.result.slice(0, 200)}{tool.result.length > 200 ? '...' : ''}
                  </div>
                )}
              </div>
            ))}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  )
}

export default function ChatPage() {
  const location = useLocation()
  const { conversationId } = useParams()
  const { user } = useAuth()
  const { messages, threadId, isLoading, loadingStatus, generationProgress, embeddingProgress, streamingMessage, sourcesNeedRefresh, clearSourcesRefresh, sendMessage, sendMessageWithFile, clearChat, loadConversation, approveContent } = useChat()
  const [input, setInput] = useState('')
  const [copiedId, setCopiedId] = useState(null)
  const [approvingId, setApprovingId] = useState(null) // Track which message is being approved
  const [approvalResult, setApprovalResult] = useState(null) // { messageId, success, message }
  const scrollRef = useRef(null)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const logsEndRef = useRef(null)

  // Paper selection state
  const [availableSources, setAvailableSources] = useState([])
  const [selectedSources, setSelectedSources] = useState([])
  const [sourcesLoading, setSourcesLoading] = useState(true)

  // Sidebar tab state
  const [activeTab, setActiveTab] = useState('sources') // 'sources' or 'upload'
  const [sidebarExpanded, setSidebarExpanded] = useState(false) // For maximize/minimize

  // Document Explorer state
  const [explorerDocument, setExplorerDocument] = useState(null) // { id, name, ... }
  const [explorerChunks, setExplorerChunks] = useState([])
  const [explorerLoading, setExplorerLoading] = useState(false)
  const [selectedChunk, setSelectedChunk] = useState(null)
  const [chunkFilter, setChunkFilter] = useState('all') // all, text, image, table
  const [inspectorTab, setInspectorTab] = useState('content') // content, enhanced
  const [lightboxImage, setLightboxImage] = useState(null)
  const [explorerExpanded, setExplorerExpanded] = useState(false)

  // Upload state - supports multiple files in queue
  const [uploadQueue, setUploadQueue] = useState([]) // Array of { file, status: 'pending'|'processing'|'completed'|'error', progress, jobId, error }
  const [currentUploadIndex, setCurrentUploadIndex] = useState(-1) // Index of currently processing file
  const [uploadVisibility, setUploadVisibility] = useState('public')
  const [isUploading, setIsUploading] = useState(false)

  // Chat file attachment state
  const [chatAttachedFile, setChatAttachedFile] = useState(null)
  const [addToKnowledgeBase, setAddToKnowledgeBase] = useState(false)
  const chatFileInputRef = useRef(null)

  // Computed values for upload queue (must be before useEffects that reference them)
  const currentUploadItem = currentUploadIndex >= 0 ? uploadQueue[currentUploadIndex] : null
  const completedCount = uploadQueue.filter(it => it.status === 'completed').length
  const errorCount = uploadQueue.filter(it => it.status === 'error').length
  const pendingCount = uploadQueue.filter(it => it.status === 'pending').length

  // Restore active upload jobs from localStorage on mount
  useEffect(() => {
    const restoreActiveJobs = async () => {
      const stored = localStorage.getItem('rag_active_uploads')
      if (!stored) return

      try {
        const activeJobs = JSON.parse(stored) // Array of { jobId, fileName, visibility }
        if (!activeJobs || activeJobs.length === 0) return

        // Create queue items for active jobs
        const restoredQueue = activeJobs.map((job, index) => ({
          file: { name: job.fileName }, // Minimal file info for display
          status: index === 0 ? 'processing' : 'pending',
          progress: null,
          jobId: job.jobId,
          error: null,
        }))

        setUploadQueue(restoredQueue)
        setUploadVisibility(activeJobs[0]?.visibility || 'public')
        setIsUploading(true)
        setCurrentUploadIndex(0)

        // Start polling the first job
        if (activeJobs[0]?.jobId) {
          pollJobStatusRestored(activeJobs[0].jobId, 0)
        }
      } catch (e) {
        console.error('Failed to restore uploads:', e)
        localStorage.removeItem('rag_active_uploads')
      }
    }

    restoreActiveJobs()
  }, [])

  // Poll job status for restored jobs (separate function to avoid closure issues)
  const pollJobStatusRestored = (jobId, queueIndex) => {
    const poll = async () => {
      try {
        const response = await fetch(`/api/v1/embed-house/job/${jobId}?password=akhilishere`)
        if (!response.ok) {
          // Job might not exist anymore, remove from storage and skip
          removeJobFromStorage(jobId)
          processNextRestoredJob(queueIndex)
          return
        }

        const data = await response.json()
        const progress = {
          ...data.status,
          logs: data.status.logs || [],
          chunks_count: data.chunks_count,
        }

        // Update progress for this file
        setUploadQueue(prev => prev.map((it, i) =>
          i === queueIndex ? { ...it, progress, status: 'processing' } : it
        ))

        if (data.status.vectorization === 'completed') {
          // Mark completed
          setUploadQueue(prev => prev.map((it, i) =>
            i === queueIndex ? { ...it, status: 'completed', progress } : it
          ))
          removeJobFromStorage(jobId)
          processNextRestoredJob(queueIndex)
        } else if (data.status.error_message) {
          // Mark as error
          setUploadQueue(prev => prev.map((it, i) =>
            i === queueIndex ? { ...it, status: 'error', error: data.status.error_message, progress } : it
          ))
          removeJobFromStorage(jobId)
          processNextRestoredJob(queueIndex)
        } else {
          setTimeout(poll, 1000)
        }
      } catch (err) {
        console.error('Poll error:', err)
        setTimeout(poll, 2000)
      }
    }
    poll()
  }

  // Process next restored job
  const processNextRestoredJob = (currentIndex) => {
    setUploadQueue(prev => {
      const nextPending = prev.findIndex((it, i) => i > currentIndex && it.status === 'pending')
      if (nextPending !== -1 && prev[nextPending]?.jobId) {
        setCurrentUploadIndex(nextPending)
        setTimeout(() => pollJobStatusRestored(prev[nextPending].jobId, nextPending), 500)
      } else {
        setIsUploading(false)
        setCurrentUploadIndex(-1)
        fetchSources()
        localStorage.removeItem('rag_active_uploads')
      }
      return prev
    })
  }

  // Helper to save active jobs to localStorage
  const saveJobToStorage = (jobId, fileName, visibility) => {
    const stored = localStorage.getItem('rag_active_uploads')
    const jobs = stored ? JSON.parse(stored) : []
    jobs.push({ jobId, fileName, visibility })
    localStorage.setItem('rag_active_uploads', JSON.stringify(jobs))
  }

  // Helper to remove job from localStorage
  const removeJobFromStorage = (jobId) => {
    const stored = localStorage.getItem('rag_active_uploads')
    if (!stored) return
    const jobs = JSON.parse(stored).filter(j => j.jobId !== jobId)
    if (jobs.length > 0) {
      localStorage.setItem('rag_active_uploads', JSON.stringify(jobs))
    } else {
      localStorage.removeItem('rag_active_uploads')
    }
  }

  // Fetch available sources from Qdrant (re-fetch when user changes)
  useEffect(() => {
    if (user) {
      fetchSources()
    }
  }, [user?.id, user?.tenant_id, user?.department])

  const fetchSources = async () => {
    setSourcesLoading(true)
    try {
      const params = new URLSearchParams()
      if (user?.tenant_id) params.append('tenant_id', user.tenant_id)
      if (user?.department) params.append('department', user.department)
      if (user?.id) params.append('user_id', user.id)

      const response = await fetch(`/api/v1/embed-house/knowledge-base/sources?${params.toString()}`)
      if (response.ok) {
        const data = await response.json()
        setAvailableSources(data.sources || [])
      }
    } catch (err) {
      console.error('Failed to fetch sources:', err)
    } finally {
      setSourcesLoading(false)
    }
  }

  // Load conversation if ID is in URL
  useEffect(() => {
    if (conversationId && conversationId !== threadId) {
      loadConversation(conversationId)
    }
  }, [conversationId])

  // Handle initial prompt from home page
  useEffect(() => {
    if (location.state?.initialPrompt) {
      setInput(location.state.initialPrompt)
      inputRef.current?.focus()
    }
  }, [location.state])

  // Auto-scroll chat to bottom when messages change, streaming updates, or when loading
  useEffect(() => {
    // Use scrollIntoView with block: 'end' to scroll within the container
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [messages, isLoading, loadingStatus, streamingMessage?.content])

  // Refresh sources when a document is added to KB via chat attachment
  useEffect(() => {
    if (sourcesNeedRefresh) {
      fetchSources()
      clearSourcesRefresh()
    }
  }, [sourcesNeedRefresh])

  // Auto-scroll logs to bottom
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [currentUploadItem?.progress?.logs?.length])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    if (chatAttachedFile) {
      // Send message with attached file
      sendMessageWithFile(input, chatAttachedFile, addToKnowledgeBase)
      setInput('')
      setChatAttachedFile(null)
      setAddToKnowledgeBase(false)
    } else {
      // Regular message with optional source selection
      const selectedSourceIds = selectedSources.length > 0
        ? selectedSources.map(s => s.id)
        : null

      sendMessage(input, selectedSourceIds)
      setInput('')
    }
  }

  const handleChatFileSelect = (e) => {
    const file = e.target.files?.[0]
    if (file && file.type === 'application/pdf') {
      setChatAttachedFile(file)
    } else if (file) {
      alert('Please select a PDF file')
    }
    // Reset input so same file can be selected again
    e.target.value = ''
  }

  const removeChatAttachedFile = () => {
    setChatAttachedFile(null)
    setAddToKnowledgeBase(false)
  }

  const handleCopy = async (text, id) => {
    await navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const handleApprove = async (message) => {
    setApprovingId(message.id)
    setApprovalResult(null)

    // Extract topic from the message content or tools used
    let topic = 'Generated content'
    if (message.toolsUsed) {
      const generator = message.toolsUsed.find(t =>
        t.name === 'twitter_generator' || t.name === 'linkedin_generator'
      )
      if (generator?.args?.topic) {
        topic = generator.args.topic
      }
    }

    const result = await approveContent(
      message.id,
      message.approvalType,
      message.pendingContent || message.content,
      topic
    )

    setApprovingId(null)
    setApprovalResult({ messageId: message.id, ...result })

    // Clear result after 3 seconds
    setTimeout(() => setApprovalResult(null), 3000)
  }

  const toggleSource = (source) => {
    setSelectedSources(prev => {
      const isSelected = prev.some(s => s.id === source.id)
      if (isSelected) {
        return prev.filter(s => s.id !== source.id)
      } else {
        return [...prev, source]
      }
    })
  }

  const selectAllSources = () => {
    setSelectedSources([...availableSources])
  }

  const clearAllSources = () => {
    setSelectedSources([])
  }

  // Handle file selection - supports multiple files
  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files || [])
    const pdfFiles = files.filter(f => f.type === 'application/pdf')
    const nonPdfCount = files.length - pdfFiles.length

    if (pdfFiles.length > 0) {
      // Add new files to queue with pending status
      const newQueueItems = pdfFiles.map(file => ({
        file,
        status: 'pending',
        progress: null,
        jobId: null,
        error: null,
      }))
      setUploadQueue(prev => [...prev, ...newQueueItems])
    }

    if (nonPdfCount > 0) {
      alert(`${nonPdfCount} non-PDF file(s) were skipped. Only PDF files are supported.`)
    }

    // Reset input so same file can be selected again
    e.target.value = ''
  }

  // Handle file upload - processes queue sequentially
  const handleUpload = async () => {
    if (uploadQueue.length === 0 || !user) return

    // Find first pending file
    const pendingIndex = uploadQueue.findIndex(item => item.status === 'pending')
    if (pendingIndex === -1) return

    setIsUploading(true)
    processFileAtIndex(pendingIndex)
  }

  // Process a single file at given index
  const processFileAtIndex = async (index) => {
    if (index >= uploadQueue.length) {
      setIsUploading(false)
      setCurrentUploadIndex(-1)
      fetchSources()
      return
    }

    const item = uploadQueue[index]
    if (item.status !== 'pending') {
      // Skip to next pending file
      const nextPending = uploadQueue.findIndex((it, i) => i > index && it.status === 'pending')
      if (nextPending !== -1) {
        processFileAtIndex(nextPending)
      } else {
        setIsUploading(false)
        setCurrentUploadIndex(-1)
        fetchSources()
      }
      return
    }

    setCurrentUploadIndex(index)

    // Update status to processing
    setUploadQueue(prev => prev.map((it, i) =>
      i === index ? { ...it, status: 'processing', progress: null } : it
    ))

    const formData = new FormData()
    formData.append('file', item.file)
    formData.append('password', 'akhilishere')
    formData.append('tenant_id', user.tenant_id || 'default')
    formData.append('department', user.department || 'general')
    formData.append('user_id', user.id || 'anonymous')
    formData.append('visibility', uploadVisibility)
    formData.append('processing_mode', 'hi_res')

    try {
      const response = await fetch('/api/v1/embed-house/upload', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Upload failed')
      }

      const data = await response.json()

      // Update queue with job ID
      setUploadQueue(prev => prev.map((it, i) =>
        i === index ? { ...it, jobId: data.job_id } : it
      ))

      // Save to localStorage for persistence across navigation
      saveJobToStorage(data.job_id, item.file.name, uploadVisibility)

      // Start polling for this file
      pollJobStatus(data.job_id, index)
    } catch (err) {
      // Mark as error and move to next
      setUploadQueue(prev => prev.map((it, i) =>
        i === index ? { ...it, status: 'error', error: err.message } : it
      ))
      // Process next file
      const nextPending = uploadQueue.findIndex((it, i) => i > index && it.status === 'pending')
      if (nextPending !== -1) {
        processFileAtIndex(nextPending)
      } else {
        setIsUploading(false)
        setCurrentUploadIndex(-1)
      }
    }
  }

  // Poll job status for a specific file in queue
  const pollJobStatus = async (jobId, queueIndex) => {
    const poll = async () => {
      try {
        const response = await fetch(`/api/v1/embed-house/job/${jobId}?password=akhilishere`)
        if (!response.ok) return

        const data = await response.json()
        const progress = {
          ...data.status,
          logs: data.status.logs || [],
          chunks_count: data.chunks_count,
        }

        // Update progress for this file
        setUploadQueue(prev => prev.map((it, i) =>
          i === queueIndex ? { ...it, progress } : it
        ))

        if (data.status.vectorization === 'completed') {
          // Mark completed and process next
          setUploadQueue(prev => prev.map((it, i) =>
            i === queueIndex ? { ...it, status: 'completed', progress } : it
          ))

          // Remove from localStorage
          removeJobFromStorage(jobId)

          // Find next pending file
          setUploadQueue(prev => {
            const nextPending = prev.findIndex((it, i) => i > queueIndex && it.status === 'pending')
            if (nextPending !== -1) {
              setTimeout(() => processFileAtIndex(nextPending), 500)
            } else {
              setIsUploading(false)
              setCurrentUploadIndex(-1)
              fetchSources()
            }
            return prev
          })
        } else if (data.status.error_message) {
          // Mark as error and process next
          setUploadQueue(prev => prev.map((it, i) =>
            i === queueIndex ? { ...it, status: 'error', error: data.status.error_message, progress } : it
          ))

          // Remove from localStorage
          removeJobFromStorage(jobId)

          setUploadQueue(prev => {
            const nextPending = prev.findIndex((it, i) => i > queueIndex && it.status === 'pending')
            if (nextPending !== -1) {
              setTimeout(() => processFileAtIndex(nextPending), 500)
            } else {
              setIsUploading(false)
              setCurrentUploadIndex(-1)
            }
            return prev
          })
        } else {
          setTimeout(poll, 1000)
        }
      } catch (err) {
        console.error('Poll error:', err)
        setTimeout(poll, 2000)
      }
    }

    poll()
  }

  // Remove a file from queue
  const removeFromQueue = (index) => {
    if (uploadQueue[index]?.status === 'processing') return // Can't remove while processing
    setUploadQueue(prev => prev.filter((_, i) => i !== index))
  }

  // Reset upload state
  const resetUpload = () => {
    setUploadQueue([])
    setCurrentUploadIndex(-1)
    setUploadVisibility('public')
    localStorage.removeItem('rag_active_uploads')
  }

  // Open document explorer
  const openDocumentExplorer = async (source) => {
    setExplorerDocument(source)
    setExplorerLoading(true)
    setSelectedChunk(null)
    setChunkFilter('all')

    try {
      const response = await fetch(`/api/v1/embed-house/knowledge-base/document/${encodeURIComponent(source.id)}/chunks`)
      if (response.ok) {
        const data = await response.json()
        setExplorerChunks(data.chunks || [])
      } else {
        setExplorerChunks([])
      }
    } catch (err) {
      console.error('Failed to fetch chunks:', err)
      setExplorerChunks([])
    } finally {
      setExplorerLoading(false)
    }
  }

  // Close document explorer
  const closeDocumentExplorer = () => {
    setExplorerDocument(null)
    setExplorerChunks([])
    setSelectedChunk(null)
    setLightboxImage(null)
    setExplorerExpanded(false)
  }

  // Delete document from knowledge base
  const handleDeleteDocument = async (document) => {
    if (!window.confirm(`Delete "${document.name}"? This cannot be undone.`)) {
      return
    }

    try {
      const params = new URLSearchParams()
      params.append('tenant_id', user?.tenant_id || 'default')
      params.append('user_id', user?.id || 'anonymous')

      const response = await fetch(
        `/api/v1/embed-house/knowledge-base/document/${encodeURIComponent(document.id)}?${params.toString()}`,
        { method: 'DELETE' }
      )

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to delete document')
      }

      // Close explorer and refresh sources
      closeDocumentExplorer()
      fetchSources()

    } catch (error) {
      console.error('Delete failed:', error)
      alert(`Failed to delete: ${error.message}`)
    }
  }

  // Filter chunks by type
  const filteredExplorerChunks = explorerChunks.filter(chunk => {
    if (chunkFilter === 'all') return true
    return chunk.content_types?.includes(chunkFilter)
  })

  // Get current processing step for a given progress object
  const getCurrentStep = (progress) => {
    if (!progress) return null
    const steps = ['partitioning', 'chunking', 'summarization', 'vectorization']
    for (const step of steps) {
      if (progress[step] === 'processing') return step
      if (progress[step] === 'error') return `${step} (error)`
    }
    return null
  }

  // Filter logs by step for a given progress object
  const getLogsForStep = (step, progress) => {
    if (!progress?.logs) return []
    const stepKeywords = {
      partitioning: ['PARTITIONING', 'partition', 'Partition', 'elements', 'Elements', 'pages', 'Pages', 'atomic'],
      chunking: ['CHUNKING', 'chunk', 'Chunk', 'Creating semantic'],
      summarization: ['SUMMARISATION', 'SUMMARIZATION', 'summar', 'Summar', 'enhanced', 'Enhanced', 'GPT'],
      vectorization: ['VECTORIZATION', 'vector', 'Vector', 'embed', 'Embed', 'Qdrant', 'upsert', 'STORAGE'],
    }
    const keywords = stepKeywords[step] || []
    return progress.logs.filter(log =>
      keywords.some(kw => log.includes(kw)) ||
      log.includes(`STEP ${['partitioning', 'chunking', 'summarization', 'vectorization'].indexOf(step) + 1}`)
    )
  }

  const initial = user?.email?.[0]?.toUpperCase() || 'U'

  return (
    <div className="h-screen flex animate-fade-in">
      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-2xl font-bold">Chat</h1>
            <p className="text-sm text-muted-foreground">
              Thread: <span className="font-mono">{threadId?.slice(0, 8)}...</span>
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={clearChat} className="gap-2">
            <RotateCcw className="h-4 w-4" />
            New Chat
          </Button>
        </div>

        {/* Chat area */}
        <Card className="flex-1 flex flex-col overflow-hidden min-h-0">
          <ScrollArea className="flex-1 p-4 min-h-0" ref={scrollRef}>
            <div className="space-y-4">
              {messages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full min-h-[400px] text-center">
                  <div className="h-16 w-16 rounded-2xl bg-gradient-to-br from-primary to-orange-400 flex items-center justify-center mb-4">
                    <Sparkles className="h-8 w-8 text-white" />
                  </div>
                  <h2 className="text-xl font-semibold mb-2">Start a conversation</h2>
                  <p className="text-muted-foreground max-w-md mb-4">
                    {selectedSources.length > 0
                      ? `Searching ${selectedSources.length} selected paper${selectedSources.length > 1 ? 's' : ''}. Ask a question about them.`
                      : 'Select papers from the right sidebar to search specific sources, or ask any question.'}
                  </p>
                  <div className="flex flex-wrap gap-2 justify-center">
                    {[
                      'What is the main contribution?',
                      'Explain the methodology',
                      'What are the key findings?',
                    ].map((prompt) => (
                      <Button
                        key={prompt}
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setInput(prompt)
                          inputRef.current?.focus()
                        }}
                      >
                        {prompt}
                      </Button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((message) => (
                <div
                  key={message.id}
                  className={cn(
                    'flex gap-3 animate-fade-in',
                    message.role === 'user' && 'flex-row-reverse'
                  )}
                >
                  <Avatar className="h-8 w-8 shrink-0">
                    <AvatarFallback className={cn(
                      message.role === 'user'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-gradient-to-br from-violet-500 to-purple-500 text-white'
                    )}>
                      {message.role === 'user' ? initial : <Sparkles className="h-4 w-4" />}
                    </AvatarFallback>
                  </Avatar>

                  <div className={cn(
                    'flex flex-col max-w-[80%]',
                    message.role === 'user' && 'items-end'
                  )}>
                    <div
                      className={cn(
                        'rounded-2xl px-4 py-3',
                        message.role === 'user'
                          ? 'bg-primary text-primary-foreground rounded-br-md'
                          : 'bg-muted rounded-bl-md'
                      )}
                    >
                      {/* User message with attached file indicator */}
                      {message.role === 'user' && message.attachedFile && (
                        <div className="flex items-center gap-2 mb-2 pb-2 border-b border-primary-foreground/20">
                          <FileText className="h-4 w-4" />
                          <span className="text-sm">{message.attachedFile.name}</span>
                        </div>
                      )}

                      {message.role === 'user' ? (
                        <div className="whitespace-pre-wrap">
                          {message.content}
                        </div>
                      ) : (
                        message.content ? (
                          <MessageContent content={message.content} />
                        ) : (
                          <span className="text-muted-foreground italic">No content</span>
                        )
                      )}

                      {/* Cached response indicator */}
                      {message.role === 'assistant' && message.fromCache && (
                        <div className="mt-2 pt-2 border-t border-border/50">
                          <Badge variant="secondary" className="bg-emerald-500/20 text-emerald-600 gap-1">
                            <Database className="h-3 w-3" />
                            {message.cacheInfo?.match_type === 'semantic'
                              ? `Cached (${Math.round((message.cacheInfo?.similarity || 0) * 100)}% match)`
                              : 'Cached'}
                          </Badge>
                        </div>
                      )}

                      {/* Assistant response with attached document info */}
                      {message.role === 'assistant' && message.attachedDocument && (
                        <div className="mt-2 pt-2 border-t border-border/50">
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <FileText className="h-3 w-3" />
                            <span>
                              {message.attachedDocument.filename}
                              {' '}({message.attachedDocument.page_count} pages,{' '}
                              {message.attachedDocument.method === 'full_text' ? 'full context' : 'RAG'})
                            </span>
                            {message.attachedDocument.added_to_kb && (
                              <Badge variant="secondary" className="text-xs py-0">
                                Added to KB
                              </Badge>
                            )}
                          </div>
                        </div>
                      )}

                      {message.role === 'assistant' && message.toolsUsed && (
                        <ToolsUsedDisplay tools={message.toolsUsed} />
                      )}

                      {message.role === 'assistant' && message.ragContext && (
                        <RAGContextDisplay ragContext={message.ragContext} />
                      )}

                      {/* Approve Button for Generated Content */}
                      {message.role === 'assistant' && message.requiresApproval && !message.approved && (
                        <div className="mt-3 pt-3 border-t border-border/50">
                          <div className="flex items-center gap-2">
                            <Button
                              size="sm"
                              className="gap-2"
                              onClick={() => handleApprove(message)}
                              disabled={approvingId === message.id}
                            >
                              {approvingId === message.id ? (
                                <>
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                  Saving...
                                </>
                              ) : (
                                <>
                                  <CheckCircle className="h-4 w-4" />
                                  Approve & Save {message.approvalType === 'tweet' ? 'Tweet' : 'Post'}
                                </>
                              )}
                            </Button>
                            <span className="text-xs text-muted-foreground">
                              {message.approvalType === 'tweet' ? 'Save to your tweets' : 'Save to your posts'}
                            </span>
                          </div>
                          {approvalResult?.messageId === message.id && (
                            <div className={cn(
                              "mt-2 text-xs flex items-center gap-1",
                              approvalResult.success ? "text-green-600" : "text-destructive"
                            )}>
                              {approvalResult.success ? (
                                <CheckCircle className="h-3 w-3" />
                              ) : (
                                <AlertCircle className="h-3 w-3" />
                              )}
                              {approvalResult.message}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Already Approved Badge */}
                      {message.role === 'assistant' && message.approved && (
                        <div className="mt-2 pt-2 border-t border-border/50">
                          <Badge variant="secondary" className="bg-green-500/20 text-green-600 gap-1">
                            <CheckCircle className="h-3 w-3" />
                            Saved
                          </Badge>
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                      <span>{formatTime(message.timestamp)}</span>
                      {message.role === 'assistant' && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6"
                          onClick={() => handleCopy(message.content, message.id)}
                        >
                          {copiedId === message.id ? (
                            <Check className="h-3 w-3 text-green-500" />
                          ) : (
                            <Copy className="h-3 w-3" />
                          )}
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              ))}

              {/* Streaming message - appears as text streams in */}
              {streamingMessage && (
                <div className="flex gap-3 animate-fade-in">
                  <Avatar className="h-8 w-8 shrink-0">
                    <AvatarFallback className="bg-gradient-to-br from-violet-500 to-purple-500 text-white">
                      <Sparkles className="h-4 w-4" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="flex flex-col max-w-[80%]">
                    <div className="rounded-2xl rounded-bl-md px-4 py-3 bg-muted">
                      <div className="prose-chat whitespace-pre-wrap">
                        {streamingMessage.content || (
                          <span className="text-muted-foreground italic">Thinking...</span>
                        )}
                        {streamingMessage.isStreaming && streamingMessage.content && (
                          <span className="inline-block w-1.5 h-4 ml-0.5 bg-primary/70 animate-pulse rounded-sm" />
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Loading indicator - only show when not streaming */}
              {isLoading && !streamingMessage && (
                <div className="flex gap-3 animate-fade-in">
                  <Avatar className="h-8 w-8">
                    <AvatarFallback className="bg-gradient-to-br from-violet-500 to-purple-500 text-white">
                      <Sparkles className="h-4 w-4" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="bg-muted rounded-2xl rounded-bl-md px-4 py-3 min-w-[200px]">
                    <div className="flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin text-primary" />
                      <span className="text-sm text-muted-foreground">
                        {loadingStatus || 'Processing...'}
                      </span>
                    </div>

                    {/* Content Generator Progress */}
                    {generationProgress && (
                      <div className="mt-3 pt-3 border-t border-border/50 space-y-2">
                        <div className="flex items-center gap-2 text-xs">
                          {generationProgress.tool === 'twitter_generator' ? (
                            <Twitter className="h-3 w-3 text-sky-500" />
                          ) : (
                            <Linkedin className="h-3 w-3 text-blue-600" />
                          )}
                          <span className="font-medium">
                            {generationProgress.tool === 'twitter_generator' ? 'Tweet' : 'LinkedIn Post'} Generator
                          </span>
                        </div>

                        {/* Progress Steps */}
                        <div className="space-y-1">
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-muted-foreground capitalize">
                              {generationProgress.step}
                            </span>
                            <span className="text-muted-foreground">
                              Iteration {generationProgress.iteration}/3
                            </span>
                          </div>

                          {/* Progress Bar */}
                          <div className="h-1.5 bg-muted-foreground/20 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-primary transition-all duration-300"
                              style={{
                                width: `${((generationProgress.iteration - 1) * 33) +
                                  (generationProgress.step === 'generating' ? 10 :
                                   generationProgress.step === 'evaluating' ? 20 :
                                   generationProgress.step === 'evaluated' ? 33 : 5)}%`
                              }}
                            />
                          </div>

                          {/* Quality Score */}
                          {generationProgress.qualityScore != null && (
                            <div className="flex items-center gap-1 text-xs">
                              <span className="text-muted-foreground">Score:</span>
                              <span className={cn(
                                "font-medium",
                                generationProgress.qualityScore >= 8 ? "text-green-600" :
                                generationProgress.qualityScore >= 6 ? "text-yellow-600" : "text-orange-600"
                              )}>
                                {Number(generationProgress.qualityScore).toFixed(1)}/10
                              </span>
                              {generationProgress.qualityScore < 8 && generationProgress.iteration < 3 && (
                                <span className="text-muted-foreground">(regenerating...)</span>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Document Embedding Progress */}
                    {embeddingProgress && (
                      <div className="mt-3 pt-3 border-t border-border/50 space-y-3">
                        <div className="flex items-center gap-2 text-xs">
                          <BookOpen className="h-3 w-3 text-orange-500" />
                          <span className="font-medium">Document Embedder</span>
                        </div>

                        {/* Document Name */}
                        <div className="text-xs text-muted-foreground">
                          Embedding: <span className="font-mono">{embeddingProgress.document_name}</span>
                          {embeddingProgress.arxiv_id && (
                            <Badge variant="outline" className="ml-2 text-xs py-0">
                              arXiv: {embeddingProgress.arxiv_id}
                            </Badge>
                          )}
                        </div>

                        {/* Step Progress Indicators */}
                        <div className="space-y-1">
                          {['download', 'partition', 'chunking', 'summarization', 'vectorization'].map((step) => {
                            const status = embeddingProgress.steps?.[step] || 'pending'
                            const isActive = status === 'processing'
                            const isCompleted = status === 'completed'
                            const isError = status === 'error'

                            return (
                              <div key={step} className="flex items-center gap-2 text-xs">
                                <div className={cn(
                                  "w-4 h-4 rounded-full flex items-center justify-center",
                                  isCompleted ? "bg-green-500" :
                                  isActive ? "bg-primary" :
                                  isError ? "bg-destructive" :
                                  "bg-muted-foreground/30"
                                )}>
                                  {isCompleted ? (
                                    <Check className="h-3 w-3 text-white" />
                                  ) : isActive ? (
                                    <Loader2 className="h-3 w-3 text-white animate-spin" />
                                  ) : isError ? (
                                    <X className="h-2 w-2 text-white" />
                                  ) : null}
                                </div>
                                <span className={cn(
                                  "capitalize",
                                  isActive ? "font-medium text-foreground" : "text-muted-foreground"
                                )}>
                                  {step}
                                </span>
                                {/* Show partition progress */}
                                {step === 'partition' && isActive && embeddingProgress.partition_progress?.total > 0 && (
                                  <span className="text-muted-foreground">
                                    ({embeddingProgress.partition_progress.current}/{embeddingProgress.partition_progress.total} pages)
                                  </span>
                                )}
                                {/* Show chunk progress */}
                                {step === 'chunking' && isActive && embeddingProgress.chunk_progress?.total > 0 && (
                                  <span className="text-muted-foreground">
                                    ({embeddingProgress.chunk_progress.current}/{embeddingProgress.chunk_progress.total} chunks)
                                  </span>
                                )}
                              </div>
                            )
                          })}
                        </div>

                        {/* Current Message */}
                        {embeddingProgress.message && (
                          <div className="text-xs text-muted-foreground italic">
                            {embeddingProgress.message}
                          </div>
                        )}

                        {/* Live Logs */}
                        {embeddingProgress.logs && embeddingProgress.logs.length > 0 && (
                          <div className="mt-2">
                            <div className="flex items-center gap-1 text-xs text-muted-foreground mb-1">
                              <Terminal className="h-3 w-3" />
                              Live logs
                            </div>
                            <div className="bg-muted/50 rounded p-2 max-h-32 overflow-y-auto font-mono text-xs">
                              {embeddingProgress.logs.slice(-5).map((log, i) => (
                                <div key={i} className="text-muted-foreground leading-relaxed">
                                  {log}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Error Display */}
                        {embeddingProgress.error && (
                          <div className="text-xs text-destructive flex items-center gap-1">
                            <AlertCircle className="h-3 w-3" />
                            {embeddingProgress.error}
                          </div>
                        )}

                        {/* Completion Message */}
                        {embeddingProgress.completed && !embeddingProgress.error && (
                          <div className="text-xs text-green-600 flex items-center gap-1">
                            <CheckCircle className="h-3 w-3" />
                            Document embedded successfully!
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Scroll anchor for auto-scroll */}
              <div ref={messagesEndRef} />
            </div>
          </ScrollArea>

          {/* Input */}
          <div className="p-4 border-t">
            {/* Source selection indicator */}
            {selectedSources.length > 0 && !chatAttachedFile && (
              <div className="flex items-center gap-2 mb-2 text-xs text-muted-foreground">
                <Search className="h-3 w-3" />
                <span>Searching in: {selectedSources.map(s => s.arxiv_id || s.name).join(', ')}</span>
              </div>
            )}

            {/* Attached file indicator */}
            {chatAttachedFile && (
              <div className="mb-3 p-3 bg-muted/50 rounded-lg border">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-primary" />
                    <div>
                      <p className="text-sm font-medium">{chatAttachedFile.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {(chatAttachedFile.size / 1024).toFixed(1)} KB
                      </p>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={removeChatAttachedFile}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
                <div className="flex items-center gap-2 mt-2 pt-2 border-t">
                  <Checkbox
                    id="add-to-kb"
                    checked={addToKnowledgeBase}
                    onCheckedChange={setAddToKnowledgeBase}
                  />
                  <Label htmlFor="add-to-kb" className="text-xs cursor-pointer">
                    Add to knowledge base (for future RAG queries)
                  </Label>
                </div>
              </div>
            )}

            <form onSubmit={handleSubmit} className="flex gap-2">
              {/* Hidden file input */}
              <input
                type="file"
                ref={chatFileInputRef}
                onChange={handleChatFileSelect}
                accept=".pdf"
                className="hidden"
              />

              {/* Attach file button */}
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={() => chatFileInputRef.current?.click()}
                disabled={isLoading || chatAttachedFile}
                title="Attach PDF document"
              >
                <FileText className="h-4 w-4" />
              </Button>

              <Input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={
                  chatAttachedFile
                    ? `Ask about ${chatAttachedFile.name}...`
                    : selectedSources.length > 0
                      ? `Ask about ${selectedSources.length} selected paper${selectedSources.length > 1 ? 's' : ''}...`
                      : "Type your message..."
                }
                disabled={isLoading}
                className="flex-1"
              />
              <Button type="submit" disabled={isLoading || !input.trim()}>
                <Send className="h-4 w-4" />
              </Button>
            </form>
          </div>
        </Card>
      </div>

      {/* Right Sidebar - Paper Selection & Upload */}
      <div className={cn(
        "border-l bg-muted/30 flex flex-col transition-all duration-300",
        sidebarExpanded ? "w-[600px]" : "w-96"
      )}>
        {/* Tab Headers */}
        <div className="flex border-b">
          <button
            className={cn(
              "flex-1 px-4 py-3 text-sm font-medium transition-colors flex items-center justify-center gap-2",
              activeTab === 'sources'
                ? "border-b-2 border-primary text-primary"
                : "text-muted-foreground hover:text-foreground"
            )}
            onClick={() => setActiveTab('sources')}
          >
            <FileText className="h-4 w-4" />
            Sources
          </button>
          <button
            className={cn(
              "flex-1 px-4 py-3 text-sm font-medium transition-colors flex items-center justify-center gap-2",
              activeTab === 'upload'
                ? "border-b-2 border-primary text-primary"
                : "text-muted-foreground hover:text-foreground"
            )}
            onClick={() => setActiveTab('upload')}
          >
            <Upload className="h-4 w-4" />
            Upload
          </button>
          <button
            className="px-3 py-3 text-muted-foreground hover:text-foreground transition-colors"
            onClick={() => setSidebarExpanded(!sidebarExpanded)}
            title={sidebarExpanded ? "Minimize sidebar" : "Maximize sidebar"}
          >
            {sidebarExpanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
        </div>

        {/* Sources Tab Content */}
        {activeTab === 'sources' && !explorerDocument && (
          <>
            <div className="p-4 border-b">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs text-muted-foreground">Papers in knowledge base</p>
                <Badge variant="secondary" className="text-xs">
                  {selectedSources.length}/{availableSources.length}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                Click checkbox to select for RAG. Click document name to explore chunks.
              </p>
            </div>

            <div className="p-2 border-b flex gap-2">
              <Button
                variant="outline"
                size="sm"
                className="flex-1 text-xs"
                onClick={selectAllSources}
                disabled={availableSources.length === 0}
              >
                Select All
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="flex-1 text-xs"
                onClick={clearAllSources}
                disabled={selectedSources.length === 0}
              >
                Clear
              </Button>
            </div>

            <ScrollArea className="flex-1">
              <div className="p-2 space-y-1">
                {sourcesLoading ? (
                  <div className="flex flex-col items-center justify-center py-8">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground mb-2" />
                    <p className="text-xs text-muted-foreground">Loading papers...</p>
                  </div>
                ) : availableSources.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-8 text-center px-4">
                    <FileText className="h-8 w-8 text-muted-foreground/50 mb-2" />
                    <p className="text-sm text-muted-foreground">No papers embedded</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Upload a PDF in the Upload tab
                    </p>
                  </div>
                ) : (
                  availableSources.map((source) => {
                    const isSelected = selectedSources.some(s => s.id === source.id)
                    const isPrivate = source.visibility === 'private'
                    const isOwn = source.is_own
                    return (
                      <div
                        key={source.id}
                        className={cn(
                          "flex items-start gap-2 p-2 rounded-md transition-colors",
                          isSelected ? "bg-primary/10 border border-primary/30" : "hover:bg-muted/50"
                        )}
                      >
                        <Checkbox
                          checked={isSelected}
                          className="mt-1 cursor-pointer"
                          onClick={(e) => {
                            e.stopPropagation()
                            toggleSource(source)
                          }}
                        />
                        <div
                          className="flex-1 min-w-0 cursor-pointer"
                          onClick={() => openDocumentExplorer(source)}
                        >
                          <div className="flex items-center gap-1.5">
                            <p className="text-sm font-medium truncate hover:text-primary transition-colors flex-1">
                              {source.name}
                            </p>
                            {isPrivate && (
                              <Badge variant="secondary" className="text-[10px] h-4 bg-amber-500/20 text-amber-600 shrink-0">
                                Private
                              </Badge>
                            )}
                            {isOwn && !isPrivate && (
                              <Badge variant="secondary" className="text-[10px] h-4 bg-blue-500/20 text-blue-600 shrink-0">
                                Mine
                              </Badge>
                            )}
                          </div>
                          <div className="flex items-center gap-2 mt-0.5">
                            {source.arxiv_id && (
                              <span className="text-xs text-muted-foreground">
                                arXiv:{source.arxiv_id}
                              </span>
                            )}
                            <Badge variant="outline" className="text-[10px] h-4">
                              {source.chunks_count} chunks
                            </Badge>
                          </div>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            </ScrollArea>

            {/* Selected sources summary */}
            {selectedSources.length > 0 && (
              <div className="p-3 border-t bg-primary/5">
                <p className="text-xs font-medium mb-2">Selected ({selectedSources.length}):</p>
                <div className="flex flex-wrap gap-1">
                  {selectedSources.slice(0, 3).map((source) => (
                    <Badge
                      key={source.id}
                      variant="secondary"
                      className="text-xs gap-1 pr-1"
                    >
                      <span className="truncate max-w-[80px]">
                        {source.arxiv_id || source.name}
                      </span>
                      <button
                        className="hover:bg-muted rounded-full p-0.5"
                        onClick={(e) => {
                          e.stopPropagation()
                          toggleSource(source)
                        }}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                  {selectedSources.length > 3 && (
                    <Badge variant="secondary" className="text-xs">
                      +{selectedSources.length - 3} more
                    </Badge>
                  )}
                </div>
              </div>
            )}
          </>
        )}

        {/* Document Explorer View */}
        {activeTab === 'sources' && explorerDocument && !explorerExpanded && (
          <div className="flex flex-col h-full">
            {/* Explorer Header */}
            <div className="p-3 border-b">
              <div className="flex items-center justify-between mb-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 gap-1"
                  onClick={closeDocumentExplorer}
                >
                  <ChevronLeft className="h-4 w-4" />
                  Back
                </Button>
                <div className="flex items-center gap-1">
                  {explorerDocument.is_own && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-destructive hover:text-destructive hover:bg-destructive/10"
                      onClick={() => handleDeleteDocument(explorerDocument)}
                      title="Delete document"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 gap-1"
                    onClick={() => setExplorerExpanded(true)}
                  >
                    <Maximize2 className="h-4 w-4" />
                    Expand
                  </Button>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <FileText className="h-5 w-5 text-primary shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{explorerDocument.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {explorerChunks.length} chunks
                    {explorerDocument.arxiv_id && ` • arXiv:${explorerDocument.arxiv_id}`}
                  </p>
                </div>
              </div>
            </div>

            {/* Chunk Type Filters */}
            <div className="p-2 border-b flex gap-1 flex-wrap">
              <Button
                variant={chunkFilter === 'all' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 text-xs"
                onClick={() => setChunkFilter('all')}
              >
                All
              </Button>
              <Button
                variant={chunkFilter === 'text' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 text-xs gap-1"
                onClick={() => setChunkFilter('text')}
              >
                <Type className="h-3 w-3" />
                Text
              </Button>
              <Button
                variant={chunkFilter === 'image' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 text-xs gap-1"
                onClick={() => setChunkFilter('image')}
              >
                <Image className="h-3 w-3" />
                Image
              </Button>
              <Button
                variant={chunkFilter === 'table' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 text-xs gap-1"
                onClick={() => setChunkFilter('table')}
              >
                <Table className="h-3 w-3" />
                Table
              </Button>
            </div>

            {/* Chunks List & Inspector */}
            <div className="flex-1 flex flex-col overflow-hidden">
              {explorerLoading ? (
                <div className="flex-1 flex items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <>
                  {/* Chunks List */}
                  <ScrollArea className="flex-1 border-b">
                    <div className="p-2 space-y-2">
                      {filteredExplorerChunks.length === 0 ? (
                        <p className="text-xs text-muted-foreground text-center py-4">
                          No chunks match filter
                        </p>
                      ) : (
                        filteredExplorerChunks.map((chunk, i) => {
                          const hasImages = chunk.images_base64?.length > 0
                          const hasTables = chunk.tables_html?.length > 0
                          const isSelected = selectedChunk?.chunk_id === chunk.chunk_id

                          return (
                            <div
                              key={chunk.chunk_id || i}
                              className={cn(
                                "p-2 rounded-lg border cursor-pointer transition-all",
                                isSelected
                                  ? "bg-primary/10 border-primary"
                                  : "hover:bg-muted/50 border-border"
                              )}
                              onClick={() => setSelectedChunk(chunk)}
                            >
                              <div className="flex items-center justify-between mb-1">
                                <div className="flex items-center gap-1">
                                  {chunk.content_types?.map((type, j) => (
                                    <Badge
                                      key={j}
                                      variant="secondary"
                                      className={cn(
                                        "text-[9px] h-4 px-1",
                                        type === 'text' && 'bg-purple-500/20 text-purple-600',
                                        type === 'image' && 'bg-blue-500/20 text-blue-600',
                                        type === 'table' && 'bg-orange-500/20 text-orange-600'
                                      )}
                                    >
                                      {type}
                                    </Badge>
                                  ))}
                                </div>
                                <span className="text-[10px] text-muted-foreground">
                                  p.{chunk.page_number}
                                </span>
                              </div>

                              {/* Image thumbnails */}
                              {hasImages && (
                                <div className="flex gap-1 mb-1">
                                  {chunk.images_base64.slice(0, 2).map((img, j) => (
                                    <img
                                      key={j}
                                      src={`data:image/jpeg;base64,${img}`}
                                      alt=""
                                      className="h-10 w-10 object-cover rounded border"
                                    />
                                  ))}
                                  {chunk.images_base64.length > 2 && (
                                    <div className="h-10 w-10 rounded border bg-muted flex items-center justify-center text-[10px] text-muted-foreground">
                                      +{chunk.images_base64.length - 2}
                                    </div>
                                  )}
                                </div>
                              )}

                              <p className="text-xs text-muted-foreground line-clamp-2">
                                {chunk.content?.slice(0, 150)}...
                              </p>
                              <p className="text-[10px] text-muted-foreground mt-1">
                                {chunk.char_count} chars
                              </p>
                            </div>
                          )
                        })
                      )}
                    </div>
                  </ScrollArea>

                  {/* Chunk Inspector */}
                  {selectedChunk && (
                    <div className="border-t bg-muted/30">
                      <div className="p-2 border-b flex items-center justify-between">
                        <span className="text-xs font-medium">Chunk Inspector</span>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 w-6 p-0"
                          onClick={() => setSelectedChunk(null)}
                        >
                          <X className="h-3 w-3" />
                        </Button>
                      </div>

                      {/* Content / Enhanced tabs */}
                      <div className="flex border-b">
                        <button
                          className={cn(
                            "flex-1 px-3 py-1.5 text-xs font-medium border-b-2 transition-colors",
                            inspectorTab === 'content'
                              ? "border-primary text-primary"
                              : "border-transparent text-muted-foreground"
                          )}
                          onClick={() => setInspectorTab('content')}
                        >
                          Content
                        </button>
                        <button
                          className={cn(
                            "flex-1 px-3 py-1.5 text-xs font-medium border-b-2 transition-colors",
                            inspectorTab === 'enhanced'
                              ? "border-primary text-primary"
                              : "border-transparent text-muted-foreground"
                          )}
                          onClick={() => setInspectorTab('enhanced')}
                        >
                          Enhanced
                        </button>
                      </div>

                      <ScrollArea className="h-[200px]">
                        <div className="p-3 space-y-3">
                          {inspectorTab === 'content' ? (
                            <>
                              {/* Images */}
                              {selectedChunk.images_base64?.length > 0 && (
                                <div>
                                  <p className="text-[10px] font-medium text-muted-foreground mb-1">
                                    Images ({selectedChunk.images_base64.length})
                                  </p>
                                  <div className="grid grid-cols-2 gap-1">
                                    {selectedChunk.images_base64.map((img, i) => (
                                      <img
                                        key={i}
                                        src={`data:image/jpeg;base64,${img}`}
                                        alt=""
                                        className="w-full rounded border cursor-zoom-in hover:ring-2 hover:ring-primary"
                                        onClick={() => setLightboxImage(img)}
                                      />
                                    ))}
                                  </div>
                                </div>
                              )}

                              {/* Tables */}
                              {selectedChunk.tables_html?.length > 0 && (
                                <div>
                                  <p className="text-[10px] font-medium text-muted-foreground mb-1">
                                    Tables ({selectedChunk.tables_html.length})
                                  </p>
                                  {selectedChunk.tables_html.map((html, i) => (
                                    <div
                                      key={i}
                                      className="p-2 border rounded bg-background text-[10px] overflow-x-auto"
                                      dangerouslySetInnerHTML={{ __html: html }}
                                    />
                                  ))}
                                </div>
                              )}

                              {/* Text */}
                              <div>
                                <p className="text-[10px] font-medium text-muted-foreground mb-1">
                                  Text Content
                                </p>
                                <p className="text-xs whitespace-pre-wrap">
                                  {selectedChunk.content}
                                </p>
                              </div>
                            </>
                          ) : (
                            <div>
                              <p className="text-[10px] font-medium text-muted-foreground mb-1">
                                AI-Enhanced Summary
                              </p>
                              <p className="text-xs whitespace-pre-wrap">
                                {selectedChunk.enhanced_content || 'No enhanced content available'}
                              </p>
                            </div>
                          )}
                        </div>
                      </ScrollArea>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {/* Upload Tab Content */}
        {activeTab === 'upload' && (
          <div className="flex-1 flex flex-col min-h-0">
            <ScrollArea className="flex-1">
              <div className="p-4 space-y-4 overflow-visible">
                {/* Metadata Info Box */}
                <div className="p-3 rounded-lg bg-muted/50 border space-y-2">
                  <div className="flex items-center gap-2 text-xs">
                    <Database className="h-3 w-3 text-primary" />
                    <span className="text-muted-foreground">Collection:</span>
                    <span className="font-mono font-medium">research_papers</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <Building className="h-3 w-3 text-primary" />
                    <span className="text-muted-foreground">Tenant:</span>
                    <span className="font-medium">{user?.tenant_id || 'default'}</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <Users className="h-3 w-3 text-primary" />
                    <span className="text-muted-foreground">Department:</span>
                    <span className="font-medium">{user?.department || 'general'}</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <User className="h-3 w-3 text-primary" />
                    <span className="text-muted-foreground">User:</span>
                    <span className="font-medium truncate">{user?.email?.split('@')[0] || 'anonymous'}</span>
                  </div>
                </div>

                {/* File Selection Area - hide during upload */}
                {!isUploading && (
                  <div className="space-y-2">
                    <Label className="text-xs">Select PDFs</Label>
                    <div
                      className={cn(
                        "border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors",
                        uploadQueue.length > 0 ? "border-primary bg-primary/5" : "border-muted-foreground/25 hover:border-primary/50"
                      )}
                      onClick={() => document.getElementById('pdf-upload')?.click()}
                    >
                      <input
                        id="pdf-upload"
                        type="file"
                        accept=".pdf"
                        multiple
                        className="hidden"
                        onChange={handleFileSelect}
                      />
                      <Upload className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
                      <p className="text-sm text-muted-foreground">Click to select PDFs</p>
                      <p className="text-xs text-muted-foreground mt-1">You can select multiple files</p>
                    </div>
                  </div>
                )}

                {/* File Queue - Only show when NOT uploading */}
                {uploadQueue.length > 0 && !isUploading && (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label className="text-xs">Upload Queue ({uploadQueue.length} files)</Label>
                      {completedCount > 0 && (
                        <span className="text-xs text-green-600">{completedCount} completed</span>
                      )}
                    </div>
                    <ScrollArea className="max-h-[350px]">
                      <div className="space-y-2 pr-2">
                        {uploadQueue.map((item, index) => (
                          <div
                            key={`${item.file.name}-${index}`}
                            className={cn(
                              "p-2 rounded-lg border flex items-center gap-2",
                              item.status === 'processing' && "bg-primary/10 border-primary/30",
                              item.status === 'completed' && "bg-green-500/10 border-green-500/30",
                              item.status === 'error' && "bg-destructive/10 border-destructive/30",
                              item.status === 'pending' && "bg-muted/30"
                            )}
                          >
                            {item.status === 'processing' ? (
                              <Loader2 className="h-4 w-4 animate-spin text-primary shrink-0" />
                            ) : item.status === 'completed' ? (
                              <CheckCircle className="h-4 w-4 text-green-500 shrink-0" />
                            ) : item.status === 'error' ? (
                              <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
                            ) : (
                              <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                            )}
                            <div className="flex-1 min-w-0">
                              <p className="text-xs font-medium truncate">{item.file.name}</p>
                              {item.status === 'completed' && item.progress?.chunks_count && (
                                <p className="text-[10px] text-green-600">
                                  {item.progress.chunks_count} chunks
                                </p>
                              )}
                              {item.status === 'error' && (
                                <p className="text-[10px] text-destructive truncate">{item.error}</p>
                              )}
                            </div>
                            {item.status === 'pending' && (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 shrink-0"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  removeFromQueue(index)
                                }}
                              >
                                <X className="h-3 w-3" />
                              </Button>
                            )}
                          </div>
                        ))}
                      </div>
                    </ScrollArea>
                  </div>
                )}

                {/* Visibility Toggle - hide during upload */}
                {pendingCount > 0 && !isUploading && (
                  <div className="space-y-2">
                    <Label className="text-xs">Visibility</Label>
                    <div className="flex gap-2">
                      <Button
                        variant={uploadVisibility === 'public' ? 'default' : 'outline'}
                        size="sm"
                        className="flex-1 gap-1"
                        onClick={() => setUploadVisibility('public')}
                      >
                        <Eye className="h-3 w-3" />
                        Public
                      </Button>
                      <Button
                        variant={uploadVisibility === 'private' ? 'default' : 'outline'}
                        size="sm"
                        className="flex-1 gap-1"
                        onClick={() => setUploadVisibility('private')}
                      >
                        <EyeOff className="h-3 w-3" />
                        Private
                      </Button>
                    </div>
                    <p className="text-[10px] text-muted-foreground">
                      {uploadVisibility === 'public'
                        ? 'Anyone in your organization can search these documents'
                        : 'Only you can search these documents'}
                    </p>
                  </div>
                )}

                {/* Upload Button - hide during upload */}
                {pendingCount > 0 && !isUploading && (
                  <Button
                    onClick={handleUpload}
                    className="w-full gap-2"
                  >
                    <Upload className="h-4 w-4" />
                    Upload & Embed {pendingCount} {pendingCount === 1 ? 'file' : 'files'}
                  </Button>
                )}

                {/* Current File Processing Progress */}
                {isUploading && currentUploadItem && (
                  <div className="space-y-3">
                    {/* Queue Progress Header */}
                    <div className="p-3 rounded-lg bg-primary/10 border border-primary/20">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-xs font-medium min-w-0 truncate">Processing file {currentUploadIndex + 1} of {uploadQueue.length}</span>
                        <span className="text-xs text-muted-foreground shrink-0">
                          {completedCount} completed, {pendingCount} pending
                        </span>
                      </div>
                      <p className="text-sm font-medium truncate min-w-0">{currentUploadItem.file.name}</p>
                    </div>

                    {/* Current Progress Details */}
                    {currentUploadItem.progress?.progress_message && (
                      <div className="p-3 rounded-lg bg-muted/30 border">
                        <p className="text-xs text-muted-foreground break-words">
                          {currentUploadItem.progress.progress_message}
                        </p>
                        {currentUploadItem.progress.total_chunks > 0 && (
                          <div className="mt-2">
                            <div className="flex justify-between text-xs mb-1 min-w-0">
                              <span className="truncate">Chunk {currentUploadItem.progress.current_chunk} of {currentUploadItem.progress.total_chunks}</span>
                              <span className="shrink-0">{Math.round((currentUploadItem.progress.current_chunk / currentUploadItem.progress.total_chunks) * 100)}%</span>
                            </div>
                            <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                              <div
                                className="h-full bg-primary transition-all duration-300"
                                style={{ width: `${(currentUploadItem.progress.current_chunk / currentUploadItem.progress.total_chunks) * 100}%` }}
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Pipeline Steps */}
                    {currentUploadItem.progress && (
                      <div className="space-y-2">
                        <p className="text-xs font-medium pl-1">Pipeline Steps:</p>
                        {['partitioning', 'chunking', 'summarization', 'vectorization'].map((step) => {
                          const status = currentUploadItem.progress[step]
                          const stepLogs = getLogsForStep(step, currentUploadItem.progress)
                          const stepLabels = {
                            partitioning: 'Partitioning',
                            chunking: 'Chunking',
                            summarization: 'Summarization',
                            vectorization: 'Vectorization & Storage',
                          }
                          return (
                            <Collapsible key={step} className="rounded-lg border bg-muted/30 overflow-hidden">
                              <CollapsibleTrigger className="flex items-center justify-between w-full px-3 py-2.5 hover:bg-muted/50 transition-colors">
                                <div className="flex items-center gap-2.5 min-w-0">
                                  {status === 'completed' ? (
                                    <CheckCircle className="h-4 w-4 text-green-500 shrink-0" />
                                  ) : status === 'error' ? (
                                    <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
                                  ) : status === 'processing' ? (
                                    <Loader2 className="h-4 w-4 animate-spin text-primary shrink-0" />
                                  ) : (
                                    <div className="h-4 w-4 rounded-full border-2 border-muted-foreground/30 shrink-0" />
                                  )}
                                  <span className={cn(
                                    "text-sm font-medium truncate min-w-0",
                                    status === 'completed' && "text-green-600",
                                    status === 'error' && "text-destructive",
                                    status === 'processing' && "text-primary"
                                  )}>
                                    {stepLabels[step]}
                                  </span>
                                </div>
                                <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform duration-200 [[data-state=open]>&]:rotate-180 shrink-0" />
                              </CollapsibleTrigger>
                              <CollapsibleContent>
                                <div className="px-2.5 pb-2.5 pt-0">
                                  {stepLogs.length > 0 ? (
                                    <ScrollArea className="h-[80px] rounded bg-zinc-950 border border-zinc-800">
                                      <div className="p-2 font-mono text-[10px] space-y-0.5">
                                        {stepLogs.map((log, i) => (
                                          <div
                                            key={i}
                                            className={cn(
                                              'py-0.5',
                                              log.includes('ERROR') && 'text-red-400',
                                              (log.includes('SUCCESS') || log.includes('Completed') || log.includes('successfully')) && 'text-green-400',
                                              (log.includes('Processing') || log.includes('Starting') || log.includes('STEP')) && 'text-yellow-400',
                                              log.includes('===') && 'text-blue-400',
                                              !(log.includes('ERROR') || log.includes('SUCCESS') || log.includes('Completed') || log.includes('successfully') || log.includes('Processing') || log.includes('Starting') || log.includes('STEP') || log.includes('===')) && 'text-zinc-300'
                                            )}
                                          >
                                            {log}
                                          </div>
                                        ))}
                                      </div>
                                    </ScrollArea>
                                  ) : (
                                    <p className="text-xs text-muted-foreground italic">Waiting...</p>
                                  )}
                                </div>
                              </CollapsibleContent>
                            </Collapsible>
                          )
                        })}
                      </div>
                    )}

                    {/* Live Logs */}
                    {currentUploadItem.progress?.logs && currentUploadItem.progress.logs.length > 0 && (
                      <Collapsible defaultOpen className="rounded-lg border bg-muted/30 overflow-hidden">
                        <CollapsibleTrigger className="flex items-center justify-between w-full px-3 py-2.5 hover:bg-muted/50 transition-colors">
                          <div className="flex items-center gap-2.5 min-w-0">
                            <Terminal className="h-4 w-4 text-muted-foreground shrink-0" />
                            <span className="text-sm font-medium truncate">Live Logs</span>
                            <Badge variant="secondary" className="text-[10px] shrink-0">{currentUploadItem.progress.logs.length}</Badge>
                          </div>
                          <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform duration-200 [[data-state=open]>&]:rotate-180 shrink-0" />
                        </CollapsibleTrigger>
                        <CollapsibleContent>
                          <div className="px-2.5 pb-2.5 pt-0">
                            <ScrollArea className="h-[120px] rounded bg-zinc-950 border border-zinc-800">
                              <div className="p-2 font-mono text-[10px] space-y-0.5">
                                {currentUploadItem.progress.logs.map((log, i) => (
                                  <div
                                    key={i}
                                    className={cn(
                                      'py-0.5',
                                      log.includes('ERROR') && 'text-red-400',
                                      (log.includes('SUCCESS') || log.includes('Completed') || log.includes('successfully')) && 'text-green-400',
                                      (log.includes('Processing') || log.includes('Starting') || log.includes('STEP')) && 'text-yellow-400',
                                      log.includes('===') && 'text-blue-400',
                                      !(log.includes('ERROR') || log.includes('SUCCESS') || log.includes('Completed') || log.includes('successfully') || log.includes('Processing') || log.includes('Starting') || log.includes('STEP') || log.includes('===')) && 'text-zinc-300'
                                    )}
                                  >
                                    {log}
                                  </div>
                                ))}
                                <div ref={logsEndRef} />
                              </div>
                            </ScrollArea>
                          </div>
                        </CollapsibleContent>
                      </Collapsible>
                    )}
                  </div>
                )}

                {/* Completed State - Show summary when all done */}
                {!isUploading && uploadQueue.length > 0 && completedCount + errorCount === uploadQueue.length && (
                  <div className="space-y-3">
                    {/* Summary */}
                    <div className={cn(
                      "p-3 rounded-lg text-sm flex items-center gap-2",
                      errorCount === 0 ? "bg-green-500/10 text-green-600 border border-green-500/20" : "bg-yellow-500/10 text-yellow-600 border border-yellow-500/20"
                    )}>
                      {errorCount === 0 ? (
                        <CheckCircle className="h-4 w-4 shrink-0" />
                      ) : (
                        <AlertCircle className="h-4 w-4 shrink-0" />
                      )}
                      <span>
                        {completedCount} of {uploadQueue.length} files embedded successfully
                        {errorCount > 0 && `, ${errorCount} failed`}
                      </span>
                    </div>

                    {/* Total chunks */}
                    {completedCount > 0 && (
                      <div className="p-3 rounded-lg border bg-green-500/10 border-green-500/20 flex items-center justify-between">
                        <span className="text-sm text-green-600">Total chunks created:</span>
                        <span className="font-bold text-green-600 text-lg">
                          {uploadQueue.reduce((sum, item) => sum + (item.progress?.chunks_count || 0), 0)}
                        </span>
                      </div>
                    )}

                    {/* Start New Upload Button */}
                    <Button
                      onClick={resetUpload}
                      variant="outline"
                      className="w-full gap-2"
                    >
                      <Upload className="h-4 w-4" />
                      Start New Upload
                    </Button>
                  </div>
                )}
              </div>
            </ScrollArea>
          </div>
        )}
      </div>

      {/* Expanded Document Explorer Modal */}
      {explorerExpanded && explorerDocument && (
        <div className="fixed inset-0 z-40 bg-background/95 backdrop-blur-sm flex flex-col animate-fade-in">
          {/* Expanded Header */}
          <div className="p-4 border-b flex items-center justify-between bg-background">
            <div className="flex items-center gap-3">
              <FileText className="h-6 w-6 text-primary" />
              <div>
                <h2 className="text-lg font-semibold">{explorerDocument.name}</h2>
                <p className="text-sm text-muted-foreground">
                  {explorerChunks.length} chunks
                  {explorerDocument.arxiv_id && ` • arXiv:${explorerDocument.arxiv_id}`}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {explorerDocument.is_own && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-destructive hover:text-destructive hover:bg-destructive/10"
                  onClick={() => handleDeleteDocument(explorerDocument)}
                  title="Delete document"
                >
                  <Trash2 className="h-5 w-5" />
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => setExplorerExpanded(false)}
              >
                <Minimize2 className="h-4 w-4" />
                Collapse
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => {
                  setExplorerExpanded(false)
                  closeDocumentExplorer()
                }}
              >
                <X className="h-5 w-5" />
              </Button>
            </div>
          </div>

          {/* Expanded Chunk Type Filters */}
          <div className="px-4 py-2 border-b flex gap-2 bg-muted/30">
            <Button
              variant={chunkFilter === 'all' ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => setChunkFilter('all')}
            >
              All ({explorerChunks.length})
            </Button>
            <Button
              variant={chunkFilter === 'text' ? 'secondary' : 'ghost'}
              size="sm"
              className="gap-1"
              onClick={() => setChunkFilter('text')}
            >
              <Type className="h-4 w-4" />
              Text
            </Button>
            <Button
              variant={chunkFilter === 'image' ? 'secondary' : 'ghost'}
              size="sm"
              className="gap-1"
              onClick={() => setChunkFilter('image')}
            >
              <Image className="h-4 w-4" />
              Image
            </Button>
            <Button
              variant={chunkFilter === 'table' ? 'secondary' : 'ghost'}
              size="sm"
              className="gap-1"
              onClick={() => setChunkFilter('table')}
            >
              <Table className="h-4 w-4" />
              Table
            </Button>
          </div>

          {/* Expanded Content - Two Column Layout */}
          <div className="flex-1 flex overflow-hidden">
            {/* Chunks List - Left Side */}
            <div className="w-1/3 border-r flex flex-col">
              <ScrollArea className="flex-1">
                <div className="p-4 space-y-3">
                  {filteredExplorerChunks.length === 0 ? (
                    <p className="text-sm text-muted-foreground text-center py-8">
                      No chunks match filter
                    </p>
                  ) : (
                    filteredExplorerChunks.map((chunk, i) => {
                      const hasImages = chunk.images_base64?.length > 0
                      const isSelected = selectedChunk?.chunk_id === chunk.chunk_id

                      return (
                        <div
                          key={chunk.chunk_id || i}
                          className={cn(
                            "p-3 rounded-lg border cursor-pointer transition-all",
                            isSelected
                              ? "bg-primary/10 border-primary ring-1 ring-primary"
                              : "hover:bg-muted/50 border-border"
                          )}
                          onClick={() => setSelectedChunk(chunk)}
                        >
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-1">
                              {chunk.content_types?.map((type, j) => (
                                <Badge
                                  key={j}
                                  variant="secondary"
                                  className={cn(
                                    "text-xs",
                                    type === 'text' && 'bg-purple-500/20 text-purple-600',
                                    type === 'image' && 'bg-blue-500/20 text-blue-600',
                                    type === 'table' && 'bg-orange-500/20 text-orange-600'
                                  )}
                                >
                                  {type}
                                </Badge>
                              ))}
                            </div>
                            <span className="text-xs text-muted-foreground">
                              Page {chunk.page_number}
                            </span>
                          </div>

                          {/* Image thumbnails */}
                          {hasImages && (
                            <div className="flex gap-1 mb-2">
                              {chunk.images_base64.slice(0, 3).map((img, j) => (
                                <img
                                  key={j}
                                  src={`data:image/jpeg;base64,${img}`}
                                  alt=""
                                  className="h-12 w-12 object-cover rounded border"
                                />
                              ))}
                              {chunk.images_base64.length > 3 && (
                                <div className="h-12 w-12 rounded border bg-muted flex items-center justify-center text-xs text-muted-foreground">
                                  +{chunk.images_base64.length - 3}
                                </div>
                              )}
                            </div>
                          )}

                          <p className="text-sm text-muted-foreground line-clamp-3">
                            {chunk.content?.slice(0, 200)}...
                          </p>
                          <p className="text-xs text-muted-foreground mt-2">
                            {chunk.char_count} characters
                          </p>
                        </div>
                      )
                    })
                  )}
                </div>
              </ScrollArea>
            </div>

            {/* Chunk Inspector - Right Side */}
            <div className="flex-1 flex flex-col">
              {selectedChunk ? (
                <>
                  {/* Inspector Tabs */}
                  <div className="flex border-b">
                    <button
                      className={cn(
                        "flex-1 px-4 py-3 text-sm font-medium border-b-2 transition-colors",
                        inspectorTab === 'content'
                          ? "border-primary text-primary"
                          : "border-transparent text-muted-foreground hover:text-foreground"
                      )}
                      onClick={() => setInspectorTab('content')}
                    >
                      Content
                    </button>
                    <button
                      className={cn(
                        "flex-1 px-4 py-3 text-sm font-medium border-b-2 transition-colors",
                        inspectorTab === 'enhanced'
                          ? "border-primary text-primary"
                          : "border-transparent text-muted-foreground hover:text-foreground"
                      )}
                      onClick={() => setInspectorTab('enhanced')}
                    >
                      AI-Enhanced Summary
                    </button>
                  </div>

                  <ScrollArea className="flex-1">
                    <div className="p-6 space-y-6">
                      {inspectorTab === 'content' ? (
                        <>
                          {/* Images */}
                          {selectedChunk.images_base64?.length > 0 && (
                            <div>
                              <h3 className="text-sm font-medium mb-3">
                                Images ({selectedChunk.images_base64.length})
                              </h3>
                              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                                {selectedChunk.images_base64.map((img, i) => (
                                  <img
                                    key={i}
                                    src={`data:image/jpeg;base64,${img}`}
                                    alt=""
                                    className="w-full rounded-lg border cursor-zoom-in hover:ring-2 hover:ring-primary transition-all"
                                    onClick={() => setLightboxImage(img)}
                                  />
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Tables */}
                          {selectedChunk.tables_html?.length > 0 && (
                            <div>
                              <h3 className="text-sm font-medium mb-3">
                                Tables ({selectedChunk.tables_html.length})
                              </h3>
                              {selectedChunk.tables_html.map((html, i) => (
                                <div
                                  key={i}
                                  className="p-4 border rounded-lg bg-background text-sm overflow-x-auto mb-3"
                                  dangerouslySetInnerHTML={{ __html: html }}
                                />
                              ))}
                            </div>
                          )}

                          {/* Text Content */}
                          <div>
                            <h3 className="text-sm font-medium mb-3">Text Content</h3>
                            <div className="p-4 rounded-lg bg-muted/50 border">
                              <p className="text-sm whitespace-pre-wrap leading-relaxed">
                                {selectedChunk.content}
                              </p>
                            </div>
                          </div>
                        </>
                      ) : (
                        <div>
                          <h3 className="text-sm font-medium mb-3">AI-Enhanced Summary</h3>
                          <div className="p-4 rounded-lg bg-primary/5 border border-primary/20">
                            <p className="text-sm whitespace-pre-wrap leading-relaxed">
                              {selectedChunk.enhanced_content || 'No enhanced content available for this chunk.'}
                            </p>
                          </div>
                        </div>
                      )}
                    </div>
                  </ScrollArea>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center text-muted-foreground">
                  <div className="text-center">
                    <FileText className="h-12 w-12 mx-auto mb-3 opacity-50" />
                    <p className="text-sm">Select a chunk from the left to inspect</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Image Lightbox Modal */}
      {lightboxImage && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
          onClick={() => setLightboxImage(null)}
        >
          <div className="relative max-w-4xl max-h-[90vh] w-full">
            <Button
              variant="ghost"
              size="icon"
              className="absolute -top-12 right-0 text-white hover:bg-white/20"
              onClick={() => setLightboxImage(null)}
            >
              <X className="h-6 w-6" />
            </Button>
            <img
              src={`data:image/jpeg;base64,${lightboxImage}`}
              alt="Full size"
              className="w-full h-full object-contain rounded-lg"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        </div>
      )}
    </div>
  )
}
