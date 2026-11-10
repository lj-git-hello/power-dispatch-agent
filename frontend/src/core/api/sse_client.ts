/**
 * SSEClient —— 通用 Server-Sent Events 客户端。
 *
 * - 基于 fetch + ReadableStream 解析事件（支持自定义请求头，如鉴权）；
 * - 断线后指数退避自动重连；
 * - 显式识别并吞掉以 ":" 开头的注释帧（后端每 15s 发送的 ":ping" 保活），
 *   不向业务回调分发。
 */

/** 退避参数 */
const INITIAL_BACKOFF_MS = 1000
const MAX_BACKOFF_MS = 30000
const BACKOFF_FACTOR = 2

/** 解析后的 SSE 事件 */
export interface SSEEvent {
  event: string
  data: string
  id: string
}

export interface SSEClientOptions {
  method?: 'GET' | 'POST'
  body?: BodyInit
  headers?: Record<string, string>
  /** 业务事件回调 */
  onEvent: (event: SSEEvent) => void
  /** 可选：状态回调（重连等） */
  onStatus?: (status: 'connecting' | 'open' | 'reconnecting') => void
  /** 最大重连次数；不填则无限重连 */
  maxRetries?: number
}

/** 判定 SSE 注释行（如 ":ping"），此类帧被吞掉 */
function isCommentLine(line: string): boolean {
  return line.startsWith(':')
}

/** 将一段 SSE 文本块按事件解析并产出事件 */
function parseChunk(chunk: string): SSEEvent[] {
  const events: SSEEvent[] = []
  let event = 'message'
  const dataParts: string[] = []
  let id = ''

  for (const line of chunk.split('\n')) {
    // 空行 = 事件边界
    if (line === '') {
      if (dataParts.length > 0) {
        events.push({ event, data: dataParts.join('\n'), id })
      }
      event = 'message'
      dataParts.length = 0
      id = ''
      continue
    }
    if (isCommentLine(line)) continue
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataParts.push(line.slice(5).trimStart())
    } else if (line.startsWith('id:')) {
      id = line.slice(3).trim()
    }
  }
  return events
}

export class SSEClient {
  private readonly url: string
  private readonly options: Required<Pick<SSEClientOptions, 'method' | 'headers'>> &
    SSEClientOptions
  private closed = false
  private retryCount = 0
  private abortController: AbortController | null = null

  constructor(url: string, options: SSEClientOptions) {
    this.url = url
    this.options = { method: 'GET', headers: {}, ...options }
  }

  /** 建立连接（含重连循环）。 */
  async connect(): Promise<void> {
    this.closed = false
    let backoff = INITIAL_BACKOFF_MS

    while (!this.closed) {
      this.options.onStatus?.(this.retryCount === 0 ? 'connecting' : 'reconnecting')
      this.abortController = new AbortController()

      try {
        const response = await fetch(this.url, {
          method: this.options.method,
          headers: { Accept: 'text/event-stream', ...this.options.headers },
          body: this.options.body,
          signal: this.abortController.signal,
        })
        if (!response.ok || !response.body) {
          throw new Error(`SSE connect failed: ${response.status}`)
        }

        this.retryCount = 0
        backoff = INITIAL_BACKOFF_MS
        this.options.onStatus?.('open')
        await this.readStream(response.body)
      } catch (error) {
        if (this.closed) return
        if (
          this.options.maxRetries !== undefined &&
          this.retryCount >= this.options.maxRetries
        ) {
          throw error
        }
      }

      if (this.closed) return

      // 等待退避后重连
      await this.delay(backoff)
      backoff = Math.min(backoff * BACKOFF_FACTOR, MAX_BACKOFF_MS)
      this.retryCount += 1
    }
  }

  /** 读取流并按 SSE 边界拼接（跨 chunk 的半行用 buffer 衔接）。 */
  private async readStream(stream: ReadableStream<Uint8Array>): Promise<void> {
    const reader = stream.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break

      // 仅在完整行/事件边界解析：保留最后一个不完整片段
      buffer += decoder.decode(value, { stream: true })
      const boundary = buffer.lastIndexOf('\n\n')
      if (boundary === -1) continue

      const complete = buffer.slice(0, boundary + 2)
      buffer = buffer.slice(boundary + 2)
      for (const event of parseChunk(complete)) {
        this.options.onEvent(event)
      }
    }
  }

  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }

  /** 主动关闭，不再重连。 */
  close(): void {
    this.closed = true
    this.abortController?.abort()
  }
}
