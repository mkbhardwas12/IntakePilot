import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { TurnStage } from "../api";
import type { AttachmentReport, Budget, Question } from "../types";
import { AttachmentCard } from "./AttachmentCard";

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  questions?: Question[];
  degraded?: boolean;
  error?: boolean;
  attachment?: AttachmentReport;
}

const STAGE_LABELS: Record<TurnStage, string> = {
  extracting: "Extracting slots…",
  resolving_gaps: "Resolving gaps…",
  composing_questions: "Composing questions…",
  interpreting: "Analyst reading the ask…",
  scoring: "Scoring readiness…"
};

const EXAMPLE_PROMPTS = [
  "our monthly vendor report takes 3 days to compile by hand",
  "we need a dashboard that shows open invoices by region",
  "onboarding a new supplier means re-typing the same data into 4 systems"
];

interface RequesterInfo {
  name: string;
  dept: string;
  role: string;
}

interface ChatProps {
  messages: ChatMessage[];
  streaming: boolean;
  stage: TurnStage | null;
  budget: Budget | null;
  answered: Record<string, string>;
  disabled: boolean;
  pendingCount: number;
  onSend: (text: string) => void;
  onAnswer: (question: Question, value: string) => void;
  onSendAnswers: () => void;
  onAttach?: (file: File) => void;
  attaching?: boolean;
  onPlayDemo?: () => void;
  demoPlaying?: boolean;
  requester?: RequesterInfo;
  onRequesterChange?: (r: RequesterInfo) => void;
}

export function Chat({
  messages, streaming, stage, budget, answered, disabled, pendingCount,
  onSend, onAnswer, onSendAnswers, onAttach, attaching, onPlayDemo, demoPlaying,
  requester, onRequesterChange
}: ChatProps) {
  const [input, setInput] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const liveRef = useRef<HTMLDivElement>(null);
  const lastAssistantId = [...messages].reverse().find((m) => m.role === "assistant")?.id;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, streaming, stage]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || streaming || disabled) return;
    setInput("");
    onSend(text);
  };

  return (
    <section className="chat-pane">
      {requester && onRequesterChange && messages.length === 0 && (
        <div className="requester-bar">
          <label>
            Name
            <input
              value={requester.name}
              onChange={(e) => onRequesterChange({ ...requester, name: e.target.value })}
              disabled={disabled || demoPlaying}
            />
          </label>
          <label>
            Dept
            <input
              value={requester.dept}
              onChange={(e) => onRequesterChange({ ...requester, dept: e.target.value })}
              disabled={disabled || demoPlaying}
            />
          </label>
          <label>
            Role
            <input
              value={requester.role}
              onChange={(e) => onRequesterChange({ ...requester, role: e.target.value })}
              disabled={disabled || demoPlaying}
            />
          </label>
        </div>
      )}
      <div className="chat-scroll" ref={scrollRef}>
        <div className="sr-only" aria-live="polite" aria-atomic="true" ref={liveRef}>
          {streaming && stage ? STAGE_LABELS[stage] : ""}
          {!streaming && messages.length > 0 ? messages[messages.length - 1]?.text : ""}
        </div>
        {messages.length === 0 && !streaming ? (
          <div className="chat-hero">
            <div className="chat-hero-glow" aria-hidden="true" />
            <h1>
              Describe what you need.
              <br />
              <span className="hero-accent">Watch the X-ray draft it.</span>
            </h1>
            <p className="hero-sub">
              Plain language in — structured requirement out. The orchestrator shows every infer, retrieve, and ask.
            </p>
            {onPlayDemo && (
              <button
                type="button"
                className="play-demo-btn"
                onClick={onPlayDemo}
                disabled={disabled || demoPlaying}
              >
                {demoPlaying ? "Playing demo…" : "Play the 23-second demo"}
              </button>
            )}
            <div className="hero-examples">
              {EXAMPLE_PROMPTS.map((p) => (
                <button key={p} className="example-chip" onClick={() => onSend(p)} disabled={disabled || demoPlaying}>
                  {p}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="chat-messages">
            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="msg-row user">
                  <div className="bubble user-bubble">{m.text}</div>
                </div>
              ) : (
                <div key={m.id} className="msg-row assistant">
                  <div className="avatar" aria-hidden="true">
                    <span />
                  </div>
                  <div className="assistant-body">
                    {m.degraded && <span className="degraded-tag">degraded mode</span>}
                    <div className={`bubble assistant-bubble${m.error ? " error-bubble" : ""}`}>{m.text}</div>
                    {m.attachment && <AttachmentCard report={m.attachment} />}
                    {m.questions && m.questions.length > 0 && (
                      <div className="question-cards">
                        {m.questions.map((q) => (
                          <QuestionCard
                            key={q.id}
                            question={q}
                            selected={answered[q.id]}
                            interactive={m.id === lastAssistantId && !streaming && !demoPlaying}
                            onAnswer={onAnswer}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )
            )}
            {streaming && (
              <div className="msg-row assistant">
                <div className="avatar" aria-hidden="true">
                  <span />
                </div>
                <div className="thinking-line">
                  <span className="thinking-pulse" />
                  {stage ? STAGE_LABELS[stage] : "Thinking…"}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="chat-inputbar">
        {budget && <BudgetDots budget={budget} />}
        {pendingCount > 0 && !streaming && (
          <div className="pending-answers-row">
            <span>
              {pendingCount} answer{pendingCount === 1 ? "" : "s"} ready — answer the rest, or
            </span>
            <button type="button" className="send-answers-btn" onClick={onSendAnswers}>
              Send now
            </button>
          </div>
        )}
        <form className="chat-form" onSubmit={submit}>
          {onAttach && (
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".xlsx"
                className="attach-input"
                aria-label="Attach a spreadsheet"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onAttach(f);
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                className="attach-btn"
                title="Attach a spreadsheet (.xlsx) — checked instantly"
                aria-label="Attach a spreadsheet"
                disabled={disabled || streaming || attaching}
                onClick={() => fileRef.current?.click()}
              >
                {attaching ? (
                  <span className="attach-spinner" aria-hidden="true" />
                ) : (
                  <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
                    <path
                      d="M10.5 4.5 5.7 9.3a1.6 1.6 0 1 0 2.3 2.3l4.8-4.8a3.2 3.2 0 1 0-4.6-4.6L3.4 7"
                      fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"
                    />
                  </svg>
                )}
              </button>
            </>
          )}
          <input
            className="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={disabled ? "Starting session…" : pendingCount > 0 ? "Add detail — your answers go with it…" : "Describe what you need…"}
            disabled={disabled || streaming}
            aria-label="Message"
          />
          <button type="submit" className="send-btn" disabled={disabled || streaming || input.trim() === ""}>
            <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
              <path d="M2 8 L14 2 L10.5 8 L14 14 Z" fill="currentColor" />
            </svg>
            Send
          </button>
        </form>
      </div>
    </section>
  );
}

function BudgetDots({ budget }: { budget: Budget }) {
  const dots = Array.from({ length: budget.max }, (_, i) => i < budget.spent);
  return (
    <div
      className="budget-row"
      title={`${budget.spent} of ${budget.max} questions used`}
      aria-label={`${budget.spent} of ${budget.max} questions used`}
    >
      <span className="budget-label">
        {budget.spent} of {budget.max} questions used
      </span>
      <span className="budget-dots" aria-hidden="true">
        {dots.map((filled, i) => (
          <span key={i} className={filled ? "budget-dot filled" : "budget-dot"} />
        ))}
      </span>
    </div>
  );
}

function QuestionCard({
  question,
  selected,
  interactive,
  onAnswer
}: {
  question: Question;
  selected: string | undefined;
  interactive: boolean;
  onAnswer: (question: Question, value: string) => void;
}) {
  const [freeText, setFreeText] = useState("");
  const answeredAlready = selected !== undefined;

  return (
    <div className={answeredAlready ? "question-card answered" : "question-card"}>
      <div className="question-text" id={`q-${question.id}`}>{question.text}</div>
      <div className="question-because">Why we ask: {question.because}</div>
      {question.options && question.options.length > 0 ? (
        <div className="option-chips" role="group" aria-labelledby={`q-${question.id}`}>
          {question.options.map((opt) => (
            <button
              key={opt}
              className={selected === opt ? "option-chip selected" : "option-chip"}
              disabled={!interactive || answeredAlready}
              onClick={() => onAnswer(question, opt)}
            >
              {opt}
            </button>
          ))}
        </div>
      ) : (
        !answeredAlready &&
        interactive && (
          <form
            className="question-freetext"
            onSubmit={(e) => {
              e.preventDefault();
              const v = freeText.trim();
              if (v) onAnswer(question, v);
            }}
          >
            <input
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              placeholder="Type an answer…"
              aria-label={question.text}
            />
            <button type="submit" disabled={freeText.trim() === ""}>
              Answer
            </button>
          </form>
        )
      )}
      {answeredAlready && !question.options?.includes(selected) && (
        <div className="question-answered-note">Answered: {selected}</div>
      )}
    </div>
  );
}
