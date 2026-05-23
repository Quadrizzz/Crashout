# Frontend Updates Required

## Overview
The backend has been updated to use a PostgreSQL database with proper session management, message persistence, and analysis result storage. The frontend needs to be updated to leverage these new capabilities.

## Backend API Endpoints Available

### Authentication
- `POST /api/auth/me` - Get current user info (requires Bearer token)

### Upload & Sessions
- `POST /api/upload` - Upload file, creates session and dataset profile
  - Returns: `{ session_id, profile, parquet_path }`
  - Saves to DB: Session + DatasetProfile

- `GET /api/sessions` - Get all user sessions
  - Returns: `{ sessions: [{ id, filename, parquet_path, created_at }] }`

- `GET /api/sessions/{session_id}/profile` - Get session with full profile
  - Returns: `{ session_id, parquet_path, filename, profile: {...} }`

### Chat & Messages
- `POST /api/chat` - Send message (streaming response)
  - Saves user message before streaming
  - Saves assistant message + analysis result after streaming
  - Returns SSE stream with progress and response events

- `GET /api/sessions/{session_id}/messages` - Get all messages for a session
  - Returns: `{ messages: [{ id, role, content, created_at, chart_config }] }`
  - Includes chart_config from AnalysisResult if available

## Database Schema

### User
- id (UUID from Supabase)
- email
- created_at

### Session
- id (UUID)
- user_id (FK)
- filename
- parquet_path (S3 URL)
- created_at

### DatasetProfile
- id (auto-increment)
- session_id (FK, unique)
- row_count
- column_count
- summary
- quality_flags (JSON array)
- columns (JSON object)
- created_at

### Message
- id (UUID)
- session_id (FK)
- user_id (FK)
- role ("user" | "assistant")
- content (text)
- created_at

### AnalysisResult
- id (auto-increment)
- message_id (FK, unique)
- chart_config (JSON, nullable)
- created_at

## Required Frontend Changes

### 1. Update Types (`src/types/index.ts`)

```typescript
// Update DatasetProfile to match backend structure
export interface DatasetProfile {
  row_count: number
  column_count: number
  summary: string
  quality_flags: string[]
  columns: Record<string, ColumnProfile>
}

// Add created_at to Message
export interface Message {
  id: string
  role: MessageRole
  content: string
  chart_config?: ChartConfig
  created_at?: string  // NEW
  isStreaming?: boolean
  node?: string
}

// Session should not include messages array (fetched separately)
export interface Session {
  id: string
  filename: string
  parquet_path: string
  created_at: string
  // Remove: profile, messages (fetched on demand)
}
```

### 2. Update API Functions (`src/lib/api.ts`)

Add new API functions:

```typescript
// Fetch all user sessions
export async function getSessions(token: string): Promise<{ sessions: Session[] }>

// Fetch session profile
export async function getSessionProfile(sessionId: string, token: string): Promise<{
  session_id: string
  parquet_path: string
  filename: string
  profile: DatasetProfile
}>

// Fetch messages for a session
export async function getSessionMessages(sessionId: string, token: string): Promise<{
  messages: Message[]
}>
```

Update `streamChat` to use new backend structure:
- Remove `datasetProfile` from request body (backend fetches from DB)
- Backend now expects: `{ session_id, parquet_path, messages, message }`

### 3. Create ChatContext (`src/context/ChatContext.tsx`)

Create a new context to manage:
- Sessions list (fetched from backend)
- Active session
- Messages for active session (fetched from backend)
- Loading states
- Session selection
- Message sending

Key functions:
- `loadSessions()` - Fetch all sessions on mount
- `selectSession(sessionId)` - Load session profile + messages
- `createSession(file)` - Upload file, add to sessions list
- `sendMessage(content)` - Send message via streaming API
- `refreshMessages()` - Reload messages for current session

### 4. Update App.tsx

- Remove local `sessions` state (use ChatContext)
- Remove `useChat` hook (use ChatContext)
- Load sessions from backend on mount
- When selecting a session, fetch its messages from backend
- Display persisted messages from database

### 5. Update useChat Hook (`src/hooks/useChat.ts`)

Option A: Convert to ChatContext (recommended)
Option B: Update to fetch messages from backend when session changes

Current issues:
- Messages are only stored in local state
- When switching sessions, messages are lost
- No persistence between page refreshes

New behavior:
- Fetch messages from backend when session is selected
- Append new messages to existing conversation
- Messages persist in database

### 6. Update Components

#### Sidebar (`src/components/layout/Sidebar.tsx`)
- Display sessions from backend with `created_at` timestamps
- Show loading state while fetching sessions

#### ChatThread (`src/components/chat/ChatThread.tsx`)
- Display messages with timestamps
- Handle loading state for message fetching
- Show empty state when no messages exist

#### ChatInput (`src/components/chat/ChatInput.tsx`)
- No major changes needed
- Ensure it works with ChatContext

### 7. Session Management Flow

**On App Load:**
1. Check authentication
2. Fetch all sessions: `GET /api/sessions`
3. Display sessions in sidebar

**On Session Select:**
1. Fetch session profile: `GET /api/sessions/{id}/profile`
2. Fetch session messages: `GET /api/sessions/{id}/messages`
3. Display messages in chat thread

**On File Upload:**
1. Upload file: `POST /api/upload`
2. Backend creates session + profile in DB
3. Add new session to sessions list
4. Select new session (no messages yet)

**On Send Message:**
1. Call streaming API: `POST /api/chat`
2. Backend saves user message immediately
3. Stream assistant response
4. Backend saves assistant message + analysis result
5. Append messages to local state
6. (Optional) Refresh messages from backend to ensure sync

### 8. Data Flow Changes

**Before (Current):**
- Upload → Get profile → Store in local state
- Send message → Stream response → Store in local state
- Switch session → Lose all messages
- Refresh page → Lose everything

**After (Updated):**
- Upload → Backend saves session + profile to DB
- Fetch sessions → Display in sidebar
- Select session → Fetch messages from DB
- Send message → Backend saves to DB → Stream response
- Switch session → Fetch messages from DB
- Refresh page → Fetch sessions + messages from DB

## Implementation Priority

1. **High Priority:**
   - Update types to match backend schema
   - Add API functions for sessions and messages
   - Create ChatContext with session/message management
   - Update App.tsx to use ChatContext
   - Fetch and display persisted messages

2. **Medium Priority:**
   - Add loading states and error handling
   - Add timestamps to message display
   - Improve session list with metadata

3. **Low Priority:**
   - Add session deletion
   - Add message editing/deletion
   - Add session search/filter
   - Add export functionality

## Testing Checklist

- [ ] Upload file creates session in database
- [ ] Sessions list loads from database
- [ ] Selecting session loads its messages
- [ ] Sending message saves to database
- [ ] Messages persist after page refresh
- [ ] Switching sessions shows correct messages
- [ ] Chart configs are preserved and displayed
- [ ] Multiple users see only their own sessions
- [ ] Authentication token is included in all requests
- [ ] Error handling for failed API calls

## Notes

- All API calls require `Authorization: Bearer {token}` header
- Backend validates session ownership (user can only access their sessions)
- Messages are ordered by `created_at` timestamp
- Chart configs are stored in `AnalysisResult` table, joined with messages
- Profile data structure changed from nested `overview` to flat structure
