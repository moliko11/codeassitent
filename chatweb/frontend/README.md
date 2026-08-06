# Chat Template

A standalone **chat / conversation UI layout** extracted from
[DeepTutor](https://github.com/HKUDS/DeepTutor)'s web frontend, packaged as a
clean Next.js project for secondary development (二开).

It keeps the **layout and visual system** of DeepTutor's chat — sidebar,
title bar, message column (user/assistant bubbles, Markdown + code blocks),
composer, four-theme switching — and replaces all backend coupling
(WebSocket, REST, tools, capabilities) with a **mock provider** that simulates
streaming. No backend required: `npm install && npm run dev` and it runs.

---

## Quick start

```bash
cd chat-template
npm install
npm run dev
# open http://localhost:3000
```

Requires Node.js 18.18+ (tested conceptually against Node 22).

---

## What's inside

```
chat-template/
├── app/
│   ├── globals.css        # Theme palettes + prose typography + animations (ported)
│   ├── layout.tsx         # Root layout: ThemeScript + AppShellProvider
│   └── page.tsx           # The chat shell: Sidebar + main(header + messages + composer)
├── components/
│   ├── ThemeScript.tsx    # Pre-hydration theme apply (no FOUC)
│   ├── Sidebar.tsx        # Workspace rail: nav + recents + collapse (220px / 60px)
│   ├── ChatHeader.tsx     # Editable session title + theme switcher
│   ├── MessageList.tsx    # Message column + empty state + streaming indicator
│   ├── Composer.tsx       # Auto-sizing input + send/stop, Enter to send
│   ├── MarkdownRenderer.tsx   # react-markdown + GFM
│   ├── RichCodeBlock.tsx  # Prism syntax highlighting
│   └── ThemeSwitcher.tsx  # Popover to switch the 4 themes
├── context/
│   ├── AppShellContext.tsx    # UI prefs (theme, sidebar, code-block) -> localStorage
│   └── ChatContext.tsx        # MOCK chat provider (messages + simulated streaming)
├── lib/
│   ├── cn.ts              # clsx + tailwind-merge
│   ├── theme.ts           # Theme type + apply/persist (ported)
│   ├── mockData.ts        # Sample sessions + canned reply generator
│   └── useChatAutoScroll.ts   # Pin-to-bottom while streaming
├── package.json
├── tailwind.config.js     # Semantic colors -> CSS variables
├── postcss.config.js
├── tsconfig.json
└── next.config.js
```

---

## The theme system (the look)

All colors are **CSS variables** defined in `app/globals.css`. Four palettes:

| Theme id  | Class           | Look                                  |
| --------- | --------------- | ------------------------------------- |
| `snow`    | `.theme-snow`   | Pure-white neutral, blue accent (default) |
| `light`   | `:root`         | Cream — warm off-white, terracotta    |
| `dark`    | `.dark`         | Warm near-black, terracotta           |
| `glass`   | `.theme-glass`  | Translucent purple on near-black      |

Switching theme = swapping one variable block on `<html>`. Every component
uses tokens like `bg-[var(--card)]`, `text-[var(--foreground)]`, so the whole
UI re-themes instantly. `tailwind.config.js` maps the same tokens to Tailwind
color utilities (`bg-card`, `text-foreground`, …).

---

## Going real (replacing the mock)

The only backend-coupled file is `context/ChatContext.tsx`. It exposes:

```ts
interface ChatContextValue {
  messages: ChatMessage[];        // { id, role, content, streaming?, createdAt }
  isStreaming: boolean;
  sessions: SessionSummary[];     // sidebar recents
  activeSessionId: string | null;
  sendMessage: (content: string) => void;
  stopStreaming: () => void;
  newChat: () => void;
  selectSession: (id: string) => void;
}
```

To connect a real backend:

1. **REST** — in `sendMessage`, POST to your `/api/chat` and append the
   response to `messages`. Set `streaming: true` while pending.
2. **WebSocket / SSE** — open a socket on mount, push deltas into the active
   assistant message's `content` (exactly like the mock's `setInterval`
   loop does), flip `streaming: false` on done.
3. **Sessions** — load `sessions` from your API in a `useEffect`; in
   `selectSession`, fetch that session's `messages`.

`ChatMessage` and `SessionSummary` types live in `lib/mockData.ts`.

---

## Customization notes

- **Fonts**: uses a system stack by default (builds offline). To match
  DeepTutor exactly, install Geist + Lora via `next/font/google` and set the
  `--font-sans` / `--font-serif` CSS variables (see `app/layout.tsx` comment).
- **i18n**: removed for simplicity. Add `react-i18next` + a provider around
  the tree if you need multi-language UI strings.
- **Code blocks**: line-numbers / wrap toggles are wired through
  `AppShellContext` but have no settings UI — add one (a small dropdown like
  `ThemeSwitcher`) if you want them user-toggleable.
- **Streaming feel**: token cadence is `28ms` in `ChatContext.tsx`; tune it.

---

## Provenance

Layout, theme tokens, and component structure are ported from DeepTutor's
`web/` (Apache-2.0). Backend logic (UnifiedChatContext, WebSocket client,
tools, capability gating, pickers) was intentionally **removed** to keep this
a pure layout template.
