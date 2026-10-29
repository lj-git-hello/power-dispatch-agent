export interface PlanApplyPayload {
  plan_id: string;
  substation_name: string;
  voltage_level: string;
  work_content: string;
  safety_measures: string;
}

export interface StreamEvent {
  type: 'token' | 'workflow_interrupt' | 'audit_result';
  content?: string;
  data?: any;
  waiting_for?: string;
}

// 消费 SSE 流式打字机与事件（带 Buffer 缓冲区防截断）
export async function fetchDispatchStream(
  payload: PlanApplyPayload,
  onEvent: (event: StreamEvent) => void
) {
  const response = await fetch('http://127.0.0.1:8000/api/v1/dispatch/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = ''; // 缓冲区，用来拼接跨分包的不完整字符

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');

    // 最后一个分块可能是不完整的，留在 buffer 里等待下一次网络包拼接
    buffer = parts.pop() || '';

    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith('data:')) {
        const rawJson = line.replace(/^data:\s*/, '').trim();
        if (rawJson) {
          try {
            const parsed: StreamEvent = JSON.parse(rawJson);
            onEvent(parsed);
          } catch (e) {
            console.error('JSON parse error on raw chunk:', rawJson, e);
          }
        }
      }
    }
  }

  // 处理最后剩余的尾巴
  if (buffer.trim().startsWith('data:')) {
    const rawJson = buffer.trim().replace(/^data:\s*/, '').trim();
    if (rawJson) {
      try {
        const parsed: StreamEvent = JSON.parse(rawJson);
        onEvent(parsed);
      } catch (e) { }
    }
  }
}