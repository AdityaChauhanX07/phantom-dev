'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TaskStatus = 'queued' | 'running' | 'completed' | 'failed';

interface ActiveTask {
  task_id: string;
  goal: string;
  status: TaskStatus;
}

interface FeedEvent {
  id: string;
  timestamp: Date;
  type: string;
  message: string;
  textClass: string;
  badgeClass: string;
}

type WsStatus = 'connected' | 'reconnecting';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WS_URL: string =
  process.env.NEXT_PUBLIC_AGENT_WS_URL ?? 'ws://localhost:8000/ws/dashboard';

const MAX_EVENTS = 50;
const RECONNECT_DELAY_MS = 3_000;

const STATUS_BADGE: Record<TaskStatus, string> = {
  queued:    'bg-gray-800 text-gray-400',
  running:   'bg-blue-950 text-blue-300 animate-pulse',
  completed: 'bg-green-950 text-green-400',
  failed:    'bg-red-950 text-red-400',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let _idCounter = 0;
function makeId(): string {
  return `ev-${Date.now()}-${++_idCounter}`;
}

function fmtTime(d: Date): string {
  return d.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

// ---------------------------------------------------------------------------
// Dashboard component
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const [wsStatus, setWsStatus]         = useState<WsStatus>('reconnecting');
  const [executorCount, setExecutorCount] = useState(0);
  const [activeTask, setActiveTask]      = useState<ActiveTask | null>(null);
  const [events, setEvents]              = useState<FeedEvent[]>([]);

  const wsRef             = useRef<WebSocket | null>(null);
  const reconnectRef      = useRef<ReturnType<typeof setTimeout> | null>(null);
  const feedBottomRef     = useRef<HTMLDivElement | null>(null);

  // ── Push a new event to the top of the feed ────────────────────────────
  const pushEvent = useCallback(
    (partial: Omit<FeedEvent, 'id' | 'timestamp'>) => {
      setEvents((prev) =>
        [{ ...partial, id: makeId(), timestamp: new Date() }, ...prev].slice(0, MAX_EVENTS)
      );
    },
    [],
  );

  // ── WebSocket message handler ───────────────────────────────────────────
  const handleMessage = useCallback(
    (raw: string) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(raw);
      } catch {
        return;
      }

      const type = msg.type as string;

      switch (type) {
        // Welcome handshake — gives initial executor count
        case 'connected': {
          setExecutorCount((msg.connected_executors as number) ?? 0);
          break;
        }

        case 'executor_connected': {
          setExecutorCount((msg.connected_executors as number) ?? 0);
          const shortId = ((msg.executor_id as string) ?? '').slice(0, 8);
          pushEvent({
            type,
            message: `Executor connected (${shortId})`,
            textClass: 'text-gray-400',
            badgeClass: 'bg-gray-800 text-gray-500',
          });
          break;
        }

        case 'executor_disconnected': {
          setExecutorCount((msg.connected_executors as number) ?? 0);
          pushEvent({
            type,
            message: 'Executor disconnected',
            textClass: 'text-gray-400',
            badgeClass: 'bg-gray-800 text-gray-500',
          });
          break;
        }

        case 'task_queued': {
          const goal = (msg.goal as string) ?? '';
          const task_id = (msg.task_id as string) ?? '';
          setActiveTask({ task_id, goal, status: 'queued' });
          pushEvent({
            type,
            message: `Task queued: ${goal}`,
            textClass: 'text-blue-300',
            badgeClass: 'bg-blue-950 text-blue-400',
          });
          break;
        }

        case 'task_result': {
          const status = (msg.status as string) === 'completed' ? 'completed' : 'failed';
          const data   = (msg.data as Record<string, unknown>) ?? {};
          const goal   = (data.goal as string) ?? (msg.task_id as string) ?? '';
          const task_id = (msg.task_id as string) ?? '';

          setActiveTask((prev) =>
            prev ? { ...prev, status } : { task_id, goal, status }
          );

          if (status === 'completed') {
            pushEvent({
              type,
              message: `✓ Task completed: ${goal}`,
              textClass: 'text-green-300',
              badgeClass: 'bg-green-950 text-green-400',
            });
          } else {
            pushEvent({
              type,
              message: `✗ Task failed: ${goal}`,
              textClass: 'text-red-400',
              badgeClass: 'bg-red-950 text-red-400',
            });
          }
          break;
        }

        case 'screenshot': {
          pushEvent({
            type,
            message: 'Screenshot captured',
            textClass: 'text-slate-400',
            badgeClass: 'bg-slate-800 text-slate-500',
          });
          break;
        }

        default:
          break;
      }
    },
    [pushEvent],
  );

  // ── WebSocket connect / reconnect ───────────────────────────────────────
  const connect = useCallback(() => {
    // Don't stack connections
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsStatus('connected');
      if (reconnectRef.current) {
        clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
    };

    ws.onmessage = (ev) => handleMessage(ev.data as string);

    ws.onclose = () => {
      setWsStatus('reconnecting');
      reconnectRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
    };

    ws.onerror = () => {
      // onclose fires right after onerror, which triggers the reconnect
      ws.close();
    };
  }, [handleMessage]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // ── Derived values ──────────────────────────────────────────────────────
  const taskIsLive =
    activeTask?.status === 'queued' || activeTask?.status === 'running';

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 font-mono flex flex-col">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="border-b border-gray-800 px-6 py-4 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Phantom Dev
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">Autonomous Computer Operator</p>
        </div>

        <div className="flex items-center gap-4 flex-shrink-0">
          {/* Executor pill */}
          {executorCount > 0 ? (
            <span className="flex items-center gap-1.5 text-sm text-green-400">
              <span className="text-green-400 leading-none">●</span>
              {executorCount} executor{executorCount !== 1 ? 's' : ''} connected
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-sm text-red-400">
              <span className="leading-none">●</span>
              No executor
            </span>
          )}

          {/* WebSocket connection badge */}
          {wsStatus === 'connected' ? (
            <span className="text-xs px-2.5 py-1 rounded-full bg-green-950 text-green-400 border border-green-900">
              Connected
            </span>
          ) : (
            <span className="text-xs px-2.5 py-1 rounded-full bg-yellow-950 text-yellow-400 border border-yellow-900 animate-pulse">
              Reconnecting…
            </span>
          )}
        </div>
      </header>

      {/* ── Body ───────────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col gap-5 p-6 max-w-5xl w-full mx-auto">

        {/* ── Active Task Panel ─────────────────────────────────────────── */}
        <section className="rounded-xl border border-gray-800 bg-gray-900 p-5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-600 mb-4">
            Active Task
          </h2>

          {activeTask ? (
            <div className="flex items-start gap-4">
              {/* Animated indicator dot */}
              <div className="mt-1 flex-shrink-0">
                {taskIsLive ? (
                  <span className="relative flex h-3 w-3">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-60" />
                    <span className="relative inline-flex rounded-full h-3 w-3 bg-blue-500" />
                  </span>
                ) : activeTask.status === 'completed' ? (
                  <span className="inline-flex rounded-full h-3 w-3 bg-green-500" />
                ) : (
                  <span className="inline-flex rounded-full h-3 w-3 bg-red-500" />
                )}
              </div>

              {/* Goal text */}
              <p className="flex-1 min-w-0 text-white text-base leading-snug break-words">
                {activeTask.goal}
              </p>

              {/* Status badge */}
              <span
                className={`flex-shrink-0 text-xs font-semibold px-2.5 py-1 rounded-md ${STATUS_BADGE[activeTask.status]}`}
              >
                {activeTask.status}
              </span>
            </div>
          ) : (
            <p className="text-gray-700 text-sm">Waiting for task…</p>
          )}
        </section>

        {/* ── Activity Feed ─────────────────────────────────────────────── */}
        <section className="flex-1 flex flex-col rounded-xl border border-gray-800 bg-gray-900 overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-800 flex items-center justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-600">
              Activity Feed
            </h2>
            {events.length > 0 && (
              <span className="text-xs text-gray-700">{events.length} event{events.length !== 1 ? 's' : ''}</span>
            )}
          </div>

          <div className="overflow-y-auto flex-1 max-h-[32rem] px-5 py-3 space-y-2.5">
            {events.length === 0 ? (
              <p className="text-gray-700 text-sm pt-1">No events yet.</p>
            ) : (
              events.map((ev) => (
                <div
                  key={ev.id}
                  className="flex items-baseline gap-3 text-sm"
                >
                  {/* Timestamp */}
                  <span className="flex-shrink-0 text-gray-700 text-xs tabular-nums w-20">
                    {fmtTime(ev.timestamp)}
                  </span>

                  {/* Type badge */}
                  <span
                    className={`flex-shrink-0 text-xs px-1.5 py-0.5 rounded font-medium leading-tight ${ev.badgeClass}`}
                  >
                    {ev.type.replace(/_/g, '\u200b_')}
                  </span>

                  {/* Message */}
                  <span className={`${ev.textClass} break-words min-w-0`}>
                    {ev.message}
                  </span>
                </div>
              ))
            )}
            <div ref={feedBottomRef} />
          </div>
        </section>
      </div>
    </main>
  );
}
