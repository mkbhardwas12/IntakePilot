import { useCallback, useEffect, useRef, useState } from "react";
import { createSession, getSchema, getSession, sendTurn, uploadAttachment } from "../api";
import type { TurnAnswer, TurnStage } from "../api";
import type { ConfirmResponse, DecisionEvent, Question, RequirementObject, SlotSchemaEntry } from "../types";
import { useToast } from "../toast";
import { Chat } from "../components/Chat";
import type { ChatMessage } from "../components/Chat";
import { AnalystReadCard } from "../components/AnalystReadCard";
import { ShadowDraft } from "../components/ShadowDraft";
import { DecisionRail } from "../components/DecisionRail";
import { ConfirmView } from "../components/ConfirmView";
import { PostConfirm } from "../components/PostConfirm";

type View = "intake" | "confirm" | "done";

const SESSION_KEY = "intakepilot-session";
const REQUESTER_KEY = "intakepilot-requester";

const DEFAULT_REQUESTER = { name: "Demo User", dept: "Finance Ops", role: "Analyst" };

const VIRAL_DEMO_ASK =
  "our monthly vendor spend report takes 3 days to compile by hand from SAP and spreadsheets — finance needs it by month-end";

export function IntakePage() {
  const toast = useToast();

  const [requester, setRequester] = useState(() => {
    try {
      const raw = sessionStorage.getItem(REQUESTER_KEY);
      if (raw) return JSON.parse(raw) as typeof DEFAULT_REQUESTER;
    } catch { /* ignore */ }
    return DEFAULT_REQUESTER;
  });
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [schema, setSchema] = useState<Record<string, SlotSchemaEntry> | null>(null);
  const [schemaForType, setSchemaForType] = useState<string | null>(null);
  const [draft, setDraft] = useState<RequirementObject | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [answered, setAnswered] = useState<Record<string, string>>({});
  const [pendingAnswers, setPendingAnswers] = useState<TurnAnswer[]>([]);
  const [currentQuestions, setCurrentQuestions] = useState<Question[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [stage, setStage] = useState<TurnStage | null>(null);
  const [confirmUnlocked, setConfirmUnlocked] = useState(false);
  const [changedKeys, setChangedKeys] = useState<Set<string>>(new Set());
  const [decisions, setDecisions] = useState<DecisionEvent[]>([]);
  const [view, setView] = useState<View>("intake");
  const [confirmResult, setConfirmResult] = useState<ConfirmResponse | null>(null);
  const [demoPlaying, setDemoPlaying] = useState(false);
  const [attaching, setAttaching] = useState(false);

  const nextMsgId = useRef(1);
  const pulseTimers = useRef<Map<string, number>>(new Map());
  const initedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const pulseSlot = useCallback((key: string) => {
    setChangedKeys((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
    const timers = pulseTimers.current;
    const existing = timers.get(key);
    if (existing !== undefined) window.clearTimeout(existing);
    timers.set(
      key,
      window.setTimeout(() => {
        timers.delete(key);
        setChangedKeys((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }, 1600)
    );
  }, []);

  const loadSchema = useCallback((type = "default") => {
    getSchema(type)
      .then((s) => {
        setSchema(s.slots);
        setSchemaForType(type);
      })
      .catch((err: unknown) => {
        toast(`Could not load slot schema: ${err instanceof Error ? err.message : String(err)}`);
      });
  }, [toast]);

  const persistSession = useCallback((sid: string) => {
    try { sessionStorage.setItem(SESSION_KEY, sid); } catch { /* ignore */ }
  }, []);

  const clearPersisted = useCallback(() => {
    try { sessionStorage.removeItem(SESSION_KEY); } catch { /* ignore */ }
  }, []);

  const resetLocalState = useCallback(() => {
    setDraft(null);
    setSchemaForType(null);
    setMessages([]);
    setAnswered({});
    setPendingAnswers([]);
    setCurrentQuestions([]);
    setStreaming(false);
    setStage(null);
    setConfirmUnlocked(false);
    setChangedKeys(new Set());
    setDecisions([]);
    setView("intake");
    setConfirmResult(null);
    setDemoPlaying(false);
  }, []);

  const initSession = useCallback((overrideRequester?: typeof DEFAULT_REQUESTER) => {
    abortRef.current?.abort();
    abortRef.current = null;
    clearPersisted();
    setSessionId(null);
    resetLocalState();
    const who = overrideRequester ?? requester;
    createSession(who)
      .then((s) => {
        setSessionId(s.session_id);
        setDraft(s.draft);
        persistSession(s.session_id);
      })
      .catch((err: unknown) => {
        toast(`Could not start a session: ${err instanceof Error ? err.message : String(err)}`);
      });
    loadSchema("default");
  }, [requester, loadSchema, toast, clearPersisted, persistSession, resetLocalState]);

  useEffect(() => {
    if (initedRef.current) return;
    initedRef.current = true;
    const timers = pulseTimers.current;

    const restore = async () => {
      let saved: string | null = null;
      try { saved = sessionStorage.getItem(SESSION_KEY); } catch { /* ignore */ }
      if (saved) {
        try {
          const s = await getSession(saved);
          setSessionId(s.session_id);
          setDraft(s.draft);
          setCurrentQuestions(s.pending_questions);
          setConfirmUnlocked(
            ["awaiting_confirmation", "confirmed", "gated", "routed"].includes(s.draft.status)
          );
          if (s.turns?.length) {
            setMessages(
              s.turns.map((t) => ({
                id: nextMsgId.current++,
                role: t.role,
                text: t.text,
                questions: t.role === "assistant" && !t.attachment ? s.pending_questions : undefined,
                attachment: t.attachment,
              }))
            );
          }
          loadSchema(s.draft.request_type || "default");
          return;
        } catch {
          clearPersisted();
        }
      }
      initSession();
    };
    void restore();

    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      timers.clear();
      abortRef.current?.abort();
    };
  }, [initSession, loadSchema, clearPersisted]);

  useEffect(() => {
    if (!draft) return;
    const desired = draft.request_type || "default";
    if (desired !== schemaForType) loadSchema(desired);
  }, [draft?.request_type, schemaForType, loadSchema]);

  useEffect(() => {
    try { sessionStorage.setItem(REQUESTER_KEY, JSON.stringify(requester)); } catch { /* ignore */ }
  }, [requester]);

  const pushMessage = useCallback((msg: Omit<ChatMessage, "id">) => {
    setMessages((prev) => [...prev, { ...msg, id: nextMsgId.current++ }]);
  }, []);

  const sendMessage = useCallback(
    async (text: string, answers?: TurnAnswer[]) => {
      if (!sessionId || streaming) return;
      const batch = answers ?? (pendingAnswers.length > 0 ? pendingAnswers : undefined);
      setPendingAnswers([]);
      pushMessage({ role: "user", text });
      setStreaming(true);
      setStage("extracting");
      const ac = new AbortController();
      abortRef.current = ac;
      try {
        const result = await sendTurn(
          sessionId,
          { message: text, ...(batch && batch.length > 0 ? { answers: batch } : {}) },
          {
            onStatus: (s) => setStage(s),
            onSlot: (key, slot) => {
              setDraft((d) => (d ? { ...d, slots: { ...d.slots, [key]: slot } } : d));
              pulseSlot(key);
            },
            onDecision: (d) => setDecisions((prev) => [...prev, d]),
            onReadiness: (score) => {
              setDraft((d) => (d ? { ...d, readiness_score: score } : d));
            },
            onAnalyst: (read) => {
              setDraft((d) => (d ? { ...d, analyst: read } : d));
            }
          },
          ac.signal
        );
        setDraft((prev) => {
          if (prev) {
            for (const key of Object.keys(result.draft.slots)) {
              const before = prev.slots[key];
              const after = result.draft.slots[key];
              if (!before || JSON.stringify(before.value) !== JSON.stringify(after.value)) pulseSlot(key);
            }
          }
          return result.draft;
        });
        setConfirmUnlocked(result.confirm_unlocked);
        setCurrentQuestions(result.questions);
        const assistantText =
          result.questions.length > 0
            ? "I need a few details to finish the draft."
            : result.confirm_unlocked
              ? "The draft looks ready — review it in the panel and hit Confirm."
              : "Draft updated with what you told me.";
        pushMessage({
          role: "assistant",
          text: assistantText,
          questions: result.questions,
          degraded: result.degraded
        });
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === "AbortError") return;
        const detail = err instanceof Error ? err.message : String(err);
        pushMessage({ role: "assistant", text: `Turn failed: ${detail}`, error: true });
        toast(`Turn failed: ${detail}`);
      } finally {
        setStreaming(false);
        setStage(null);
        abortRef.current = null;
      }
    },
    [sessionId, streaming, pendingAnswers, pushMessage, pulseSlot, toast]
  );

  const answerQuestion = useCallback(
    (question: Question, value: string) => {
      setAnswered((prev) => ({ ...prev, [question.id]: value }));
      const next = [
        ...pendingAnswers.filter((a) => a.question_id !== question.id),
        { question_id: question.id, slot_key: question.slot_key, value }
      ];
      if (currentQuestions.length > 0 && next.length >= currentQuestions.length) {
        void sendMessage(next.map((a) => String(a.value)).join(" · "), next);
      } else {
        setPendingAnswers(next);
      }
    },
    [pendingAnswers, currentQuestions, sendMessage]
  );

  const attachFile = useCallback(
    async (file: File) => {
      if (!sessionId || attaching) return;
      setAttaching(true);
      pushMessage({ role: "user", text: `Attached ${file.name}` });
      try {
        const report = await uploadAttachment(sessionId, file);
        pushMessage({ role: "assistant", text: report.summary, attachment: report });
      } catch (err: unknown) {
        const detail = err instanceof Error ? err.message : String(err);
        pushMessage({ role: "assistant", text: `Attachment check failed: ${detail}`, error: true });
        toast(`Attachment check failed: ${detail}`);
      } finally {
        setAttaching(false);
      }
    },
    [sessionId, attaching, pushMessage, toast]
  );

  const sendPendingAnswers = useCallback(() => {
    if (pendingAnswers.length === 0) return;
    void sendMessage(pendingAnswers.map((a) => String(a.value)).join(" · "), pendingAnswers);
  }, [pendingAnswers, sendMessage]);

  const reviseSlot = useCallback(
    async (key: string, value: string) => {
      if (!sessionId || streaming) return;
      setStreaming(true);
      const ac = new AbortController();
      abortRef.current = ac;
      try {
        const result = await sendTurn(
          sessionId,
          { message: "", revisions: { [key]: value } },
          {
            onSlot: (k, slot) => {
              setDraft((d) => (d ? { ...d, slots: { ...d.slots, [k]: slot } } : d));
              pulseSlot(k);
            },
            onDecision: (d) => setDecisions((prev) => [...prev, d]),
            onReadiness: (score) => {
              setDraft((d) => (d ? { ...d, readiness_score: score } : d));
            }
          },
          ac.signal
        );
        setDraft(result.draft);
        setConfirmUnlocked(result.confirm_unlocked);
        const label = schema?.[key]?.label ?? key.replace(/_/g, " ");
        toast(`${label} updated.`);
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === "AbortError") return;
        toast(`Update failed: ${err instanceof Error ? err.message : String(err)}`);
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [sessionId, streaming, schema, pulseSlot, toast]
  );

  const handleConfirmed = useCallback((resp: ConfirmResponse) => {
    setConfirmResult(resp);
    setDraft(resp.draft);
    setView("done");
  }, []);

  const playDemo = useCallback(async () => {
    if (!sessionId || streaming || demoPlaying) return;
    setDemoPlaying(true);
    setDecisions([]);
    await sendMessage(VIRAL_DEMO_ASK);
  }, [sessionId, streaming, demoPlaying, sendMessage]);

  useEffect(() => {
    if (!demoPlaying || streaming) return;
    if (currentQuestions.length > 0 && pendingAnswers.length < currentQuestions.length) {
      const unanswered = currentQuestions.filter(
        (q) => !answered[q.id] && !pendingAnswers.find((a) => a.question_id === q.id)
      );
      if (unanswered.length === 0) return;
      const q = unanswered[0];
      const value = q.options?.[0] ?? "this quarter";
      const t = window.setTimeout(() => answerQuestion(q, value), 700);
      return () => window.clearTimeout(t);
    }
    if (demoPlaying && confirmUnlocked && view === "intake" && currentQuestions.length === 0) {
      const t = window.setTimeout(() => setView("confirm"), 900);
      return () => window.clearTimeout(t);
    }
  }, [demoPlaying, streaming, currentQuestions, pendingAnswers, answered, confirmUnlocked, view, answerQuestion]);

  if (view === "done" && confirmResult && sessionId) {
    return (
      <PostConfirm
        result={confirmResult}
        sessionId={sessionId}
        decisions={decisions}
        onRestart={() => initSession()}
      />
    );
  }

  const schemaLabels: Record<string, string> = {};
  if (schema) {
    for (const [k, v] of Object.entries(schema)) schemaLabels[k] = v.label;
  }

  const confirmDisabledReason =
    !draft
      ? "Starting session…"
      : !confirmUnlocked
        ? `Readiness ${draft.readiness_score} — keep answering or wait for the draft to unlock`
        : null;

  return (
    <div className="intake-layout">
      <Chat
        messages={messages}
        streaming={streaming}
        stage={stage}
        budget={draft?.question_budget ?? null}
        answered={answered}
        disabled={!sessionId || demoPlaying}
        pendingCount={pendingAnswers.length}
        onSend={(text) => void sendMessage(text)}
        onAnswer={answerQuestion}
        onSendAnswers={sendPendingAnswers}
        onAttach={(file) => void attachFile(file)}
        attaching={attaching}
        onPlayDemo={() => void playDemo()}
        demoPlaying={demoPlaying}
        requester={requester}
        onRequesterChange={setRequester}
      />
      <div className="draft-column">
        <ShadowDraft
          draft={draft}
          schema={schema}
          changedKeys={changedKeys}
          confirmUnlocked={confirmUnlocked}
          confirmDisabledReason={confirmDisabledReason}
          editable={!!draft && !streaming && ["draft", "questioning", "awaiting_confirmation"].includes(draft.status)}
          onRevise={(key, value) => void reviseSlot(key, value)}
          onConfirm={() => setView("confirm")}
        />
        {draft?.analyst && <AnalystReadCard read={draft.analyst} />}
        <DecisionRail decisions={decisions} schemaLabels={schemaLabels} />
      </div>
      {view === "confirm" && draft && sessionId && (
        <ConfirmView
          draft={draft}
          sessionId={sessionId}
          schema={schema}
          demoAutoConfirm={demoPlaying}
          onCancel={() => {
            setDemoPlaying(false);
            setView("intake");
          }}
          onConfirmed={(resp) => {
            setDemoPlaying(false);
            handleConfirmed(resp);
          }}
        />
      )}
    </div>
  );
}
