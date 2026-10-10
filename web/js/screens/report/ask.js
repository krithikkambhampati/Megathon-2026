// "Ask about this home": the chat transcript and composer, in a side drawer.
import { html, useState, useEffect, useRef } from "../../lib.js";
import { useStore, ask, clearChat } from "../../store.js";
import { Drawer, AiAnswer, Notice, Button, Icon } from "../../ui.js";

const SUGGESTIONS = ["What if I only install solar?", "Why is my score low?", "What should I do first?", "We already have loft insulation"];

function Turn({ turn }) {
  if (turn.role === "user") return html`<div class="rb-msg rb-msg-user"><p>${turn.text}</p></div>`;
  if (turn.error) return html`<div class="rb-msg"><${Notice} tone="bad" title="That didn't work">${turn.text}<//></div>`;
  return html`<div class="rb-msg rb-msg-ai">
    <${AiAnswer} text=${turn.text} check=${turn.check} />
    ${turn.intent === "memory" && html`<p class="faint small">Nothing has been saved. Edit the home's details to change them.</p>`}
    ${turn.intent === "whatif" && turn.diff && html`<p class="faint small">This scenario is now shown under "Try a scenario".</p>`}
  </div>`;
}

export function AskDrawer({ open, prefill, onClose }) {
  const chat = useStore((s) => s.chat);
  const chatBusy = useStore((s) => s.chatBusy);
  const [draft, setDraft] = useState("");
  const inputRef = useRef(null);
  const endRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    setDraft(prefill || "");
    const t = setTimeout(() => inputRef.current?.focus(), 60);
    return () => clearTimeout(t);
  }, [open, prefill]);

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [open, chat.length, chatBusy]);

  const send = (text = draft) => {
    if (!text.trim() || chatBusy) return;
    ask(text);
    setDraft("");
  };
  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  };

  const footer = html`<form class="rb-composer" onSubmit=${(e) => { e.preventDefault(); send(); }}>
    <label for="rb-ask-input" class="sr-only">Your question</label>
    <textarea id="rb-ask-input" ref=${inputRef} class="input rb-composer-input" rows="2" value=${draft}
      placeholder="Ask about savings, your score, or a what-if" onInput=${(e) => setDraft(e.target.value)} onKeyDown=${onKey}></textarea>
    <button type="submit" class="btn btn-primary rb-send" disabled=${!draft.trim() || chatBusy} aria-label="Send">
      <${Icon} name="send" size=${16} /></button>
  </form>
  <p class="faint small rb-composer-hint">Enter to send, Shift+Enter for a new line. Answers use your report's figures, which are estimates.</p>`;

  return html`<${Drawer} open=${open} onClose=${onClose} title="Ask about this home" width=${480} footer=${footer}>
    <div class="rb-chat">
      ${chat.length === 0 ? html`<div class="rb-chat-empty stack gap-4">
        <p class="muted">Ask a question in your own words, or try one of these.</p>
        <div class="stack gap-2">${SUGGESTIONS.map((q) => html`<button key=${q} type="button" class="rb-suggest" disabled=${chatBusy}
          onClick=${() => send(q)}><${Icon} name="message" size=${15} /><span>${q}</span></button>`)}</div>
      </div>` : html`<div class="row between rb-chat-head"><span class="faint small">Conversation</span>
        <${Button} variant="ghost" size="sm" icon="refresh" disabled=${chatBusy} onClick=${clearChat}>Clear conversation<//></div>`}
      <div class="stack gap-4" role="log" aria-live="polite">
        ${chat.map((t, i) => html`<${Turn} key=${i} turn=${t} />`)}
        ${chatBusy && html`<div class="rb-typing" role="status" aria-label="Writing an answer"><span></span><span></span><span></span></div>`}
      </div>
      <div ref=${endRef}></div>
    </div>
  <//>`;
}
