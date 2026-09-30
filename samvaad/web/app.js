// Samvaad interface: microphone capture, live results, Recall, Beacon.
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  const state = {
    langs: {},
    settings: { lang_a: "en", lang_b: "hi", label_a: "Doctor", label_b: "Patient", beacon_name: "Priya" },
    turn: "auto",
    listening: false,
    capRunning: false,
    mode: "conversation",
    holdingSide: null,
    ws: null,
    wsOpen: false,
    ctx: null,
    node: null,
    sink: null,
    mic: null,
    display: null,
    source: null,
    sending: false,
    speaking: false,
    items: new Map(),
    firstStatus: true,
  };

  // ---------------------------------------------------------------- helpers
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function fmt(sec) {
    const s = Math.max(0, Math.round(sec || 0));
    return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }
  function langName(code) { return (state.langs[code] || {}).name || code; }
  async function api(path, body) {
    const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const r = await fetch(path, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }
  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
  const ICONS = {
    pass: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="m4.8 8.2 2.1 2.1 4.3-4.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    hold: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 4.5v4.2M8 11v.4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
    confirm: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.8 15 14H1z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 6.2v3.3M8 11.6v.3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    none: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M5 8h6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  };
  function guardNode(item) {
    const g = item.guard;
    if (!g && !item.note) return null;
    const status = g ? g.status : "none";
    const n = el("div", "guard " + status);
    n.innerHTML = ICONS[status] || ICONS.none;
    n.appendChild(el("span", null, g ? g.message : item.note));
    return n;
  }

  // ---------------------------------------------------------------- status
  const banner = $("#banner");
  function showBanner(html, bad) {
    banner.innerHTML = html;
    banner.className = "banner" + (bad ? " bad" : "");
    banner.hidden = !html;
  }
  function setChip(id, cls, label, value) {
    const c = $(id);
    c.className = "chip-status " + cls;
    c.innerHTML = "";
    c.append(label + ": ");
    c.appendChild(el("b", null, value));
  }
  function updateNet() {
    if (navigator.onLine) setChip("#chip-net", "", "Network", "online");
    else setChip("#chip-net", "ok", "Network", "offline, still working");
  }
  window.addEventListener("online", updateNet);
  window.addEventListener("offline", updateNet);

  async function refreshStatus() {
    let s;
    try { s = await api("/api/status"); } catch (e) {
      setChip("#chip-asr", "bad", "Speech", "server stopped");
      showBanner("Samvaad's server is not running. Start it again with <code>run.ps1</code> (Windows) or <code>bash run.sh</code> (Mac, Linux).", true);
      return;
    }
    state.langs = s.languages;
    $("#version").textContent = "v" + s.version;
    const problems = [];
    if (s.platform) {
      $("#platform").textContent = `on ${s.platform.chip} · ${s.platform.os}`;
    }
    if (s.asr.ready) {
      setChip("#chip-asr", "ok", "Speech", `${s.asr.name} · ${s.asr.device}`);
      $("#asr-dev").textContent = s.asr.device;
      $("#stage-asr").classList.toggle("npu", s.asr.device === "NPU");
    } else if (s.asr.loading) {
      setChip("#chip-asr", "warn", "Speech", "loading model…");
    } else {
      setChip("#chip-asr", "bad", "Speech", "not loaded");
      const missing = /NO_SUCHFILE|No such file|not exist|FileNotFound|Load model|No speech engine is installed|ModuleNotFound/i.test(s.asr.error);
      problems.push(missing
        ? `The speech model is not installed yet. Run ${s.asr.setup || "the setup script"} once (see README).`
        : "The speech model did not load: <code>" + escapeHtml(s.asr.error) + "</code>. See README &gt; Troubleshooting.");
    }
    $("#llm-dev").textContent = s.llm.device || "local";
    $("#stage-llm").classList.toggle("npu", s.llm.device === "NPU");
    if (s.llm.reachable) {
      setChip("#chip-llm", "ok", "Translator", `${s.llm.label} · ${s.llm.provider}`);
    } else {
      setChip("#chip-llm", "bad", "Translator", "offline");
      problems.push(s.llm.hint || "The translator is not running. See README.");
    }
    showBanner(problems.join("<br>"), !s.asr.ready && !s.asr.loading);
    const b = s.beacon;
    $("#beacon-conn").textContent = "Arduino UNO Q · " + (b.connected ? "connected" : "not connected");
    if (state.firstStatus) {
      state.firstStatus = false;
      state.settings = s.settings;
      initSelects();
      $("#label-a").value = s.settings.label_a;
      $("#label-b").value = s.settings.label_b;
      $("#beacon-name").value = s.settings.beacon_name;
      $("#glossary").value = Object.entries(s.settings.glossary || {}).map(([k, v]) => `${k} = ${v}`).join("\n");
      idleBeacon();
      loadSession();
    }
  }
  function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  function fillLang(select, value, withAuto) {
    select.innerHTML = "";
    if (withAuto) { const o = el("option", null, "Detect automatically"); o.value = "auto"; select.appendChild(o); }
    Object.entries(state.langs).forEach(([code, l]) => {
      const o = el("option", null, code === "en" ? "English" : `${l.native} · ${l.name}`);
      o.value = code;
      select.appendChild(o);
    });
    select.value = value;
  }
  function initSelects() {
    fillLang($("#lang-a"), state.settings.lang_a);
    fillLang($("#lang-b"), state.settings.lang_b);
    fillLang($("#cap-src"), "auto", true);
    fillLang($("#cap-tgt"), state.settings.lang_b);
    fillLang($("#ans-lang"), "en");
  }

  // ---------------------------------------------------------------- pipeline + meter
  const stageEls = {};
  $$(".stage").forEach((s) => { stageEls[s.dataset.stage] = s; });
  function setStage(name) { Object.entries(stageEls).forEach(([k, n]) => n.classList.toggle("on", k === name)); }
  const meter = $("#meter"), meterBar = meter.querySelector("i");

  // ---------------------------------------------------------------- audio socket
  function wsConfig(extra) {
    if (state.mode === "captions") {
      return { mode: "captions", src: $("#cap-src").value, tgt: $("#cap-tgt").value, ptt: false, ...extra };
    }
    return {
      mode: "conversation", ptt: state.turn === "ptt",
      speaker: state.turn === "auto" ? "auto" : (state.holdingSide || "a"),
      lang_a: $("#lang-a").value, lang_b: $("#lang-b").value, ...extra,
    };
  }
  function wsSend(obj) {
    if (state.ws && state.wsOpen) state.ws.send(JSON.stringify(obj));
  }
  function connectAudio() {
    return new Promise((resolve) => {
      if (state.ws && state.wsOpen) { resolve(); return; }
      const ws = new WebSocket(`ws://${location.host}/ws/audio`);
      ws.binaryType = "arraybuffer";
      state.ws = ws;
      ws.onopen = () => { state.wsOpen = true; wsSend({ type: "start", ...wsConfig() }); resolve(); };
      ws.onmessage = (e) => onAudioMessage(JSON.parse(e.data));
      ws.onclose = () => {
        state.wsOpen = false;
        if (state.listening || state.capRunning) setTimeout(() => connectAudio(), 1000);
      };
    });
  }

  async function ensureAudio() {
    if (state.ctx) { if (state.ctx.state === "suspended") await state.ctx.resume(); return; }
    let ctx;
    try { ctx = new AudioContext({ sampleRate: 16000 }); } catch (e) { ctx = new AudioContext(); }
    await ctx.audioWorklet.addModule("/audio-worklet.js");
    const node = new AudioWorkletNode(ctx, "samvaad-capture");
    node.port.onmessage = (e) => { if (state.sending && state.wsOpen && !state.speaking) state.ws.send(e.data); };
    const sink = ctx.createGain();
    sink.gain.value = 0;
    node.connect(sink).connect(ctx.destination);
    state.ctx = ctx; state.node = node; state.sink = sink;
  }
  function attach(stream) {
    if (state.source) { try { state.source.disconnect(); } catch (e) {} }
    try {
      state.source = state.ctx.createMediaStreamSource(stream);
    } catch (e) {
      // Some browsers refuse mixing sample rates; fall back to the device rate.
      state.ctx.close(); state.ctx = null;
      throw e;
    }
    state.source.connect(state.node);
  }
  async function useMic() {
    await ensureAudio();
    if (!state.mic) {
      state.mic = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    }
    attach(state.mic);
  }
  async function useDisplay() {
    await ensureAudio();
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
    const audio = stream.getAudioTracks();
    if (!audio.length) {
      stream.getTracks().forEach((t) => t.stop());
      throw new Error('No audio was shared. Pick the window or tab again and tick "Share audio".');
    }
    stream.getVideoTracks().forEach((t) => t.stop());
    state.display = new MediaStream(audio);
    audio[0].addEventListener("ended", () => { if (state.capRunning) stopCaptions(); });
    attach(state.display);
  }

  function onAudioMessage(m) {
    switch (m.type) {
      case "level":
        meterBar.style.width = Math.min(100, m.v * 700) + "%";
        break;
      case "vad":
        meter.classList.toggle("speech", m.speech);
        if (m.speech) livePartial("…", 0);
        break;
      case "stage":
        setStage(m.stage);
        break;
      case "partial":
        livePartial(m.text, m.stable);
        break;
      case "final":
        livePartial("", 0);
        addItem(m.item, true);
        break;
      case "error":
        noteConv(m.message, true);
        break;
      case "ready":
        if (m.error) noteConv(m.error, true);
        break;
    }
  }

  // ---------------------------------------------------------------- speech output
  let voices = [];
  function loadVoices() { voices = window.speechSynthesis ? speechSynthesis.getVoices() : []; }
  if (window.speechSynthesis) { loadVoices(); speechSynthesis.onvoiceschanged = loadVoices; }
  function pickVoice(code) {
    const want = ((state.langs[code] || {}).voice || code).toLowerCase();
    return voices.find((v) => v.lang.toLowerCase() === want)
      || voices.find((v) => v.lang.toLowerCase().startsWith(code))
      || null;
  }
  const missingVoice = new Set();
  function speak(text, code) {
    return new Promise((resolve) => {
      if (!window.speechSynthesis || !text) { resolve(); return; }
      const v = pickVoice(code);
      if (!v && voices.length) {
        if (!missingVoice.has(code)) {
          missingVoice.add(code);
          noteConv(`No ${langName(code)} voice is installed in Windows, so ${langName(code)} is shown but not spoken. Add it in Settings > Time & language > Language & region (include the speech pack).`, true);
        }
        resolve();
        return;
      }
      const u = new SpeechSynthesisUtterance(text);
      u.lang = (state.langs[code] || {}).voice || code;
      if (v) u.voice = v;
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        setTimeout(() => { state.speaking = false; wsSend({ type: "resume" }); setStage(null); resolve(); }, 250);
      };
      u.onend = finish; u.onerror = finish;
      state.speaking = true;
      wsSend({ type: "pause" });
      setStage("speak");
      speechSynthesis.speak(u);
      setTimeout(finish, Math.min(15000, 2000 + text.length * 80));
    });
  }

  // ---------------------------------------------------------------- conversation
  function noteConv(text, bad) { $("#turn-hint").textContent = text; $("#turn-hint").className = "note" + (bad ? " bad" : ""); }
  const TURN_HINT = {
    auto: "Hands-free: put the laptop between you and just talk. Samvaad works out who is speaking from the language.",
    ptt: "Push to talk: hold your side's button while you speak, release when done. Best in noisy rooms.",
  };
  function clearEmpty(box) { const e = box.querySelector(".empty-state"); if (e) e.remove(); }

  let liveEl = null;
  function livePartial(text, stable) {
    if (state.mode === "captions") {
      const src = $("#cap-line-src");
      src.innerHTML = "";
      if (!text) return;
      src.append(text.slice(0, stable));
      src.appendChild(el("span", "unsettled", text.slice(stable)));
      return;
    }
    if (state.turn === "auto") {
      const strip = $("#live-strip"), p = strip.querySelector(".txt");
      strip.hidden = !text;
      p.innerHTML = "";
      if (text) { p.appendChild(el("span", "settled", text.slice(0, stable))); p.append(text.slice(stable)); }
      return;
    }
    if (!text) { if (liveEl) { liveEl.remove(); liveEl = null; } return; }
    const side = state.holdingSide || "a";
    const box = $("#msgs-" + side);
    if (!liveEl || liveEl.parentNode !== box) {
      if (liveEl) liveEl.remove();
      liveEl = el("div", "msg own partial");
      liveEl.appendChild(el("span", "meta", state.turn === "auto" ? "Hearing…" : "You're saying…"));
      liveEl.appendChild(el("p", "txt"));
      clearEmpty(box);
      box.appendChild(liveEl);
    }
    const p = liveEl.querySelector(".txt");
    p.innerHTML = "";
    p.appendChild(el("span", "settled", text.slice(0, stable)));
    p.append(text.slice(stable));
    box.scrollTop = box.scrollHeight;
  }

  function msgOwn(item) {
    const n = el("div", "msg own");
    const meta = item.timings && item.timings.asr_ms != null ? ` · heard in ${item.timings.asr_ms} ms` : "";
    n.appendChild(el("span", "meta", `${item.speaker_label} · ${fmt(item.t)}${meta}`));
    const p = el("p", "txt", item.text); p.lang = item.src; p.dir = "auto";
    n.appendChild(p);
    return n;
  }
  function msgIn(item) {
    const held = item.guard && item.guard.status === "hold";
    const n = el("div", "msg in" + (held ? " held" : ""));
    n.dataset.id = item.id;
    const mt = item.timings && item.timings.mt_ms != null ? ` · translated in ${item.timings.mt_ms} ms` : "";
    n.appendChild(el("span", "meta", `${item.speaker_label} · from ${langName(item.src)} · ${fmt(item.t)}${mt}`));
    const p = el("p", "txt", item.translation); p.lang = item.tgt; p.dir = "auto";
    n.appendChild(p);
    if (item.translation !== item.text) {
      const o = el("p", "orig", item.text); o.lang = item.src; o.dir = "auto";
      n.appendChild(o);
    }
    const g = guardNode(item);
    if (g) n.appendChild(g);
    const actions = el("div", "msg-actions");
    const again = el("button", "link", "Speak again"); again.type = "button";
    again.addEventListener("click", () => speak(item.translation, item.tgt));
    const plain = el("button", "link", "Plain words"); plain.type = "button";
    plain.addEventListener("click", async () => {
      plain.disabled = true; plain.textContent = "Rewriting…";
      try {
        const r = await api("/api/clarify", { id: item.id, lang: item.tgt });
        const c = el("p", "clar", r.text); c.lang = item.tgt; c.dir = "auto";
        n.insertBefore(c, actions);
        plain.remove();
      } catch (e) { plain.textContent = e.message; }
    });
    if (!held) actions.appendChild(again);
    actions.appendChild(plain);
    n.appendChild(actions);
    return n;
  }

  function addItem(item, live) {
    if (state.items.has(item.id)) return;
    state.items.set(item.id, item);
    renderTranscript();
    if (item.kind === "caption") { addCaption(item, live); return; }
    const other = item.speaker === "a" ? "b" : "a";
    const own = $("#msgs-" + item.speaker), inbox = $("#msgs-" + other);
    clearEmpty(own); clearEmpty(inbox);
    own.appendChild(msgOwn(item));
    const incoming = msgIn(item);
    inbox.appendChild(incoming);
    if (live) incoming.classList.add("flash");
    own.scrollTop = own.scrollHeight; inbox.scrollTop = inbox.scrollHeight;
    updateSpeed(item);
    const speakable = item.src !== item.tgt && !(item.guard && item.guard.status === "hold") && !item.note;
    if (live && $("#voice").checked && speakable) speak(item.translation, item.tgt);
  }

  $("#listen").addEventListener("click", async () => {
    if (state.listening) { stopListening(); return; }
    try {
      state.mode = "conversation";
      if (state.capRunning) stopCaptions();
      await useMic();
      await connectAudio();
      wsSend({ type: "config", ...wsConfig() });
      state.listening = true; state.sending = true;
      $("#listen").classList.add("live");
      $("#listen span").textContent = "Stop listening";
      noteConv("Listening. Speak naturally; pause briefly between turns.");
    } catch (e) {
      noteConv(micError(e), true);
    }
  });
  function stopListening() {
    state.listening = false; state.sending = false;
    wsSend({ type: "flush" });
    $("#listen").classList.remove("live");
    $("#listen span").textContent = "Start listening";
    noteConv(TURN_HINT[state.turn]);
  }
  function micError(e) {
    if (e && e.name === "NotAllowedError") return "Microphone access was blocked. Click the lock icon in the address bar, allow the microphone, and try again.";
    if (e && e.name === "NotFoundError") return "No microphone found. Plug one in or check Windows Settings > Privacy > Microphone.";
    return (e && e.message) || "The microphone could not start.";
  }

  $$("[data-turn]").forEach((b) => b.addEventListener("click", () => {
    state.turn = b.dataset.turn;
    $$("[data-turn]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    if (state.listening) stopListening();
    $("#listen").hidden = state.turn !== "auto";
    $$(".talk").forEach((t) => { t.hidden = state.turn !== "ptt"; });
    noteConv(TURN_HINT[state.turn]);
  }));

  $$(".talk").forEach((btn) => {
    const side = btn.dataset.side;
    const down = async (ev) => {
      ev.preventDefault();
      if (state.holdingSide) return;
      try {
        state.mode = "conversation";
        if (state.capRunning) stopCaptions();
        await useMic();
        await connectAudio();
        state.holdingSide = side;
        wsSend({ type: "config", ...wsConfig({ speaker: side, ptt: true }) });
        state.sending = true;
        btn.classList.add("holding"); btn.textContent = "Listening… release to translate";
        document.querySelector(`.pane[data-side="${side}"]`).classList.add("speaking");
      } catch (e) { noteConv(micError(e), true); }
    };
    const up = () => {
      if (state.holdingSide !== side) return;
      state.sending = false;
      wsSend({ type: "flush" }); // the server tags this utterance with the side set above
      btn.classList.remove("holding"); btn.textContent = "Hold to talk";
      document.querySelector(`.pane[data-side="${side}"]`).classList.remove("speaking");
      state.holdingSide = null;
    };
    btn.addEventListener("pointerdown", down);
    btn.addEventListener("pointerup", up);
    btn.addEventListener("pointerleave", up);
    btn.addEventListener("pointercancel", up);
    btn.addEventListener("keydown", (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) down(e); });
    btn.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") up(); });
  });

  $$(".typed").forEach((f) => f.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const side = f.dataset.side, input = f.querySelector("input");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    setStage("translate");
    try {
      const r = await api("/api/translate", { text, speaker: side, lang_a: $("#lang-a").value, lang_b: $("#lang-b").value });
      addItem(r.item, true);
    } catch (e) { noteConv(e.message, true); }
    setStage(null);
  }));

  const saveSettings = debounce((extra) => api("/api/settings", extra).catch(() => {}), 400);
  ["a", "b"].forEach((s) => {
    $("#label-" + s).addEventListener("input", (e) => saveSettings({ ["label_" + s]: e.target.value }));
    $("#lang-" + s).addEventListener("change", (e) => {
      saveSettings({ ["lang_" + s]: e.target.value });
      if (state.wsOpen) wsSend({ type: "config", ...wsConfig() });
    });
  });

  $("#new-session").addEventListener("click", async () => {
    await api("/api/session/reset", {});
    resetUi();
  });
  function resetUi() {
    state.items.clear();
    ["a", "b"].forEach((s) => { $("#msgs-" + s).innerHTML = ""; $("#msgs-" + s).appendChild(el("p", "empty-state", "New session. Start talking.")); });
    $("#cap-log").innerHTML = "";
    renderTranscript();
    $("#answer").innerHTML = "";
    $("#answer").appendChild(el("p", "note", "Ask anything about what was said."));
  }

  // ---------------------------------------------------------------- captions
  function addCaption(item, live) {
    $("#cap-line-src").textContent = item.text;
    const dst = $("#cap-line-dst");
    dst.textContent = item.translation; dst.lang = item.tgt;
    $("#cap-hint").hidden = true;
    const li = el("li");
    li.appendChild(el("span", "time", fmt(item.t)));
    const body = el("div", "body");
    const line = el("p", "line", item.translation); line.lang = item.tgt; line.dir = "auto";
    body.appendChild(line);
    if (item.translation !== item.text) { const o = el("p", "orig", item.text); o.dir = "auto"; body.appendChild(o); }
    const g = guardNode(item); if (g) body.appendChild(g);
    li.appendChild(body);
    $("#cap-log").insertBefore(li, $("#cap-log").firstChild);
    updateSpeed(item);
    if (live && $("#cap-voice").checked && item.src !== item.tgt) speak(item.translation, item.tgt);
  }
  $("#cap-start").addEventListener("click", async () => {
    if (state.capRunning) { stopCaptions(); return; }
    try {
      if (state.listening) stopListening();
      state.mode = "captions";
      if ($("#cap-source").value === "display") await useDisplay(); else await useMic();
      await connectAudio();
      wsSend({ type: "config", ...wsConfig() });
      state.capRunning = true; state.sending = true;
      $("#cap-start").classList.add("live");
      $("#cap-start span").textContent = "Stop captions";
      $("#cap-hint").textContent = "Listening…"; $("#cap-hint").hidden = false;
    } catch (e) {
      $("#cap-hint").textContent = micError(e); $("#cap-hint").hidden = false;
      state.mode = "conversation";
    }
  });
  function stopCaptions() {
    state.capRunning = false; state.sending = false;
    wsSend({ type: "flush" });
    if (state.display) { state.display.getTracks().forEach((t) => t.stop()); state.display = null; }
    $("#cap-start").classList.remove("live");
    $("#cap-start span").textContent = "Start captions";
    state.mode = "conversation";
  }
  ["#cap-src", "#cap-tgt"].forEach((id) => $(id).addEventListener("change", () => {
    if (state.capRunning) wsSend({ type: "config", ...wsConfig() });
  }));
  $("#cap-pop").addEventListener("click", async () => {
    if (!("documentPictureInPicture" in window)) {
      $("#cap-hint").textContent = "Pop out needs Microsoft Edge or Chrome (version 116 or later).";
      $("#cap-hint").hidden = false;
      return;
    }
    const bar = $("#capbar");
    const pip = await documentPictureInPicture.requestWindow({ width: 860, height: 190 });
    const link = pip.document.createElement("link");
    link.rel = "stylesheet"; link.href = location.origin + "/style.css";
    pip.document.head.appendChild(link);
    pip.document.body.style.margin = "0";
    pip.document.body.style.background = "#0B1426";
    pip.document.body.appendChild(bar);
    pip.addEventListener("pagehide", () => { $("#capbar-home").appendChild(bar); });
  });

  // ---------------------------------------------------------------- recall
  function renderTranscript() {
    const list = $("#transcript");
    list.innerHTML = "";
    const items = Array.from(state.items.values()).sort((a, b) => a.t - b.t);
    if (!items.length) { const li = el("li"); li.append(el("span"), el("span", "note", "Nothing said yet.")); list.appendChild(li); return; }
    items.forEach((it) => {
      const li = el("li"); li.id = "tr-" + it.id;
      li.appendChild(el("span", "time", fmt(it.t)));
      const body = el("div", "body");
      body.appendChild(el("span", "spk", `${it.speaker_label} · ${langName(it.src)}`));
      const t = el("p", "t", it.text); t.dir = "auto"; body.appendChild(t);
      if (it.translation && it.translation !== it.text) { const tr = el("p", "tr", it.translation); tr.dir = "auto"; body.appendChild(tr); }
      li.appendChild(body);
      list.appendChild(li);
    });
  }
  function highlight(id) {
    const li = document.getElementById("tr-" + id);
    if (!li) return;
    li.classList.add("hl");
    li.scrollIntoView({ block: "nearest", behavior: "smooth" });
    setTimeout(() => li.classList.remove("hl"), 2400);
  }
  function citeRow(ids) {
    const row = el("div", "cites");
    row.appendChild(el("span", null, "From"));
    ids.forEach((id) => {
      const it = state.items.get(id);
      if (!it) return;
      const b = el("button", "cite", `${fmt(it.t)} ${it.speaker_label}`); b.type = "button";
      b.addEventListener("click", () => highlight(id));
      row.appendChild(b);
    });
    return row;
  }
  $("#ask-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const q = $("#q").value.trim();
    if (!q) return;
    const box = $("#answer");
    box.innerHTML = ""; box.appendChild(el("p", "note", "Thinking…"));
    try {
      const r = await api("/api/ask", { question: q, lang: $("#ans-lang").value });
      box.innerHTML = "";
      if (r.answer) {
        const p = el("p", "a-text", r.answer); p.dir = "auto"; box.appendChild(p);
      } else {
        box.appendChild(el("p", "note", r.note || "Closest moments:"));
      }
      if (r.cite && r.cite.length) { box.appendChild(citeRow(r.cite)); r.cite.forEach(highlight); }
      if (r.unsupported && r.unsupported.length) {
        const g = el("div", "guard hold"); g.innerHTML = ICONS.hold;
        g.appendChild(el("span", null, `${r.unsupported.join(", ")} does not appear in the cited moments. Check before relying on it.`));
        box.appendChild(g);
      } else if (r.answer && r.cite && r.cite.length) {
        const g = el("div", "guard pass"); g.innerHTML = ICONS.pass;
        g.appendChild(el("span", null, "Every number in this answer appears in the cited moments."));
        box.appendChild(g);
      }
    } catch (e) { box.innerHTML = ""; box.appendChild(el("p", "note bad", e.message)); }
  });
  $("#summarize").addEventListener("click", async () => {
    const box = $("#answer");
    box.innerHTML = ""; box.appendChild(el("p", "note", "Summarising…"));
    try {
      const r = await api("/api/summary", { lang: $("#ans-lang").value });
      box.innerHTML = "";
      const p = el("p", "a-text", r.summary); p.dir = "auto"; box.appendChild(p);
      if (r.actions && r.actions.length) {
        box.appendChild(el("p", "note", "Action items"));
        const ul = el("ul");
        r.actions.forEach((a) => { const li = el("li", null, a); li.dir = "auto"; ul.appendChild(li); });
        box.appendChild(ul);
      }
    } catch (e) { box.innerHTML = ""; box.appendChild(el("p", "note bad", e.message)); }
  });
  $("#save").addEventListener("click", async () => {
    try { const r = await api("/api/session/save", {}); $("#save-note").textContent = "Saved to " + r.path; }
    catch (e) { $("#save-note").textContent = e.message; }
  });
  async function loadSession() {
    try {
      const r = await api("/api/session");
      r.items.forEach((it) => addItem(it, false));
    } catch (e) { /* first run: nothing to load */ }
  }

  // ---------------------------------------------------------------- speed
  let speedCount = 0;
  function updateSpeed(item) {
    const t = item.timings || {};
    $("#s-asr").textContent = t.asr_ms != null ? t.asr_ms : "–";
    $("#s-mt").textContent = t.mt_ms != null ? t.mt_ms : "–";
    $("#s-e2e").textContent = t.end_to_end_ms != null ? t.end_to_end_ms : "–";
    speedCount++;
    if (speedCount % 3 === 0) {
      api("/api/metrics").then((m) => {
        const parts = [];
        if (m.asr_ms.n) parts.push(`speech ${m.asr_ms.median} ms`);
        if (m.mt_ms.n) parts.push(`translate ${m.mt_ms.median} ms`);
        if (m.end_to_end_ms.n) parts.push(`end to end ${m.end_to_end_ms.median} ms`);
        if (parts.length) $("#s-median").textContent = "Session medians: " + parts.join(", ") + ".";
      }).catch(() => {});
    }
  }

  // ---------------------------------------------------------------- Beacon
  const device = $("#device");
  let beaconTimer = null;
  function idleBeacon() {
    device.className = "device";
    const n = $("#beacon-name").value.trim();
    $("#beacon-status").textContent = n ? `Listening for “${n}”` : "Listening for alarms";
    $("#beacon-sub").textContent = "Vibrates and flashes for person B";
  }
  function fireBeacon(ev) {
    clearTimeout(beaconTimer);
    device.className = "device";
    void device.offsetWidth;
    device.className = "device active " + (ev.kind === "name" ? "name" : ev.kind === "alarm" ? "alarm" : "test");
    $("#beacon-status").textContent = ev.title;
    $("#beacon-sub").textContent = ev.detail;
    const list = $("#events");
    if (list.querySelector(".none")) list.innerHTML = "";
    const li = el("li");
    li.appendChild(el("span", "mono", new Date(ev.time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })));
    li.appendChild(el("span", null, `${ev.title} · ${ev.detail}`));
    list.insertBefore(li, list.firstChild);
    while (list.children.length > 6) list.removeChild(list.lastChild);
    beaconTimer = setTimeout(idleBeacon, 3500);
  }
  $("#beacon-name").addEventListener("input", (e) => { idleBeacon(); saveSettings({ beacon_name: e.target.value }); });
  $("#beacon-test").addEventListener("click", () => api("/api/beacon/test", {}).catch(() => {}));

  function connectEvents() {
    const ws = new WebSocket(`ws://${location.host}/ws/events`);
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "beacon") fireBeacon(m.event);
      else if (m.type === "item") setTimeout(() => addItem(m.item, false), 300); // our own items arrive first via the audio socket
      else if (m.type === "reset") resetUi();
    };
    ws.onclose = () => setTimeout(connectEvents, 1500);
  }

  // ---------------------------------------------------------------- glossary
  $("#glossary-save").addEventListener("click", async () => {
    const glossary = {};
    $("#glossary").value.split("\n").forEach((line) => {
      const i = line.indexOf("=");
      if (i > 0) glossary[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    });
    try { await api("/api/settings", { glossary }); $("#glossary-note").textContent = `Saved ${Object.keys(glossary).length} term(s).`; }
    catch (e) { $("#glossary-note").textContent = e.message; }
  });

  // ---------------------------------------------------------------- tabs
  const TABS = { conv: ["#tab-conv", "#panel-conv"], cap: ["#tab-cap", "#panel-cap"], recall: ["#tab-recall", "#panel-recall"] };
  function selectTab(key) {
    Object.entries(TABS).forEach(([k, [t, p]]) => { $(t).setAttribute("aria-selected", String(k === key)); $(p).hidden = k !== key; });
  }
  Object.entries(TABS).forEach(([k, [t]]) => $(t).addEventListener("click", () => selectTab(k)));

  // ---------------------------------------------------------------- start
  updateNet();
  refreshStatus();
  setInterval(refreshStatus, 5000);
  connectEvents();
})();
