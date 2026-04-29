import { message } from 'antd';
import { createContext, ReactNode, useContext, useState } from 'react';
import type { ChatResponse } from '../types/api';
import api from '../utils/api';

interface ChatContextType {
  messages: Array<{ role: 'user' | 'assistant'; content: string }>;
  sendMessage: (query: string, websiteId?: string) => Promise<void>;
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
    Array<{ role: 'user' | 'assistant'; content: string }>
  >([]);
  const [loading, setLoading] = useState(false);
  const [selectedWebsiteId, setSelectedWebsiteId] = useState<string | null>(
    null,
  );

  const sendMessage = async (query: string, websiteId?: string) => {
    setLoading(true);
    setMessages((prev) => [...prev, { role: 'user' as const, content: query }]);

    try {
      const url = websiteId
        ? `/chat?q=${encodeURIComponent(query)}&website_id=${websiteId}`
        : `/chat?q=${encodeURIComponent(query)}`;
      const response = await api.get<ChatResponse>(url);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant' as const, content: response.data.answer },
      ]);
    } catch (error) {
      message.error('Chat error');
      setMessages((prev) => [
        ...prev,
        { role: 'assistant' as const, content: 'Sorry, something went wrong.' },
      ]);
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
