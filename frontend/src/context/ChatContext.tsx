import { message } from 'antd';
import { createContext, ReactNode, useContext, useState } from 'react';
import api from '../utils/api';
import type { ChatSource } from '../types/api';

interface ChatContextType {
  messages: Array<{
    role: 'user' | 'assistant';
    content: string;
    sources?: ChatSource[];
  }>;
  sendMessage: (
    query: string,
    websiteId?: string,
    sessionId?: string,
  ) => Promise<void>;
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
  const [messages, setMessages] = useState<
    Array<{ role: 'user' | 'assistant'; content: string; sources?: ChatSource[] }>
  >([]);
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

  const setAssistantSources = (sources: ChatSource[]) => {
    if (!sources || sources.length === 0) return;
    setMessages((prev) => {
      const copy = [...prev];
      const last = copy[copy.length - 1];
      if (last && last.role === 'assistant') {
        copy[copy.length - 1] = { ...last, sources };
      }
      return copy;
    });
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
            } else if (data.done === true && Array.isArray(data.sources)) {
              // Stream finished; attach cited sources to the last answer.
              setAssistantSources(data.sources);
            }
            // `done: true` (without sources) is the normal stream terminator.
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
    } catch (error) {
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
