import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { useChat } from '@/hooks/useChat'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  MessageSquare,
  Plus,
  Clock,
  Loader2,
  Trash2,
} from 'lucide-react'
import { formatDate } from '@/lib/utils'

export default function HomePage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { conversations, conversationsLoading, deleteConversation, newConversation } = useChat()

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <div className="p-6 border-b">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold">{user?.tenant_id || 'My Workspace'}</h1>
            <p className="text-sm text-muted-foreground mt-1">
              {user?.department ? `${user.department} Department` : 'Research Assistant'}
            </p>
          </div>
          <Button onClick={() => {
            newConversation()
            navigate('/chat')
          }} className="gap-2">
            <Plus className="h-4 w-4" />
            New conversation
          </Button>
        </div>
      </div>

      {/* Conversations Section */}
      <div className="flex-1 p-6 overflow-auto">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-medium">Conversations</h2>
            <Badge variant="secondary">{conversations.length}</Badge>
          </div>

          {conversationsLoading ? (
            <div className="flex flex-col items-center justify-center py-24 text-center">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-4" />
              <p className="text-muted-foreground">Loading conversations...</p>
            </div>
          ) : conversations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-24 text-center">
              <div className="h-16 w-16 rounded-2xl bg-muted flex items-center justify-center mb-6">
                <MessageSquare className="h-8 w-8 text-muted-foreground" />
              </div>
              <h3 className="text-xl font-medium mb-2">No conversations yet</h3>
              <p className="text-muted-foreground max-w-md mb-6">
                Start your first conversation to analyze documents and get insights from your AI assistant.
              </p>
              <Button
                variant="outline"
                size="lg"
                className="gap-2"
                onClick={() => {
                  newConversation()
                  navigate('/chat')
                }}
              >
                <Plus className="h-4 w-4" />
                Start first conversation
              </Button>
            </div>
          ) : (
            <div className="grid gap-3">
              {conversations.map((conv) => (
                <Card
                  key={conv.id}
                  className="cursor-pointer hover:bg-muted/50 transition-colors group"
                  onClick={() => navigate(`/chat/${conv.id}`)}
                >
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <h4 className="font-medium truncate">{conv.title}</h4>
                        <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                          {conv.preview}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 ml-4 shrink-0">
                        <span className="text-xs text-muted-foreground flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {formatDate(conv.updatedAt)}
                        </span>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity"
                          onClick={(e) => {
                            e.stopPropagation()
                            deleteConversation(conv.id)
                          }}
                        >
                          <Trash2 className="h-4 w-4 text-muted-foreground hover:text-destructive" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
