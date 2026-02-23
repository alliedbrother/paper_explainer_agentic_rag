import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  User,
  Building2,
  Shield,
  Key,
  Download,
  Settings,
  Bell,
  Twitter,
  Linkedin,
  Plus,
  Copy,
  Check,
  Star,
  Clock,
  RotateCcw,
  CheckCircle,
  Loader2,
  FileText,
  Lightbulb,
  Megaphone,
  GraduationCap,
  BookOpen,
} from 'lucide-react'
import { cn, formatDate } from '@/lib/utils'

const styleIcons = {
  insight: Lightbulb,
  announcement: Megaphone,
  tutorial: GraduationCap,
  story: BookOpen,
}

export default function ProfilePage() {
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState('profile')
  const [tweets, setTweets] = useState([])
  const [posts, setPosts] = useState([])
  const [loadingTweets, setLoadingTweets] = useState(false)
  const [loadingPosts, setLoadingPosts] = useState(false)
  const [copiedId, setCopiedId] = useState(null)
  const [tweetFilter, setTweetFilter] = useState('all')

  const initial = user?.email?.[0]?.toUpperCase() || 'U'

  // Fetch tweets when tab changes
  useEffect(() => {
    if (activeTab === 'tweets' && user?.id && tweets.length === 0) {
      fetchTweets()
    }
  }, [activeTab, user])

  // Fetch posts when tab changes
  useEffect(() => {
    if (activeTab === 'posts' && user?.id && posts.length === 0) {
      fetchPosts()
    }
  }, [activeTab, user])

  const fetchTweets = async () => {
    if (!user?.id) return
    try {
      setLoadingTweets(true)
      const response = await fetch(`/api/v1/tweets?user_id=${user.id}`)
      if (response.ok) {
        const data = await response.json()
        setTweets(data)
      }
    } catch (err) {
      console.error('Failed to fetch tweets:', err)
    } finally {
      setLoadingTweets(false)
    }
  }

  const fetchPosts = async () => {
    if (!user?.id) return
    try {
      setLoadingPosts(true)
      const response = await fetch(`/api/v1/linkedin-posts?user_id=${user.id}`)
      if (response.ok) {
        const data = await response.json()
        setPosts(data)
      }
    } catch (err) {
      console.error('Failed to fetch posts:', err)
    } finally {
      setLoadingPosts(false)
    }
  }

  const handleCopy = async (text, id) => {
    await navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const handleApproveTweet = async (id) => {
    try {
      const response = await fetch(`/api/v1/tweets/${id}/approve`, { method: 'POST' })
      if (response.ok) {
        setTweets(tweets.map(t =>
          t.id === id ? { ...t, approved: true, approved_at: new Date().toISOString() } : t
        ))
      }
    } catch (err) {
      console.error('Failed to approve tweet:', err)
    }
  }

  const filteredTweets = tweets.filter(t => {
    if (tweetFilter === 'approved') return t.approved
    if (tweetFilter === 'pending') return !t.approved
    return true
  })

  const tweetStats = {
    total: tweets.length,
    approved: tweets.filter(t => t.approved).length,
    pending: tweets.filter(t => !t.approved).length,
  }

  return (
    <div className="p-6 animate-fade-in">
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold">Profile</h1>
            <p className="text-sm text-muted-foreground">Manage your account and content</p>
          </div>
          <TabsList>
            <TabsTrigger value="profile" className="gap-2">
              <User className="h-4 w-4" />
              Profile
            </TabsTrigger>
            <TabsTrigger value="tweets" className="gap-2">
              <Twitter className="h-4 w-4" />
              Tweets
            </TabsTrigger>
            <TabsTrigger value="posts" className="gap-2">
              <Linkedin className="h-4 w-4" />
              Posts
            </TabsTrigger>
          </TabsList>
        </div>

        {/* Profile Tab */}
        <TabsContent value="profile" className="space-y-6 max-w-4xl">
          {/* Profile header */}
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-start gap-6">
                <Avatar className="h-20 w-20">
                  <AvatarFallback className="text-2xl">{initial}</AvatarFallback>
                </Avatar>

                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <h2 className="text-xl font-semibold">{user?.email}</h2>
                    <Badge variant="secondary" className="capitalize">
                      {user?.role}
                    </Badge>
                  </div>

                  <p className="text-muted-foreground mb-4">
                    Member since {new Date().toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}
                  </p>

                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" className="gap-2">
                      <Settings className="h-4 w-4" />
                      Edit Profile
                    </Button>
                    <Button variant="outline" size="sm" className="gap-2">
                      <Key className="h-4 w-4" />
                      API Keys
                    </Button>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Access Control */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Shield className="h-5 w-5 text-primary" />
                Access Control
              </CardTitle>
              <CardDescription>Your organization and security settings</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid sm:grid-cols-3 gap-4">
                <div className="p-4 rounded-lg bg-muted/50">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
                    <Building2 className="h-4 w-4" />
                    Tenant
                  </div>
                  <p className="font-mono font-medium">{user?.tenant_id}</p>
                </div>

                <div className="p-4 rounded-lg bg-muted/50">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
                    <User className="h-4 w-4" />
                    Department
                  </div>
                  <p className="font-medium capitalize">{user?.department}</p>
                </div>

                <div className="p-4 rounded-lg bg-muted/50">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
                    <Shield className="h-4 w-4" />
                    Role
                  </div>
                  <p className="font-medium capitalize">{user?.role}</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Notifications */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Bell className="h-5 w-5 text-primary" />
                Notifications
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {[
                { label: 'Email notifications for approved content', enabled: true },
                { label: 'Daily usage summary', enabled: false },
                { label: 'New paper recommendations', enabled: true },
                { label: 'Weekly digest', enabled: false },
              ].map((item) => (
                <div key={item.label} className="flex items-center justify-between py-2">
                  <span className="text-sm">{item.label}</span>
                  <div
                    className={`w-10 h-6 rounded-full p-1 cursor-pointer transition-colors ${
                      item.enabled ? 'bg-primary' : 'bg-muted'
                    }`}
                  >
                    <div
                      className={`w-4 h-4 rounded-full bg-white transition-transform ${
                        item.enabled ? 'translate-x-4' : ''
                      }`}
                    />
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Export */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Download className="h-5 w-5 text-primary" />
                Export Data
              </CardTitle>
              <CardDescription>Download your data and content</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid sm:grid-cols-2 gap-2">
                <Button variant="outline" className="justify-start gap-2">
                  <Download className="h-4 w-4" />
                  Export Tweets
                </Button>
                <Button variant="outline" className="justify-start gap-2">
                  <Download className="h-4 w-4" />
                  Export LinkedIn Posts
                </Button>
                <Button variant="outline" className="justify-start gap-2">
                  <Download className="h-4 w-4" />
                  Export Expenses
                </Button>
                <Button variant="outline" className="justify-start gap-2">
                  <Download className="h-4 w-4" />
                  Export Chat History
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tweets Tab */}
        <TabsContent value="tweets" className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-muted text-sm">
                <span>Total: {tweetStats.total}</span>
              </div>
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-green-500/10 text-green-600 text-sm">
                <CheckCircle className="h-3.5 w-3.5" />
                <span>Approved: {tweetStats.approved}</span>
              </div>
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-500/10 text-amber-600 text-sm">
                <Clock className="h-3.5 w-3.5" />
                <span>Pending: {tweetStats.pending}</span>
              </div>
            </div>
            <Link to="/chat">
              <Button className="gap-2">
                <Plus className="h-4 w-4" />
                Generate Tweet
              </Button>
            </Link>
          </div>

          <Tabs value={tweetFilter} onValueChange={setTweetFilter}>
            <TabsList>
              <TabsTrigger value="all">All</TabsTrigger>
              <TabsTrigger value="approved">Approved</TabsTrigger>
              <TabsTrigger value="pending">Pending</TabsTrigger>
            </TabsList>

            <TabsContent value={tweetFilter} className="mt-4">
              {loadingTweets ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin text-primary" />
                </div>
              ) : filteredTweets.length === 0 ? (
                <Card className="p-12 text-center">
                  <Twitter className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                  <h3 className="text-lg font-medium mb-2">No tweets yet</h3>
                  <p className="text-muted-foreground mb-4">Start chatting to generate your first tweet</p>
                  <Link to="/chat">
                    <Button>Go to Chat</Button>
                  </Link>
                </Card>
              ) : (
                <div className="grid gap-4">
                  {filteredTweets.map((tweet) => (
                    <Card key={tweet.id}>
                      <CardContent className="pt-6">
                        <div className="flex items-start justify-between gap-4 mb-4">
                          <div className="flex items-center gap-2">
                            <Badge variant="outline">{tweet.topic}</Badge>
                            {tweet.approved ? (
                              <Badge className="gap-1 bg-green-500/10 text-green-600 hover:bg-green-500/20">
                                <Check className="h-3 w-3" />
                                Approved
                              </Badge>
                            ) : (
                              <Badge className="gap-1 bg-amber-500/10 text-amber-600 hover:bg-amber-500/20">
                                <Clock className="h-3 w-3" />
                                Pending
                              </Badge>
                            )}
                          </div>
                          {tweet.quality_score && (
                            <div className="flex items-center gap-1">
                              <Star className="h-4 w-4 text-amber-500" />
                              <span className="font-medium">{tweet.quality_score}/10</span>
                            </div>
                          )}
                        </div>

                        <div className="p-4 rounded-lg bg-muted/50 mb-4">
                          <p className="whitespace-pre-wrap">{tweet.final_content || tweet.draft_content}</p>
                        </div>

                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-4 text-sm text-muted-foreground">
                            <span className="flex items-center gap-1">
                              <RotateCcw className="h-3 w-3" />
                              {tweet.iterations} iteration(s)
                            </span>
                            <span>{formatDate(tweet.created_at)}</span>
                            <span>{(tweet.final_content || tweet.draft_content || '').length}/280</span>
                          </div>

                          <div className="flex gap-2">
                            {!tweet.approved && (
                              <Button
                                size="sm"
                                onClick={() => handleApproveTweet(tweet.id)}
                                className="gap-1"
                              >
                                <Check className="h-4 w-4" />
                                Approve
                              </Button>
                            )}
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleCopy(tweet.final_content || tweet.draft_content, tweet.id)}
                              className="gap-1"
                            >
                              {copiedId === tweet.id ? (
                                <>
                                  <Check className="h-4 w-4 text-green-500" />
                                  Copied
                                </>
                              ) : (
                                <>
                                  <Copy className="h-4 w-4" />
                                  Copy
                                </>
                              )}
                            </Button>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </TabsContent>
          </Tabs>
        </TabsContent>

        {/* LinkedIn Posts Tab */}
        <TabsContent value="posts" className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-muted text-sm">
                <FileText className="h-3.5 w-3.5" />
                <span>Total: {posts.length}</span>
              </div>
            </div>
            <Link to="/chat">
              <Button className="gap-2">
                <Plus className="h-4 w-4" />
                Create Post
              </Button>
            </Link>
          </div>

          {loadingPosts ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : posts.length === 0 ? (
            <Card className="p-12 text-center">
              <Linkedin className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
              <h3 className="text-lg font-medium mb-2">No posts yet</h3>
              <p className="text-muted-foreground mb-4">Start chatting to generate your first LinkedIn post</p>
              <Link to="/chat">
                <Button>Go to Chat</Button>
              </Link>
            </Card>
          ) : (
            <div className="grid gap-4">
              {posts.map((post) => {
                const StyleIcon = styleIcons[post.style] || FileText
                return (
                  <Card key={post.id}>
                    <CardContent className="pt-6">
                      <div className="flex items-start justify-between gap-4 mb-4">
                        <div>
                          <h3 className="text-lg font-semibold mb-2">{post.topic}</h3>
                          <div className="flex items-center gap-2">
                            <Badge variant="secondary" className="gap-1">
                              <StyleIcon className="h-3 w-3" />
                              {post.style || 'insight'}
                            </Badge>
                            {post.quality_score && (
                              <Badge variant="outline" className="gap-1">
                                <Star className="h-3 w-3 text-amber-500" />
                                {post.quality_score}/10
                              </Badge>
                            )}
                            <Badge variant="outline" className="gap-1">
                              <RotateCcw className="h-3 w-3" />
                              {post.iterations} iter
                            </Badge>
                          </div>
                        </div>
                        <span className="text-sm text-muted-foreground">{formatDate(post.created_at)}</span>
                      </div>

                      {post.outline && (
                        <details className="mb-4">
                          <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
                            View outline
                          </summary>
                          <pre className="mt-2 p-3 rounded-lg bg-muted text-sm whitespace-pre-wrap">
                            {post.outline}
                          </pre>
                        </details>
                      )}

                      <ScrollArea className="h-[200px] rounded-lg border p-4">
                        <p className="whitespace-pre-wrap text-sm">{post.final_content || post.draft_content}</p>
                      </ScrollArea>

                      <div className="flex items-center justify-between mt-4">
                        <div className="text-sm text-muted-foreground">
                          {(post.final_content || '').length} chars | {(post.final_content || '').split(' ').length} words
                        </div>

                        <div className="flex gap-2">
                          <Link to="/chat" state={{ initialPrompt: `Regenerate LinkedIn post about: ${post.topic}` }}>
                            <Button variant="outline" size="sm" className="gap-1">
                              <RotateCcw className="h-4 w-4" />
                              Regenerate
                            </Button>
                          </Link>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleCopy(post.final_content || post.draft_content, post.id)}
                            className="gap-1"
                          >
                            {copiedId === post.id ? (
                              <>
                                <Check className="h-4 w-4 text-green-500" />
                                Copied
                              </>
                            ) : (
                              <>
                                <Copy className="h-4 w-4" />
                                Copy
                              </>
                            )}
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
