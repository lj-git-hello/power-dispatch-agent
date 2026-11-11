/**
 * RenderTicker —— 基于 requestAnimationFrame 的恒帧打字机缓冲调度器。
 *
 * 待输出字符串先进入队列，调度器在每一帧平滑消费固定数量字符并回调，
 * 避免逐 token 直接写 DOM 造成的高频重排。当缓冲区堆积时自适应提高
 * 每帧消费速率，尽快排空，防止长文本推流越积越多。
 */

/** 每帧基础消费字符数 */
const BASE_CHARS_PER_FRAME = 2
/** 堆积阈值与对应升频档位（达到阈值采用该档每帧字符数） */
const SPEED_TIERS: ReadonlyArray<{ threshold: number; chars: number }> = [
  { threshold: 100, chars: 12 },
  { threshold: 30, chars: 6 },
]

export type TickHandler = (consumed: string) => void

export class RenderTicker {
  private readonly queue: string[] = []
  private pending = ''
  private rafId: number | null = null
  private readonly onTick: TickHandler

  constructor(onTick: TickHandler) {
    this.onTick = onTick
  }

  /** 字符串入队（可被多次调用），并确保调度器运行。 */
  enqueue(text: string): void {
    if (!text) return
    this.queue.push(text)
    this.start()
  }

  /** 当前缓冲区总字符数（未消费的队列 + 待处理段）。 */
  get bufferedLength(): number {
    return this.pending.length + this.queue.reduce((sum, part) => sum + part.length, 0)
  }

  /** 根据堆积长度返回当前每帧消费字符数。 */
  private charsForCurrentLoad(): number {
    const length = this.bufferedLength
    for (const tier of SPEED_TIERS) {
      if (length >= tier.threshold) return tier.chars
    }
    return BASE_CHARS_PER_FRAME
  }

  /** 从缓冲区取出至多 count 个字符。 */
  private drainChars(count: number): string {
    let remaining = count
    let output = ''

    if (this.pending) {
      output += this.pending.slice(0, remaining)
      this.pending = this.pending.slice(output.length)
      remaining -= output.length
    }

    while (remaining > 0 && this.queue.length > 0) {
      const part = this.queue[0]
      const taken = part.slice(0, remaining)
      output += taken
      if (taken.length === part.length) {
        this.queue.shift()
      } else {
        this.queue[0] = part.slice(taken.length)
      }
      remaining -= taken.length
    }

    return output
  }

  private frame = (): void => {
    const chars = this.charsForCurrentLoad()
    const consumed = this.drainChars(chars)
    if (consumed) this.onTick(consumed)

    if (this.bufferedLength > 0) {
      this.rafId = requestAnimationFrame(this.frame)
    } else {
      // 缓冲区排空，停止调度，等待下次 enqueue
      this.rafId = null
    }
  }

  /** 启动调度（已在运行则忽略）。 */
  start(): void {
    if (this.rafId !== null) return
    this.rafId = requestAnimationFrame(this.frame)
  }

  /** 停止调度但保留缓冲区。 */
  stop(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
  }

  /** 清空缓冲区并停止。 */
  clear(): void {
    this.stop()
    this.queue.length = 0
    this.pending = ''
  }

  /**
   * 立即排空缓冲区并停止调度（流结束时调用）。
   *
   * 正常打字机按帧消费，流结束后若仍有积压会出现"尾字滞留"，
   * 故在 done 事件里一次性吐出剩余内容，保证落盘内容完整。
   */
  flush(): void {
    const consumed = this.drainChars(this.bufferedLength)
    this.stop()
    if (consumed) this.onTick(consumed)
  }
}
