import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { TurnStage } from "../api";
import type { Budget, Question } from "../types";

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  questions?: Question[];
  degraded?: boolean;
}

const STAGE_LABELS: Record<TurnStage, string> = {
  extracting: "Extracting slots…",
  resolving_gaps: "Resolving gaps…",
  composing_questions: "Composing questions…",
  scoring: "Scoring readiness…"
};

const EXAMPLE_PROMPTS = [
  "our monthly vendor report takes 3 days to compile by hand",
  "we need a dashboard that shows open invoices by region",
  "onboarding a new supplier means re-typing the same data into 4 systems"
];

interface ChatProps {
  messages: ChatMessage[];
  streaming: boolean;
  stage: TurnStage | null;
  budget: Budget | null;
  answered: Record<string, string>;
  disabled: boolean;
  onSend: (text: string) => void;
  onAnswer: (question: Question, value: string) => void;
}

export function Chat({ messages, streaming, stage, budget, answered, disabled, onSend, onAnswer }: ChatProps) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
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
      <div className="chat-scroll" ref={scrollRef}>
        {messages.length === 0 && !streaming ? (
          <div className="chat-hero">
            <div className="chat-hero-glow" aria-hidden="true" />
            <h1>
              Describe what you need.
              <br />
              <span className="hero-accent">IntakePilot drafts the requirement.</span>
            </h1>
            <p className="hero-sub">Type in plain language — the agent extracts structure as you go.</p>
            <div className="hero-examples">
              {EXAMPLE_PROMPTS.map((p) => (
                <button key={p} className="example-chip" onClick={() => onSend(p)} disabled={disabled}>
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
                    <div className="bubble assistant-bubble">{m.text}</div>
                    {m.questions && m.questions.length > 0 && (
                      <div className="question-cards">
                        {m.questions.map((q) => (
                          <QuestionCard
                            key={q.id}
                            question={q}
                            selected={answered[q.id]}
                            // Only questions on the latest assistant turn stay interactive.
                            interactive={m.id === lastAssistantId && !streaming}
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
        <form className="chat-form" onSubmit={submit}>
          <input
            className="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={disabled ? "Starting session…" : "Describe what you need…"}
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
    <div className="budget-row" title={`${budget.spent} of ${budget.max} questions used`}>
      <span className="budget-label">
        {budget.spent} of {budget.max} questions used
      </span>
      <span className="budget-dots">
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
      <div className="question-text">{question.text}</div>
      <div className="question-because">because {question.because}</div>
      {question.options && question.options.length > 0 ? (
        <div className="option-chips">
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
