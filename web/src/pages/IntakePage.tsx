import { useCallback, useEffect, useRef, useState } from "react";
import { createSession, getSchema, sendTurn } from "../api";
import type { TurnAnswer, TurnStage } from "../api";
import type { ConfirmResponse, Question, RequirementObject, SlotSchemaEntry } from "../types";
import { useToast } from "../toast";
import { Chat } from "../components/Chat";
import type { ChatMessage } from "../components/Chat";
import { ShadowDraft } from "../components/ShadowDraft";
import { ConfirmView } from "../components/ConfirmView";
import { PostConfirm } from "../components/PostConfirm";

type View = "intake" | "confirm" | "done";

const REQUESTER = { name: "Demo User", dept: "Finance Ops", role: "Analyst" };

export function IntakePage() {
  const toast = useToast();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [schema, setSchema] = useState<Record<string, SlotSchemaEntry> | null>(null);
  const [draft, setDraft] = useState<RequirementObject | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [answered, setAnswered] = useState<Record<string, string>>({});
  const [streaming, setStreaming] = useState(false);
  const [stage, setStage] = useState<TurnStage | null>(null);
  const [confirmUnlocked, setConfirmUnlocked] = useState(false);
  const [changedKeys, setChangedKeys] = useState<Set<string>>(new Set());
  const [view, setView] = useState<View>("intake");
  const [confirmResult, setConfirmResult] = useState<ConfirmResponse | null>(null);

  const nextMsgId = useRef(1);
  const pulseTimers = useRef<Map<string, number>>(new Map());
  const initedRef = useRef(false); // StrictMode double-mount guard

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

  const initSession = useCallback(() => {
    setSessionId(null);
    setDraft(null);
    setMessages([]);
    setAnswered({});
    setStreaming(false);
    setStage(null);
    setConfirmUnlocked(false);
    setChangedKeys(new Set());
    setView("intake");
    setConfirmResult(null);
    createSession(REQUESTER)
      .then((s) => {
        setSessionId(s.session_id);
        setDraft(s.draft);
      })
      .catch((err: unknown) => {
        toast(`Could not start a session: ${err instanceof Error ? err.message : String(err)}`);
      });
  }, [toast]);

  useEffect(() => {
    // React 18 StrictMode double-invokes mount effects in dev; without the
    // guard every page load persisted an orphan backend session + requirement.
    if (!initedRef.current) {
      initedRef.current = true;
      initSession();
      getSchema()
        .then((s) => setSchema(s.slots))
        .catch((err: unknown) => {
          toast(`Could not load slot schema: ${err instanceof Error ? err.message : String(err)}`);
        });
    }
    const timers = pulseTimers.current;
    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      timers.clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pushMessage = useCallback((msg: Omit<ChatMessage, "id">) => {
    setMessages((prev) => [...prev, { ...msg, id: nextMsgId.current++ }]);
  }, []);

  const sendMessage = useCallback(
    async (text: string, answers?: TurnAnswer[]) => {
      if (!sessionId || streaming) return;
      pushMessage({ role: "user", text });
      setStreaming(true);
      setStage("extracting");
      try {
        const result = await sendTurn(
          sessionId,
          { message: text, ...(answers && answers.length > 0 ? { answers } : {}) },
          {
            onStatus: (s) => setStage(s),
            onSlot: (key, slot) => {
              setDraft((d) => (d ? { ...d, slots: { ...d.slots, [key]: slot } } : d));
              pulseSlot(key);
            },
            onReadiness: (score) => {
              setDraft((d) => (d ? { ...d, readiness_score: score } : d));
            }
          }
        );
        // Reconcile with the authoritative final state.
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
        toast(`Turn failed: ${err instanceof Error ? err.message : String(err)}`);
      } finally {
        setStreaming(false);
        setStage(null);
      }
    },
    [sessionId, streaming, pushMessage, pulseSlot, toast]
  );

  const answerQuestion = useCallback(
    (question: Question, value: string) => {
      setAnswered((prev) => ({ ...prev, [question.id]: value }));
      void sendMessage(value, [{ question_id: question.id, slot_key: question.slot_key, value }]);
    },
    [sendMessage]
  );

  const handleConfirmed = useCallback((resp: ConfirmResponse) => {
    setConfirmResult(resp);
    setDraft(resp.draft);
    setView("done");
  }, []);

  if (view === "done" && confirmResult && sessionId) {
    return <PostConfirm result={confirmResult} sessionId={sessionId} onRestart={initSession} />;
  }

  return (
    <div className="intake-layout">
      <Chat
        messages={messages}
        streaming={streaming}
        stage={stage}
        budget={draft?.question_budget ?? null}
        answered={answered}
        disabled={!sessionId}
        onSend={(text) => void sendMessage(text)}
        onAnswer={answerQuestion}
      />
      <ShadowDraft
        draft={draft}
        schema={schema}
        changedKeys={changedKeys}
        confirmUnlocked={confirmUnlocked}
        onConfirm={() => setView("confirm")}
      />
      {view === "confirm" && draft && sessionId && (
        <ConfirmView
          draft={draft}
          sessionId={sessionId}
          schema={schema}
          onCancel={() => setView("intake")}
          onConfirmed={handleConfirmed}
        />
      )}
    </div>
  );
}
