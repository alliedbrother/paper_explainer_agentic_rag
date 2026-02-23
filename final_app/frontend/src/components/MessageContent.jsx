import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import 'katex/dist/katex.min.css'

/**
 * MessageContent - Renders markdown with LaTeX math support
 *
 * Supports:
 * - Inline math: $x^2$ or \(x^2\)
 * - Block math: $$x^2$$ or \[x^2\]
 * - GitHub Flavored Markdown (tables, strikethrough, etc.)
 */
export function MessageContent({ content, className = '' }) {
  const [hasError, setHasError] = useState(false)

  // Reset error state when content changes
  useEffect(() => {
    setHasError(false)
  }, [content])

  if (!content) return null

  // If there was an error, fall back to plain text
  if (hasError) {
    return (
      <div className={`whitespace-pre-wrap ${className}`}>
        {content}
      </div>
    )
  }

  // Pre-process content to convert \[ \] to $$ $$ format for remark-math
  let processedContent = content
  try {
    processedContent = content
      .replace(/\\\[/g, '$$')
      .replace(/\\\]/g, '$$')
      .replace(/\\\(/g, '$')
      .replace(/\\\)/g, '$')
  } catch (e) {
    console.error('Error processing content:', e)
    return <div className={`whitespace-pre-wrap ${className}`}>{content}</div>
  }

  return (
    <div className={`prose prose-sm dark:prose-invert max-w-none ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkMath, remarkGfm]}
        rehypePlugins={[rehypeKatex]}
        components={{
          // Customize heading sizes for chat
          h1: ({ children }) => <h1 className="text-lg font-bold mt-4 mb-2">{children}</h1>,
          h2: ({ children }) => <h2 className="text-base font-bold mt-3 mb-2">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-bold mt-2 mb-1">{children}</h3>,
          // Style paragraphs
          p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
          // Style lists
          ul: ({ children }) => <ul className="list-disc pl-4 mb-2 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="text-sm">{children}</li>,
          // Style code blocks
          code: ({ node, className, children, ...props }) => {
            // Check if this is inline code (no className with language- prefix means inline)
            const isInline = !className?.includes('language-')
            if (isInline) {
              return (
                <code className="px-1 py-0.5 rounded bg-muted text-sm font-mono" {...props}>
                  {children}
                </code>
              )
            }
            return (
              <code className="text-xs font-mono" {...props}>
                {children}
              </code>
            )
          },
          // Style pre blocks (code blocks with language)
          pre: ({ children }) => (
            <pre className="p-3 rounded-lg bg-zinc-950 text-zinc-100 overflow-x-auto my-2">
              {children}
            </pre>
          ),
          // Style blockquotes
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-primary/50 pl-3 italic text-muted-foreground my-2">
              {children}
            </blockquote>
          ),
          // Style tables
          table: ({ children }) => (
            <div className="overflow-x-auto my-2">
              <table className="min-w-full border-collapse border border-border text-sm">
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-border bg-muted px-2 py-1 text-left font-medium">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-border px-2 py-1">{children}</td>
          ),
          // Style links
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
              {children}
            </a>
          ),
          // Style strong/bold
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        }}
      >
        {processedContent}
      </ReactMarkdown>
    </div>
  )
}
