import { message } from 'antd';
import { createContext, ReactNode, useContext, useState } from 'react';
import api from '../utils/api';
import type { ChatSource, ConversationMessage } from '../types/api';

interface ChatMessageItem {
  // `agent` is a teammate's reply from the live inbox (V3-43).
  role: 'user' | 'assistant' | 'agent';
  content: string;
  sources?: ChatSource[];
  // The stored assistant row: a rating sends it back so the admin review can
  // show the exact question/answer pair (F4).
  message_id?: string;
}

interface ChatContextType {
  messages: ChatMessageItem[];
  sendMessage: (
    query: string,
    websiteId?: string,
    sessionId?: string,
  ) => Promise<void>;
  loadMessages: (items: ConversationMessage[]) => void;
  ingestSite: (url: string) => Promise<void>;
  loading: boolean;
  selectedWebsiteId: string | null;
  setSelectedWebsiteId: (id: string | null) => void;
}

const ChatContext = createContext<ChatContextType | undefined>(undefined);

export const useChat = () => {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error('useChat must be used within ChatProvider');
  }
  return context;
};

interface Props {
  children: ReactNode;
}

export const ChatProvider = ({ children }: Props) => {
  const [messages, setMessages] = useState<ChatMessageItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedWebsiteId, setSelectedWebsiteId] = useState<string | null>(
    null,
  );

  const appendAssistantChunk = (chunk: string) => {
    setMessages((prev) => {
      const copy = [...prev];
      const last = copy[copy.length - 1];
      if (last && last.role === 'assistant') {
        copy[copy.length - 1] = { ...last, content: last.content + chunk };
      } else {
        copy.push({ role: 'assistant', content: chunk });
      }
      return copy;
    });
  };

  const setAssistantError = (text: string) => {
    setMessages((prev) => {
      const copy = [...prev];
      const last = copy[copy.length - 1];
      if (last && last.role === 'assistant') {
        copy[copy.length - 1] = { ...last, content: text };
      } else {
        copy.push({ role: 'assistant', content: text });
      }
      return copy;
    });
  };

  const appendAssistantError = (text: string) => {
    setMessages((prev) => {
      const copy = [...prev];
      const last = copy[copy.length - 1];
      const note = `⚠️ ${text}`;
      if (last && last.role === 'assistant') {
        copy[copy.length - 1] = {
          ...last,
          content: last.content ? `${last.content}\n\n${note}` : note,
        };
      } else {
        copy.push({ role: 'assistant', content: note });
      }
      return copy;
    });
  };

  const setAssistantMeta = (sources?: ChatSource[], messageId?: string) => {
    if ((!sources || sources.length === 0) && !messageId) return;
    setMessages((prev) => {
      const copy = [...prev];
      const last = copy[copy.length - 1];
      if (last && last.role === 'assistant') {
        copy[copy.length - 1] = {
          ...last,
          ...(sources && sources.length > 0 ? { sources } : {}),
          ...(messageId ? { message_id: messageId } : {}),
        };
      }
      return copy;
    });
  };

  const loadMessages = (items: ConversationMessage[]) => {
    setMessages(
      items
        // Agent replies belong in the transcript too: a session that went
        // through a human must not read as if the bot answered everything.
        .filter(
          (m) => m.role === 'user' || m.role === 'assistant' || m.role === 'agent',
        )
        .map((m) => ({ role: m.role, content: m.message, message_id: m.id })),
    );
  };

  const sendMessage = async (
    query: string,
    websiteId?: string,
    sessionId?: string,
  ) => {
    setLoading(true);
    setMessages((prev) => [
      ...prev,
      { role: 'user' as const, content: query },
      { role: 'assistant' as const, content: '' },
    ]);

    try {
      const baseUrl = (api.defaults.baseURL || '').replace(/\/$/, '');
      const response = await fetch(`${baseUrl}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(localStorage.getItem('access_token')
            ? { Authorization: `Bearer ${localStorage.getItem('access_token')}` }
            : {}),
        },
        body: JSON.stringify({
          question: query,
          website_id: websiteId,
          session_id: sessionId,
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`chat failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            const data = JSON.parse(payload);
            if (typeof data.chunk === 'string') {
              appendAssistantChunk(data.chunk);
            } else if (typeof data.error === 'string') {
              appendAssistantError(data.error);
            } else if (data.done === true) {
              // Stream finished: attach citations and the stored row id.
              setAssistantMeta(
                Array.isArray(data.sources) ? data.sources : undefined,
                typeof data.message_id === 'string' ? data.message_id : undefined,
              );
            }
            // `done: true` with neither field is the normal terminator.
          } catch {
            // ignore malformed SSE line
          }
        }
      }
    } catch (error) {
      console.error('Chat stream error', error);
      message.error('Chat error');
      setAssistantError('Sorry, something went wrong.');
    } finally {
      setLoading(false);
    }
  };

  const ingestSite = async (url: string) => {
    setLoading(true);
    try {
      await api.post('/ingest', { sitemap_url: url });
      message.success('Site ingested successfully!');
    } catch {
      message.error('Ingest error');
    } finally {
      setLoading(false);
    }
  };

  return (
      <ChatContext.Provider
        value={{
          messages,
          sendMessage,
          loadMessages,
          ingestSite,
          loading,
          selectedWebsiteId,
          setSelectedWebsiteId,
        }}
      >
      {children}
    </ChatContext.Provider>
  );
};
