// Chat client — posts to the same-origin /api proxy, which injects the backend
// secret and forwards to FastAPI's POST /api/students/{slug}/chat. Mirrors the
// fetch style of api/analysis.ts, but sends a JSON body (message + history).

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export async function sendChat(
  slug: string,
  message: string,
  history: ChatMessage[],
): Promise<string> {
  const response = await fetch(`/api/students/${encodeURIComponent(slug)}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  });

  if (!response.ok) {
    let detail = `Chat request failed (${response.status}).`;
    try {
      const data = await response.json();
      if (data && typeof data.detail === 'string') detail = data.detail;
    } catch {
      /* keep the default message */
    }
    throw new Error(detail);
  }

  const data = (await response.json()) as { reply?: string };
  return data.reply ?? '';
}
