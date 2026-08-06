"use client";

import { useEffect, useState } from "react";
import { ChatProvider, useChat } from "@/context/ChatContext";
import Sidebar from "@/components/Sidebar";
import ChatHeader from "@/components/ChatHeader";
import MessageList from "@/components/MessageList";
import Composer from "@/components/Composer";

function ChatShell() {
  const { messages, sendMessage, sessions, activeSessionId } = useChat();
  const activeSession = sessions.find((s) => s.id === activeSessionId);
  const [title, setTitle] = useState("新对话");

  // Sync the title when the active session changes.
  useEffect(() => {
    if (activeSession) setTitle(activeSession.title);
    else if (messages.length === 0) setTitle("新对话");
  }, [activeSessionId, activeSession, messages.length]);

  const handleSend = (text: string) => {
    // First message in a fresh chat seeds the title.
    if (messages.length === 0 && !activeSessionId) {
      setTitle(text.slice(0, 24) || "新对话");
    }
    sendMessage(text);
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col bg-[var(--background)]">
        <ChatHeader title={title} onRename={setTitle} />
        <MessageList onPickSuggestion={handleSend} />
        <Composer />
      </main>
    </div>
  );
}

export default function Page() {
  return (
    <ChatProvider>
      <ChatShell />
    </ChatProvider>
  );
}
