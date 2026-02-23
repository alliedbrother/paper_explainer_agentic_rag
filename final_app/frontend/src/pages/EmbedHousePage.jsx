import { useState, useRef, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import {
  FileText,
  Upload,
  Lock,
  CheckCircle,
  Circle,
  Loader2,
  X,
  Eye,
  Search,
  Database,
  Sparkles,
  ArrowRight,
  AlertCircle,
  Table,
  Image,
  Type,
  Terminal,
  History,
  Clock,
  ChevronLeft,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const PIPELINE_STEPS = [
  { key: 'upload', label: 'Upload' },
  { key: 'queued', label: 'Queued' },
  { key: 'partitioning', label: 'Partitioning' },
  { key: 'chunking', label: 'Chunking' },
  { key: 'summarization', label: 'Summarisation' },
  { key: 'vectorization', label: 'Vectorization & Storage' },
  { key: 'view_chunks', label: 'View Chunks' },
]

function StepIcon({ status }) {
  if (status === 'completed') {
    return <CheckCircle className="h-4 w-4 text-green-500" />
  }
  if (status === 'processing') {
    return <Loader2 className="h-4 w-4 text-primary animate-spin" />
  }
  if (status === 'error') {
    return <AlertCircle className="h-4 w-4 text-destructive" />
  }
  return <Circle className="h-4 w-4 text-muted-foreground" />
}

function PipelineTabs({ currentStep, selectedStep, status, hasChunks, onSelectStep }) {
  return (
    <div className="flex border-b border-border/50 overflow-x-auto">
      {PIPELINE_STEPS.map((step) => {
        // View chunks is complete if we have chunks
        const stepStatus = step.key === 'view_chunks'
          ? (hasChunks ? 'completed' : status.vectorization === 'completed' ? 'pending' : 'pending')
          : status[step.key]
        const isSelected = step.key === selectedStep
        const isCompleted = stepStatus === 'completed'
        const isProcessing = stepStatus === 'processing'
        const isClickable = isCompleted || isProcessing || step.key === 'view_chunks'

        return (
          <button
            key={step.key}
            onClick={() => isClickable && onSelectStep(step.key)}
            disabled={!isClickable}
            className={cn(
              'flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap',
              isSelected && 'border-primary text-primary bg-primary/5',
              !isSelected && isCompleted && 'border-transparent text-green-500 hover:bg-muted/50 cursor-pointer',
              !isSelected && isProcessing && 'border-transparent text-primary',
              !isSelected && !isCompleted && !isProcessing && 'border-transparent text-muted-foreground cursor-not-allowed opacity-50'
            )}
          >
            <StepIcon status={stepStatus} />
            {step.label}
          </button>
        )
      })}
    </div>
  )
}

function ProcessingLogsWide({ status }) {
  const logsEndRef = useRef(null)

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [status?.logs?.length])

  if (!status) return null

  return (
    <div className="space-y-4">
      {/* Progress indicator - full width */}
      {status.progress_message && (
        <div className="p-4 rounded-lg bg-primary/10 border border-primary/20">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              <span className="font-medium capitalize">{status.current_step || 'Processing'}</span>
            </div>
            {status.total_chunks > 0 && (
              <span className="text-sm text-muted-foreground">
                Chunk {status.current_chunk} of {status.total_chunks} ({Math.round((status.current_chunk / status.total_chunks) * 100)}%)
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground mb-3">{status.progress_message}</p>
          {status.total_chunks > 0 && (
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary transition-all duration-300"
                style={{ width: `${(status.current_chunk / status.total_chunks) * 100}%` }}
              />
            </div>
          )}
        </div>
      )}

      {/* Logs panel - full width */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Terminal className="h-4 w-4 text-muted-foreground" />
          <Label className="text-sm text-muted-foreground font-medium">Processing Logs</Label>
        </div>
        <ScrollArea className="h-[200px] rounded-lg bg-zinc-950 border border-zinc-800">
          <div className="p-4 font-mono text-sm space-y-1">
            {status.logs && status.logs.length > 0 ? (
              status.logs.map((log, i) => (
                <div
                  key={i}
                  className={cn(
                    'py-0.5',
                    log.includes('ERROR') && 'text-red-400',
                    log.includes('SUCCESS') || log.includes('Completed') || log.includes('successfully') ? 'text-green-400' : '',
                    log.includes('Processing') || log.includes('Starting') || log.includes('STEP') ? 'text-yellow-400' : '',
                    log.includes('===') && 'text-blue-400',
                    !log.includes('ERROR') && !log.includes('SUCCESS') && !log.includes('Completed') && !log.includes('successfully') && !log.includes('Processing') && !log.includes('Starting') && !log.includes('STEP') && !log.includes('===') && 'text-zinc-300'
                  )}
                >
                  {log}
                </div>
              ))
            ) : (
              <div className="text-zinc-500">Waiting for logs...</div>
            )}
            <div ref={logsEndRef} />
          </div>
        </ScrollArea>
      </div>
    </div>
  )
}

function ChunkCard({ chunk, isSelected, onClick, onImageClick }) {
  const contentTypes = chunk.content_types || ['text']
  const hasImages = chunk.images_base64 && chunk.images_base64.length > 0

  return (
    <Card
      className={cn(
        'cursor-pointer transition-all hover:bg-muted/50',
        isSelected && 'ring-2 ring-primary'
      )}
      onClick={onClick}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center gap-2">
            {contentTypes.map((type, i) => (
              <Badge
                key={i}
                variant="secondary"
                className={cn(
                  'text-xs',
                  type === 'text' && 'bg-purple-500/20 text-purple-400',
                  type === 'image' && 'bg-blue-500/20 text-blue-400',
                  type === 'table' && 'bg-orange-500/20 text-orange-400'
                )}
              >
                {type}
              </Badge>
            ))}
            <span className="text-xs text-muted-foreground">Page {chunk.page_number}</span>
          </div>
          <span className="text-xs text-muted-foreground">{chunk.char_count} chars</span>
        </div>

        {/* Show image thumbnail if available */}
        {hasImages && (
          <div className="flex gap-2 mb-2">
            {chunk.images_base64.slice(0, 2).map((img, i) => (
              <img
                key={i}
                src={`data:image/jpeg;base64,${img}`}
                alt={`Chunk image ${i + 1}`}
                className="h-16 w-16 object-cover rounded border cursor-zoom-in hover:ring-2 hover:ring-primary transition-all"
                onClick={(e) => {
                  e.stopPropagation()
                  onImageClick && onImageClick(img)
                }}
              />
            ))}
            {chunk.images_base64.length > 2 && (
              <div className="h-16 w-16 rounded border bg-muted flex items-center justify-center text-xs text-muted-foreground">
                +{chunk.images_base64.length - 2}
              </div>
            )}
          </div>
        )}

        <p className="text-sm text-muted-foreground line-clamp-3">
          {chunk.content?.substring(0, 200)}...
        </p>
      </CardContent>
    </Card>
  )
}

export default function EmbedHousePage() {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [password, setPassword] = useState('')
  const [authError, setAuthError] = useState('')
  const [isAuthLoading, setIsAuthLoading] = useState(false)

  // Upload state
  const [file, setFile] = useState(null)
  const [tenantId, setTenantId] = useState('')
  const [department, setDepartment] = useState('physics')
  const [accessLevel, setAccessLevel] = useState('public')
  const [processingMode, setProcessingMode] = useState('hi_res')
  const [isUploading, setIsUploading] = useState(false)
  const fileInputRef = useRef(null)

  // Processing state
  const [currentJob, setCurrentJob] = useState(null)
  const [currentStep, setCurrentStep] = useState('upload')
  const [selectedStep, setSelectedStep] = useState('upload') // For viewing previous steps
  const [isProcessingComplete, setIsProcessingComplete] = useState(false) // Track if processing finished
  const [userManuallySelectedStep, setUserManuallySelectedStep] = useState(false) // Track if user clicked a tab
  const [selectedChunk, setSelectedChunk] = useState(null)
  const [selectedInspectorTab, setSelectedInspectorTab] = useState('content') // For Content/Enhanced tabs
  const [collectionStats, setCollectionStats] = useState(null)

  // Image lightbox state
  const [lightboxImage, setLightboxImage] = useState(null)

  // Filter and search state
  const [chunkFilter, setChunkFilter] = useState('all') // all, text, image, table
  const [chunkSearch, setChunkSearch] = useState('')

  // Job history state
  const [jobHistory, setJobHistory] = useState([])
  const [showJobHistory, setShowJobHistory] = useState(false)

  // Polling for job status
  useEffect(() => {
    if (!currentJob || !isAuthenticated) return

    const pollStatus = async () => {
      try {
        const response = await fetch(
          `/api/v1/embed-house/job/${currentJob.job_id}?password=${password}`
        )
        if (response.ok) {
          const data = await response.json()
          setCurrentJob(data)

          // Determine current step
          const status = data.status
          let newStep = currentStep
          let processingDone = false

          if (status.vectorization === 'completed' && data.chunks) {
            newStep = 'view_chunks'
            processingDone = true
            fetchStats()
          } else if (status.vectorization === 'processing' || status.vectorization === 'completed') {
            newStep = 'vectorization'
            if (status.vectorization === 'completed') fetchStats()
          } else if (status.summarization === 'processing' || status.summarization === 'completed') {
            newStep = 'summarization'
          } else if (status.chunking === 'processing' || status.chunking === 'completed') {
            newStep = 'chunking'
          } else if (status.partitioning === 'processing' || status.partitioning === 'completed') {
            newStep = 'partitioning'
          } else if (status.queued === 'processing' || status.queued === 'completed') {
            newStep = 'queued'
          }

          // Update current step tracking
          if (newStep !== currentStep) {
            setCurrentStep(newStep)
            // Only auto-advance selectedStep if user hasn't manually selected a tab
            // and processing is not complete
            if (!userManuallySelectedStep && !isProcessingComplete) {
              setSelectedStep(newStep)
            }
          }

          // Mark processing as complete when done
          if (processingDone && !isProcessingComplete) {
            setIsProcessingComplete(true)
            // Only auto-switch to view_chunks if user hasn't manually selected a tab
            if (!userManuallySelectedStep) {
              setSelectedStep('view_chunks')
            }
          }
        }
      } catch (err) {
        console.error('Failed to poll job status:', err)
      }
    }

    // Poll every 1 second for more real-time log updates
    const interval = setInterval(() => {
      if (
        currentJob?.status?.vectorization !== 'completed' &&
        currentJob?.status?.vectorization !== 'error'
      ) {
        pollStatus()
      }
    }, 1000)

    return () => clearInterval(interval)
  }, [currentJob?.job_id, password, isAuthenticated, userManuallySelectedStep, isProcessingComplete, currentStep])

  const fetchStats = async () => {
    try {
      const response = await fetch(`/api/v1/embed-house/stats?password=${password}`)
      if (response.ok) {
        const data = await response.json()
        setCollectionStats(data)
      }
    } catch (err) {
      console.error('Failed to fetch stats:', err)
    }
  }

  const fetchJobHistory = async () => {
    try {
      const response = await fetch(`/api/v1/embed-house/jobs?password=${password}`)
      if (response.ok) {
        const data = await response.json()
        setJobHistory(data)
      }
    } catch (err) {
      console.error('Failed to fetch job history:', err)
    }
  }

  const loadPreviousJob = async (jobId) => {
    try {
      const response = await fetch(`/api/v1/embed-house/job/${jobId}?password=${password}`)
      if (response.ok) {
        const data = await response.json()
        setCurrentJob(data)
        setCurrentStep('view_chunks')
        setSelectedStep('view_chunks')
        setIsProcessingComplete(true)
        setUserManuallySelectedStep(false) // Reset so tabs work normally
        setShowJobHistory(false)
        setSelectedChunk(null)
        setChunkFilter('all')
        setChunkSearch('')
        setSelectedInspectorTab('content')
        setLightboxImage(null)
        fetchStats() // Refresh stats
      }
    } catch (err) {
      console.error('Failed to load job:', err)
    }
  }

  // Filter chunks based on selected filter and search
  const filteredChunks = currentJob?.chunks?.filter(chunk => {
    // Filter by type
    if (chunkFilter !== 'all') {
      if (!chunk.content_types?.includes(chunkFilter)) {
        return false
      }
    }
    // Filter by search
    if (chunkSearch) {
      const searchLower = chunkSearch.toLowerCase()
      return chunk.content?.toLowerCase().includes(searchLower) ||
             chunk.enhanced_content?.toLowerCase().includes(searchLower)
    }
    return true
  }) || []

  const handleAuth = async (e) => {
    e.preventDefault()
    setAuthError('')
    setIsAuthLoading(true)

    try {
      const response = await fetch('/api/v1/embed-house/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })

      if (response.ok) {
        setIsAuthenticated(true)
        fetchStats()
        fetchJobHistory()
      } else {
        setAuthError('Invalid password')
      }
    } catch (err) {
      setAuthError('Failed to authenticate')
    } finally {
      setIsAuthLoading(false)
    }
  }

  const handleFileChange = (e) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setFile(selectedFile)
    }
  }

  const handleUpload = async () => {
    if (!file || !tenantId) return

    setIsUploading(true)
    setCurrentJob(null)
    setCurrentStep('upload')
    setSelectedStep('partitioning')
    setIsProcessingComplete(false)
    setUserManuallySelectedStep(false)
    setSelectedChunk(null)
    setSelectedInspectorTab('content')
    setLightboxImage(null)

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('password', password)
      formData.append('tenant_id', tenantId)
      formData.append('department', department)
      formData.append('access_level', accessLevel)
      formData.append('processing_mode', processingMode)

      const response = await fetch('/api/v1/embed-house/upload', {
        method: 'POST',
        body: formData,
      })

      if (response.ok) {
        const data = await response.json()
        // Initialize job with pending status
        setCurrentJob({
          job_id: data.job_id,
          document_name: file.name,
          status: {
            upload: 'completed',
            queued: 'completed',
            partitioning: 'processing',
            chunking: 'pending',
            summarization: 'pending',
            vectorization: 'pending',
          },
          chunks: null,
        })
        setCurrentStep('partitioning')
      } else {
        const error = await response.json()
        alert(error.detail || 'Upload failed')
      }
    } catch (err) {
      alert('Failed to upload: ' + err.message)
    } finally {
      setIsUploading(false)
    }
  }

  const handleClose = () => {
    setCurrentJob(null)
    setFile(null)
    setCurrentStep('upload')
    setSelectedStep('upload')
    setIsProcessingComplete(false)
    setUserManuallySelectedStep(false)
    setSelectedChunk(null)
    setSelectedInspectorTab('content')
    setLightboxImage(null)
  }

  // Auth screen
  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <div className="flex justify-center mb-4">
              <div className="h-16 w-16 rounded-2xl bg-gradient-to-br from-primary to-orange-500 flex items-center justify-center">
                <Database className="h-8 w-8 text-white" />
              </div>
            </div>
            <CardTitle className="text-2xl">Embed House</CardTitle>
            <CardDescription>
              Document processing pipeline for Qdrant Cloud
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleAuth} className="space-y-4">
              {authError && (
                <div className="p-3 rounded-lg bg-destructive/10 text-destructive text-sm">
                  {authError}
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="password"
                    type="password"
                    placeholder="Enter password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pl-10"
                    required
                  />
                </div>
              </div>

              <Button type="submit" className="w-full" disabled={isAuthLoading}>
                {isAuthLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <>
                    Access Embed House
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </>
                )}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    )
  }

  // Main interface
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b bg-muted/30">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-primary to-orange-500 flex items-center justify-center">
              <Database className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="font-semibold">Embed House</h1>
              <p className="text-xs text-muted-foreground">Document Processing Pipeline</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {/* Job History Button */}
            <Button
              variant={showJobHistory ? "secondary" : "outline"}
              size="sm"
              onClick={() => {
                setShowJobHistory(!showJobHistory)
                if (!showJobHistory) fetchJobHistory()
              }}
              className="gap-2"
            >
              <History className="h-4 w-4" />
              History
              {jobHistory.length > 0 && (
                <Badge variant="secondary" className="ml-1">{jobHistory.length}</Badge>
              )}
            </Button>

            {/* Stats */}
            {collectionStats && (
              <div className="text-right">
                <p className="text-sm font-medium">
                  {collectionStats.vectors_count ?? collectionStats.points_count ?? 0} vectors
                </p>
                <p className="text-xs text-muted-foreground">in {collectionStats.collection_name}</p>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="container mx-auto px-4 py-6">
        {/* Job History Panel */}
        {showJobHistory && (
          <Card className="mb-6">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-lg">
                  <History className="h-5 w-5" />
                  Processing History
                </CardTitle>
                <Button variant="ghost" size="sm" onClick={() => setShowJobHistory(false)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {jobHistory.length === 0 ? (
                <p className="text-muted-foreground text-center py-4">No previous jobs found</p>
              ) : (
                <div className="space-y-2">
                  {jobHistory.map((job) => (
                    <div
                      key={job.job_id}
                      className={cn(
                        'flex items-center justify-between p-3 rounded-lg border cursor-pointer hover:bg-muted/50 transition-colors',
                        job.has_error && 'border-destructive/50 bg-destructive/5'
                      )}
                      onClick={() => loadPreviousJob(job.job_id)}
                    >
                      <div className="flex items-center gap-3">
                        <FileText className="h-8 w-8 text-muted-foreground" />
                        <div>
                          <p className="font-medium">{job.document_name}</p>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <span>{job.tenant_id}</span>
                            <span>•</span>
                            <span>{job.department}</span>
                            <span>•</span>
                            <span className="flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              {job.created_at ? new Date(job.created_at).toLocaleString() : 'Unknown'}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <Badge variant={job.is_complete ? "default" : job.has_error ? "destructive" : "secondary"}>
                          {job.is_complete ? `${job.chunks_count} chunks` : job.has_error ? 'Error' : 'Processing'}
                        </Badge>
                        {job.is_complete && (
                          <CheckCircle className="h-5 w-5 text-green-500" />
                        )}
                        {job.has_error && (
                          <AlertCircle className="h-5 w-5 text-destructive" />
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {!currentJob ? (
          // Upload form
          <div className="max-w-2xl mx-auto">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Upload className="h-5 w-5" />
                  Upload Document
                </CardTitle>
                <CardDescription>
                  Upload a PDF document to process and store in Qdrant Cloud
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* File Upload */}
                <div
                  className={cn(
                    'border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors',
                    file ? 'border-primary bg-primary/5' : 'hover:bg-muted/50'
                  )}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf"
                    onChange={handleFileChange}
                    className="hidden"
                  />
                  {file ? (
                    <div className="flex items-center justify-center gap-3">
                      <FileText className="h-8 w-8 text-primary" />
                      <div className="text-left">
                        <p className="font-medium">{file.name}</p>
                        <p className="text-sm text-muted-foreground">
                          {(file.size / 1024 / 1024).toFixed(2)} MB
                        </p>
                      </div>
                    </div>
                  ) : (
                    <>
                      <Upload className="h-10 w-10 mx-auto mb-3 text-muted-foreground" />
                      <p className="font-medium">Drop PDF file or click to upload</p>
                      <p className="text-sm text-muted-foreground mt-1">PDF files only</p>
                    </>
                  )}
                </div>

                <Separator />

                {/* Metadata */}
                <div className="grid gap-4">
                  <div className="space-y-2">
                    <Label>Tenant</Label>
                    <Select value={tenantId} onValueChange={setTenantId}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select tenant" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="atomicworks">AtomicWorks</SelectItem>
                        <SelectItem value="togetherai">TogetherAI</SelectItem>
                        <SelectItem value="hpiq">HPIQ</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>Department</Label>
                      <Select value={department} onValueChange={setDepartment}>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="physics">Physics</SelectItem>
                          <SelectItem value="chemistry">Chemistry</SelectItem>
                          <SelectItem value="math">Math</SelectItem>
                          <SelectItem value="biology">Biology</SelectItem>
                          <SelectItem value="english">English</SelectItem>
                          <SelectItem value="history">History</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-2">
                      <Label>Access Level</Label>
                      <Select value={accessLevel} onValueChange={setAccessLevel}>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="public">Public</SelectItem>
                          <SelectItem value="internal">Internal</SelectItem>
                          <SelectItem value="confidential">Confidential</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label>Processing Speed</Label>
                    <Select value={processingMode} onValueChange={setProcessingMode}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="fast">⚡ Fast (text only)</SelectItem>
                        <SelectItem value="balanced">⚖️ Balanced (+ tables)</SelectItem>
                        <SelectItem value="hi_res">🔍 High Quality (+ images)</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      {processingMode === 'fast' && 'Fastest. Text extraction only, no OCR or images.'}
                      {processingMode === 'balanced' && 'Good balance. Includes table inference, no images.'}
                      {processingMode === 'hi_res' && 'Best quality. Full OCR, table structure, and image extraction.'}
                    </p>
                  </div>
                </div>

                <Button
                  onClick={handleUpload}
                  disabled={!file || !tenantId || isUploading}
                  className="w-full"
                  size="lg"
                >
                  {isUploading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                      Uploading...
                    </>
                  ) : (
                    <>
                      <Sparkles className="h-4 w-4 mr-2" />
                      Start Processing
                    </>
                  )}
                </Button>
              </CardContent>
            </Card>
          </div>
        ) : (
          // Processing pipeline view
          <Card className="max-w-[1400px] mx-auto">
            {/* Document header */}
            <div className="p-4 border-b flex items-center justify-between">
              <div className="flex items-center gap-3">
                <FileText className="h-10 w-10 text-muted-foreground" />
                <div>
                  <h2 className="font-semibold">{currentJob.document_name}</h2>
                  <p className="text-sm text-muted-foreground">Processing Pipeline</p>
                </div>
              </div>
              <Button variant="ghost" size="icon" onClick={handleClose}>
                <X className="h-5 w-5" />
              </Button>
            </div>

            {/* Pipeline tabs */}
            <PipelineTabs
              currentStep={currentStep}
              selectedStep={selectedStep}
              status={currentJob.status}
              hasChunks={currentJob.chunks && currentJob.chunks.length > 0}
              onSelectStep={(step) => {
                setSelectedStep(step)
                setUserManuallySelectedStep(true)
              }}
            />

            {/* Content area */}
            <div className="flex flex-col">
              {/* Main content + sidebar row */}
              <div className="flex">
                {/* Main content - fixed min-height to prevent jumping */}
                <div className="flex-1 p-6 min-h-[280px]">
                  {/* Upload/Queued - show brief info */}
                  {(selectedStep === 'upload' || selectedStep === 'queued') && (
                    <div className="text-center py-8">
                      <h3 className="text-xl font-semibold mb-2">
                        {selectedStep === 'upload' ? 'Upload' : 'Queued'}
                      </h3>
                      <p className="text-muted-foreground mb-6">
                        {selectedStep === 'upload' ? 'Document uploaded successfully' : 'Document queued for processing'}
                      </p>
                      <div className="max-w-md mx-auto p-4 rounded-lg border bg-muted/30">
                        <div className="flex items-center gap-3">
                          <FileText className="h-8 w-8 text-primary" />
                          <div className="text-left">
                            <p className="font-medium">{currentJob.document_name}</p>
                            <p className="text-sm text-muted-foreground">Ready for processing</p>
                          </div>
                        </div>
                      </div>
                      <div className="mt-6 p-4 rounded-lg bg-green-500/10 border border-green-500/20 flex items-center justify-center gap-2">
                        <CheckCircle className="h-5 w-5 text-green-500" />
                        <span className="font-medium text-green-500">Step completed</span>
                      </div>
                    </div>
                  )}

                  {/* Partitioning */}
                  {selectedStep === 'partitioning' && (
                    <div className="text-center py-8">
                      <h3 className="text-xl font-semibold mb-2">Partitioning</h3>
                      <p className="text-muted-foreground mb-6">
                        Processing and extracting content (8 parallel workers)
                      </p>

                      {currentJob.status.partitioning === 'processing' ? (
                        <div>
                          <Loader2 className="h-12 w-12 mx-auto animate-spin text-primary mb-4" />
                          <p className="text-sm text-muted-foreground">
                            Processing pages in parallel with 8 workers...
                          </p>
                          <p className="text-xs text-muted-foreground mt-1">
                            Mode: {currentJob.processing_mode === 'fast' ? '⚡ Fast' : currentJob.processing_mode === 'balanced' ? '⚖️ Balanced' : '🔍 High Quality'}
                          </p>
                        </div>
                      ) : currentJob.status.elements_discovered && Object.keys(currentJob.status.elements_discovered).length > 0 ? (
                        <div className="max-w-lg mx-auto">
                          {/* Page processing info */}
                          {currentJob.status.elements_discovered.pages_processed && (
                            <div className="mb-6 p-4 rounded-lg border bg-primary/10 border-primary/20">
                              <div className="flex items-center justify-center gap-2 mb-2">
                                <FileText className="h-5 w-5 text-primary" />
                                <span className="font-medium">Pages Processed</span>
                              </div>
                              <p className="text-2xl font-bold text-primary">
                                {currentJob.status.elements_discovered.pages_processed} of {currentJob.status.elements_discovered.total_pages}
                              </p>
                              {currentJob.status.elements_discovered.total_pages > 12 && (
                                <p className="text-xs text-muted-foreground mt-1">
                                  Limited to first 12 pages for faster processing
                                </p>
                              )}
                            </div>
                          )}

                          <div className="flex items-center justify-center gap-2 mb-4">
                            <span className="font-medium">Elements Discovered</span>
                          </div>

                          <div className="grid grid-cols-2 gap-3">
                            {Object.entries(currentJob.status.elements_discovered)
                              .filter(([key]) => !['pages_processed', 'total_pages', 'processing_mode'].includes(key))
                              .map(([key, value]) => (
                              <div
                                key={key}
                                className="flex items-center justify-between p-3 rounded-lg border bg-muted/30"
                              >
                                <span className="text-sm capitalize">
                                  {key.replace(/_/g, ' ')}
                                </span>
                                <span className="font-semibold">{value}</span>
                              </div>
                            ))}
                          </div>

                          <div className="mt-4 space-y-2">
                            <div className="p-3 rounded-lg border bg-muted/30 flex items-center justify-between">
                              <span className="text-sm">Total atomic elements</span>
                              <span className="font-semibold text-primary">{currentJob.status.atomic_elements || 0}</span>
                            </div>
                            <div className="p-3 rounded-lg border bg-muted/30 flex items-center justify-between">
                              <span className="text-sm">Processing mode</span>
                              <span className="font-semibold">
                                {currentJob.status.elements_discovered.processing_mode === 'fast' ? '⚡ Fast' :
                                 currentJob.status.elements_discovered.processing_mode === 'balanced' ? '⚖️ Balanced' : '🔍 High Quality'}
                              </span>
                            </div>
                          </div>

                          {currentJob.status.partitioning === 'completed' && (
                            <div className="mt-6 p-4 rounded-lg bg-green-500/10 border border-green-500/20 flex items-center justify-center gap-2">
                              <CheckCircle className="h-5 w-5 text-green-500" />
                              <span className="font-medium text-green-500">Step completed successfully</span>
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="text-muted-foreground">Waiting for data...</p>
                      )}
                    </div>
                  )}

                  {/* Chunking */}
                  {selectedStep === 'chunking' && (
                    <div className="text-center py-8">
                      <h3 className="text-xl font-semibold mb-2">Chunking</h3>
                      <p className="text-muted-foreground mb-6">Creating semantic chunks from elements</p>

                      {currentJob.status.chunking === 'processing' ? (
                        <Loader2 className="h-12 w-12 mx-auto animate-spin text-primary" />
                      ) : currentJob.status.chunks_created > 0 ? (
                        <div className="max-w-lg mx-auto">
                          <div className="p-6 rounded-lg border bg-muted/30 mb-4">
                            <div className="flex items-center justify-center gap-8">
                              <div className="text-center">
                                <p className="text-3xl font-bold text-primary">
                                  {currentJob.status.atomic_elements || 0}
                                </p>
                                <p className="text-sm text-muted-foreground">atomic elements</p>
                              </div>
                              <ArrowRight className="h-5 w-5 text-muted-foreground" />
                              <div className="text-center">
                                <p className="text-3xl font-bold text-green-500">
                                  {currentJob.status.chunks_created}
                                </p>
                                <p className="text-sm text-muted-foreground">chunks created</p>
                              </div>
                            </div>
                          </div>

                          <div className="space-y-2">
                            <div className="flex items-center justify-between p-3 rounded-lg border bg-muted/30">
                              <span className="text-sm">Average chunk size</span>
                              <span className="font-semibold">{currentJob.status.avg_chunk_size || 0} characters</span>
                            </div>
                            <div className="flex items-center justify-between p-3 rounded-lg border bg-muted/30">
                              <span className="text-sm">Chunking strategy</span>
                              <span className="font-semibold">chunk_by_title</span>
                            </div>
                          </div>

                          {currentJob.status.chunking === 'completed' && (
                            <div className="mt-6 p-4 rounded-lg bg-green-500/10 border border-green-500/20 flex items-center justify-center gap-2">
                              <CheckCircle className="h-5 w-5 text-green-500" />
                              <span className="font-medium text-green-500">Step completed successfully</span>
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="text-muted-foreground">Waiting for data...</p>
                      )}
                    </div>
                  )}

                  {/* Summarization */}
                  {selectedStep === 'summarization' && (
                    <div className="text-center py-8">
                      <h3 className="text-xl font-semibold mb-2">Summarisation</h3>
                      <p className="text-muted-foreground mb-6">
                        AI-enhanced summaries with concurrent processing (8 workers)
                      </p>

                      {currentJob.status.summarization === 'processing' ? (
                        <div>
                          <Loader2 className="h-12 w-12 mx-auto animate-spin text-primary mb-4" />
                          <p className="text-sm text-muted-foreground mb-2">
                            {currentJob.status.progress_message || 'Processing chunks...'}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            Text-only chunks: instant • Mixed content: concurrent GPT-4o-mini calls
                          </p>
                        </div>
                      ) : currentJob.status.summarization === 'completed' ? (
                        <div className="max-w-lg mx-auto">
                          <div className="p-6 rounded-lg border bg-muted/30 mb-4">
                            <div className="text-center">
                              <p className="text-3xl font-bold text-green-500">{currentJob.status.chunks_created}</p>
                              <p className="text-sm text-muted-foreground">chunks processed</p>
                            </div>
                          </div>
                          <div className="space-y-2">
                            <div className="flex items-center justify-between p-3 rounded-lg border bg-muted/30">
                              <span className="text-sm">Processing strategy</span>
                              <span className="font-semibold">Concurrent (8 workers)</span>
                            </div>
                            <div className="flex items-center justify-between p-3 rounded-lg border bg-muted/30">
                              <span className="text-sm">Text-only chunks</span>
                              <span className="font-semibold text-blue-500">Instant (no API)</span>
                            </div>
                            <div className="flex items-center justify-between p-3 rounded-lg border bg-muted/30">
                              <span className="text-sm">Mixed content</span>
                              <span className="font-semibold text-orange-500">GPT-4o-mini</span>
                            </div>
                          </div>
                          <div className="mt-6 p-4 rounded-lg bg-green-500/10 border border-green-500/20 flex items-center justify-center gap-2">
                            <CheckCircle className="h-5 w-5 text-green-500" />
                            <span className="font-medium text-green-500">Step completed successfully</span>
                          </div>
                        </div>
                      ) : (
                        <p className="text-muted-foreground">Waiting for data...</p>
                      )}
                    </div>
                  )}

                  {/* Vectorization */}
                  {selectedStep === 'vectorization' && (
                    <div className="text-center py-8">
                      <h3 className="text-xl font-semibold mb-2">Vectorization & Storage</h3>
                      <p className="text-muted-foreground mb-6">
                        Generating embeddings and storing in Qdrant Cloud
                      </p>

                      {currentJob.status.vectorization === 'processing' ? (
                        <div>
                          <Loader2 className="h-12 w-12 mx-auto animate-spin text-primary mb-4" />
                          <p className="text-sm text-muted-foreground">
                            Embedding {currentJob.status.chunks_created} chunks with text-embedding-3-small...
                          </p>
                        </div>
                      ) : currentJob.status.vectorization === 'completed' ? (
                        <div className="max-w-lg mx-auto">
                          <div className="p-6 rounded-lg border bg-muted/30 mb-4">
                            <div className="text-center">
                              <p className="text-3xl font-bold text-green-500">{currentJob.status.chunks_created}</p>
                              <p className="text-sm text-muted-foreground">vectors stored in Qdrant</p>
                            </div>
                          </div>
                          <div className="space-y-2">
                            <div className="flex items-center justify-between p-3 rounded-lg border bg-muted/30">
                              <span className="text-sm">Embedding model</span>
                              <span className="font-semibold">text-embedding-3-small</span>
                            </div>
                            <div className="flex items-center justify-between p-3 rounded-lg border bg-muted/30">
                              <span className="text-sm">Vector dimensions</span>
                              <span className="font-semibold">1536</span>
                            </div>
                            <div className="flex items-center justify-between p-3 rounded-lg border bg-muted/30">
                              <span className="text-sm">Collection</span>
                              <span className="font-semibold">research_papers</span>
                            </div>
                          </div>
                          <div className="mt-6 p-4 rounded-lg bg-green-500/10 border border-green-500/20 flex items-center justify-center gap-2">
                            <CheckCircle className="h-5 w-5 text-green-500" />
                            <span className="font-medium text-green-500">Step completed successfully</span>
                          </div>
                        </div>
                      ) : (
                        <p className="text-muted-foreground">Waiting for data...</p>
                      )}
                    </div>
                  )}

                  {/* View Chunks */}
                  {selectedStep === 'view_chunks' && currentJob.chunks && currentJob.chunks.length > 0 && (
                    <div className="max-w-3xl mx-auto w-full">
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-semibold">Content Chunks</h3>
                        <span className="text-sm text-muted-foreground">
                          {filteredChunks.length} of {currentJob.chunks.length} chunks
                        </span>
                      </div>

                      <div className="flex gap-2 mb-4 flex-wrap">
                        <Button
                          variant={chunkFilter === 'all' ? "secondary" : "outline"}
                          size="sm"
                          className="gap-1"
                          onClick={() => setChunkFilter('all')}
                        >
                          All
                        </Button>
                        <Button
                          variant={chunkFilter === 'text' ? "secondary" : "outline"}
                          size="sm"
                          className="gap-1"
                          onClick={() => setChunkFilter('text')}
                        >
                          <Type className="h-3 w-3" />
                          Text
                        </Button>
                        <Button
                          variant={chunkFilter === 'image' ? "secondary" : "outline"}
                          size="sm"
                          className="gap-1"
                          onClick={() => setChunkFilter('image')}
                        >
                          <Image className="h-3 w-3" />
                          Image
                        </Button>
                        <Button
                          variant={chunkFilter === 'table' ? "secondary" : "outline"}
                          size="sm"
                          className="gap-1"
                          onClick={() => setChunkFilter('table')}
                        >
                          <Table className="h-3 w-3" />
                          Table
                        </Button>
                        <div className="flex-1 relative min-w-[200px]">
                          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                          <Input
                            placeholder="Search chunks..."
                            className="pl-9 h-9"
                            value={chunkSearch}
                            onChange={(e) => setChunkSearch(e.target.value)}
                          />
                        </div>
                      </div>

                      <ScrollArea className="h-[500px]">
                        <div className="space-y-3 pr-4">
                          {filteredChunks.length > 0 ? (
                            filteredChunks.map((chunk, i) => (
                              <ChunkCard
                                key={chunk.chunk_id || i}
                                chunk={chunk}
                                isSelected={selectedChunk?.chunk_id === chunk.chunk_id}
                                onClick={() => setSelectedChunk(chunk)}
                                onImageClick={(img) => setLightboxImage(img)}
                              />
                            ))
                          ) : (
                            <div className="text-center py-8 text-muted-foreground">
                              No chunks match the current filter
                            </div>
                          )}
                        </div>
                      </ScrollArea>
                    </div>
                  )}

                  {/* View Chunks - No chunks yet */}
                  {selectedStep === 'view_chunks' && (!currentJob.chunks || currentJob.chunks.length === 0) && (
                    <div className="flex flex-col items-center justify-center py-16">
                      <div className="h-16 w-16 rounded-full bg-muted flex items-center justify-center mb-4">
                        <Database className="h-8 w-8 text-muted-foreground" />
                      </div>
                      <h3 className="text-lg font-semibold mb-2">Chunks Not Ready</h3>
                      <p className="text-muted-foreground text-center max-w-md">
                        Chunks will be available once the processing pipeline completes.
                        Check the other tabs to see the current progress.
                      </p>
                    </div>
                  )}
                </div>

                {/* Detail Inspector sidebar - only show when viewing chunks and chunks exist */}
                {selectedStep === 'view_chunks' && currentJob.chunks && currentJob.chunks.length > 0 && (
                  <div className="w-[400px] border-l bg-muted/20 p-4">
                    <h4 className="font-semibold mb-4">Detail Inspector</h4>

                    {selectedChunk ? (
                      <div className="space-y-4">
                        {/* Content type badges */}
                        <div className="flex gap-2">
                          {selectedChunk.content_types?.map((type, i) => (
                            <Badge
                              key={i}
                              className={cn(
                                type === 'text' && 'bg-purple-500',
                                type === 'image' && 'bg-blue-500',
                                type === 'table' && 'bg-orange-500'
                              )}
                            >
                              {type.toUpperCase()}
                            </Badge>
                          ))}
                        </div>

                        {/* Tabs for Content / Enhanced Summary */}
                        <div className="flex border-b">
                          <button
                            onClick={() => setSelectedInspectorTab('content')}
                            className={cn(
                              'px-4 py-2 text-sm font-medium border-b-2 transition-colors',
                              selectedInspectorTab === 'content'
                                ? 'border-primary text-primary'
                                : 'border-transparent text-muted-foreground hover:text-foreground'
                            )}
                          >
                            Content
                          </button>
                          <button
                            onClick={() => setSelectedInspectorTab('enhanced')}
                            className={cn(
                              'px-4 py-2 text-sm font-medium border-b-2 transition-colors',
                              selectedInspectorTab === 'enhanced'
                                ? 'border-primary text-primary'
                                : 'border-transparent text-muted-foreground hover:text-foreground'
                            )}
                          >
                            Enhanced Summary
                          </button>
                        </div>

                        {/* Tab content */}
                        {selectedInspectorTab === 'content' ? (
                          <ScrollArea className="h-[450px] p-3 rounded-lg bg-background border">
                            {/* Images */}
                            {selectedChunk.images_base64 && selectedChunk.images_base64.length > 0 && (
                              <div className="mb-4">
                                <p className="text-xs font-medium text-muted-foreground mb-2">Images ({selectedChunk.images_base64.length})</p>
                                <div className="grid grid-cols-2 gap-2">
                                  {selectedChunk.images_base64.map((img, i) => (
                                    <img
                                      key={i}
                                      src={`data:image/jpeg;base64,${img}`}
                                      alt={`Image ${i + 1}`}
                                      className="w-full rounded border object-contain max-h-32 cursor-zoom-in hover:ring-2 hover:ring-primary transition-all"
                                      onClick={() => setLightboxImage(img)}
                                    />
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Tables */}
                            {selectedChunk.tables_html && selectedChunk.tables_html.length > 0 && (
                              <div className="mb-4">
                                <p className="text-xs font-medium text-muted-foreground mb-2">Tables ({selectedChunk.tables_html.length})</p>
                                {selectedChunk.tables_html.map((tableHtml, i) => (
                                  <div
                                    key={i}
                                    className="p-2 border rounded bg-muted/30 overflow-x-auto text-xs mb-2"
                                    dangerouslySetInnerHTML={{ __html: tableHtml }}
                                  />
                                ))}
                              </div>
                            )}

                            {/* Text content */}
                            <div>
                              <p className="text-xs font-medium text-muted-foreground mb-2">Text Content</p>
                              <p className="text-sm whitespace-pre-wrap">{selectedChunk.content}</p>
                            </div>
                          </ScrollArea>
                        ) : (
                          <ScrollArea className="h-[450px] p-3 rounded-lg bg-background border">
                            <p className="text-sm whitespace-pre-wrap">
                              {selectedChunk.enhanced_content || 'No enhanced summary available'}
                            </p>
                          </ScrollArea>
                        )}
                      </div>
                    ) : (
                      <div className="flex flex-col items-center justify-center h-64 text-center">
                        <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center mb-3">
                          <Eye className="h-6 w-6 text-muted-foreground" />
                        </div>
                        <p className="text-sm text-muted-foreground">
                          Select a chunk to inspect details
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Processing Logs - Full width at bottom (always visible except when viewing chunks) */}
              {selectedStep !== 'view_chunks' && (
                <div className="border-t p-4 min-h-[320px]">
                  <ProcessingLogsWide status={currentJob.status} />
                </div>
              )}
            </div>
          </Card>
        )}
      </div>

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
              alt="Full size image"
              className="w-full h-full object-contain rounded-lg"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        </div>
      )}
    </div>
  )
}
