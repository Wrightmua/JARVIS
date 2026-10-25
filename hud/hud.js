// JARVIS HUD: WebSocket to the brain, browser speech recognition for the ears, neural TTS for the voice.
const $ = (id) => document.getElementById(id);
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const WAKE = /\b(?:hey |ok |okay )?(?:jarvis|jervis|javis|jarvas)\b[\s,.!?]*(.*)$/i;
const YES = /\b(yes|yeah|yep|confirm|confirmed|do it|proceed|go ahead|affirmative|authori[sz]e)\b/i;
const NO = /\b(no|nope|cancel|stop|abort|negative|deny|don't)\b/i;
const LABELS = { idle: "ONLINE", listening: "LISTENING", thinking: "THINKING", working: "EXECUTING",
  speaking: "SPEAKING", awaiting: "AWAITING AUTHORISATION", offline: "OFFLINE" };

let ws, ready = false, busy = false, current = null, pendingConfirm = null, lastStatus = "";
let rec = null, recRunning = false, micOn = false, awaitingCmd = false, awaitTimer = null, oneShot = false;
let speaking = false, stopVoice = null;

// ---------- prefs ----------
function pref(key, fallback) { try { return localStorage.getItem("jarvis." + key) ?? fallback; } catch { return fallback; } }
function setPref(key, v) { try { localStorage.setItem("jarvis." + key, v); } catch {} }
$("mode").value = pref("mode", "wake");
$("voiceOut").value = pref("voiceOut", "neural");
$("mode").onchange = () => { setPref("mode", $("mode").value); placeholder(); stopRec(); startRec(); };
$("voiceOut").onchange = () => setPref("voiceOut", $("voiceOut").value);
function placeholder() {
  $("text").placeholder = { wake: "Type a command, or say “Jarvis…”", open: "Type, or just speak",
    push: "Type, or click the reactor and speak" }[$("mode").value];
}
placeholder();

// ---------- state ----------
function baseState() {
  if (!ready) return "offline";
  if (busy) return "thinking";
  if (awaitingCmd || oneShot) return "listening";
  return "idle";
}
function setState(s) { document.body.dataset.state = s; $("stateLabel").textContent = LABELS[s] || s.toUpperCase(); }

// ---------- transcript ----------
function addMsg(kind, text) {
  const el = document.createElement("div");
  el.className = "msg " + kind;
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = { user: "YOU", jarvis: "JARVIS", error: "SYSTEM" }[kind];
  const body = document.createElement("span");
  body.textContent = text;
  el.append(who, body);
  $("transcript").append(el);
  scrollDown();
  return body;
}
function scrollDown() { const t = $("transcript"); t.scrollTop = t.scrollHeight; }

function addActivity(name, detail) {
  const li = document.createElement("li");
  const t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  li.innerHTML = `<span class="t"></span> <span class="n"></span><pre></pre>`;
  li.querySelector(".t").textContent = t;
  li.querySelector(".n").textContent = name.toUpperCase();
  li.querySelector("pre").textContent = detail;
  const list = $("activity");
  list.prepend(li);
  while (list.children.length > 60) list.lastChild.remove();
}

// ---------- socket ----------
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => { $("linkDot").classList.add("on"); $("linkText").textContent = "LINKED"; };
  ws.onclose = () => {
    ready = false; busy = false;
    $("linkDot").classList.remove("on"); $("linkText").textContent = "RECONNECTING";
    setState("offline");
    setTimeout(connect, 2000);
  };
  ws.onmessage = (e) => handle(JSON.parse(e.data));
}

function handle(ev) {
  switch (ev.type) {
    case "status":
      ready = ev.ready;
      $("model").textContent = ev.model;
      if (!ev.ready && ev.detail !== lastStatus) addMsg("error", ev.detail);
      lastStatus = ev.detail || "";
      if (!busy && !speaking) setState(baseState());
      if (!ev.ready) setTimeout(() => ws.readyState === 1 && ws.send(JSON.stringify({ type: "status" })), 5000);
      break;
    case "state":
      if (ev.value === "idle") { busy = false; if (!speaking) setState(baseState()); }
      else { busy = true; if (!speaking) setState(ev.value); }
      break;
    case "token":
      if (!current) current = addMsg("jarvis", "");
      current.textContent += ev.text;
      scrollDown();
      break;
    case "tool":
      addActivity(ev.name, Object.keys(ev.args).length ? JSON.stringify(ev.args, null, 1) : "");
      break;
    case "tool_result": {
      const pre = $("activity").firstChild?.querySelector("pre");
      if (pre) pre.textContent += (pre.textContent ? "\n" : "") + "→ " + ev.summary;
      break;
    }
    case "confirm": showConfirm(ev); break;
    case "confirm_closed": if (pendingConfirm === ev.id) hideConfirm(); break;
    case "done":
      if (ev.text && !current) addMsg("jarvis", ev.text);
      current = null;
      if (ev.speech) speak(ev.speech);
      break;
    case "error":
      current = null;
      addMsg("error", ev.text);
      break;
  }
}

function send(text) {
  text = text.trim();
  if (!text) return;
  if (!ws || ws.readyState !== 1) { addMsg("error", "Not connected to the core."); return; }
  stopSpeaking();
  addMsg("user", text);
  current = null;
  busy = true;
  setState("thinking");
  ws.send(JSON.stringify({ type: "user", text }));
}

// ---------- confirmation ----------
function showConfirm(ev) {
  pendingConfirm = ev.id;
  $("confirmMsg").textContent = ev.message;
  $("confirm").classList.remove("hidden");
  speak("I need your authorisation for that.");
  startRec();
}
function hideConfirm() { pendingConfirm = null; $("confirm").classList.add("hidden"); }
function answerConfirm(ok) {
  if (!pendingConfirm) return;
  ws.send(JSON.stringify({ type: "confirm", id: pendingConfirm, ok }));
  addActivity(ok ? "authorised" : "denied", "");
  hideConfirm();
}
$("allowBtn").onclick = () => answerConfirm(true);
$("denyBtn").onclick = () => answerConfirm(false);

// ---------- ears ----------
function shouldListen() {
  return micOn && !speaking && ($("mode").value !== "push" || oneShot || !!pendingConfirm);
}
function ensureRec() {
  if (rec) return rec;
  rec = new SR();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = navigator.language || "en-US";
  rec.onstart = () => { recRunning = true; };
  rec.onend = () => { recRunning = false; if (shouldListen()) setTimeout(startRec, 250); };
  rec.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") {
      micOn = false; updateMic();
      addMsg("error", "Microphone access was blocked. Allow it in the address bar, then click MIC.");
    }
  };
  rec.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) heard(r[0].transcript.trim());
      else interim += r[0].transcript;
    }
    $("interim").textContent = interim;
  };
  return rec;
}
function startRec() {
  if (!SR || !shouldListen() || recRunning) return;
  try { ensureRec().start(); } catch {}
}
function stopRec() { if (rec && recRunning) { try { rec.abort(); } catch {} } }

function heard(t) {
  $("interim").textContent = "";
  if (!t) return;
  if (pendingConfirm) {
    if (NO.test(t)) answerConfirm(false);
    else if (YES.test(t)) answerConfirm(true);
    return;
  }
  if (busy && /^(stop|cancel|never mind|jarvis stop)[.!]?$/i.test(t)) {
    ws.send(JSON.stringify({ type: "stop" }));
    return;
  }
  const mode = $("mode").value;
  const wake = t.match(WAKE);
  if (wake && wake[1].trim().length <= 1 && mode !== "push") { oneShot = false; armWake(); return; }
  if (oneShot || awaitingCmd) {
    oneShot = false; awaitingCmd = false; clearTimeout(awaitTimer);
    if (mode === "push") stopRec();
    send(wake ? wake[1] || t : t);
    return;
  }
  if (mode === "open") { send(wake ? wake[1] || t : t); return; }
  if (mode === "wake" && wake) {
    if (wake[1].trim().length > 1) send(wake[1]);
    else armWake();
  }
}
function armWake() {
  awaitingCmd = true;
  chime();
  setState("listening");
  clearTimeout(awaitTimer);
  awaitTimer = setTimeout(() => { awaitingCmd = false; if (!busy && !speaking) setState(baseState()); }, 8000);
}

function updateMic() {
  $("micBtn").classList.toggle("on", micOn);
  $("micBtn").textContent = micOn ? "MIC ON" : "MIC OFF";
}
$("micBtn").onclick = () => {
  initAudio();
  if (!SR) { addMsg("error", "This browser has no speech recognition. Use Edge or Chrome."); return; }
  micOn = !micOn;
  updateMic();
  if (micOn) startRec(); else { stopRec(); oneShot = awaitingCmd = false; setState(baseState()); }
};

function talkNow() {
  initAudio();
  if (speaking) { stopSpeaking(); return; }
  if (!SR) { $("text").focus(); return; }
  if (!micOn) { micOn = true; updateMic(); }
  oneShot = true;
  chime();
  setState("listening");
  startRec();
}
$("reactor").onclick = talkNow;

// ---------- voice ----------
const audio = new Audio();
let actx = null, analyser = null;
function initAudio() {
  if (actx) { if (actx.state === "suspended") actx.resume(); return; }
  try {
    actx = new AudioContext();
    analyser = actx.createAnalyser();
    analyser.fftSize = 256;
    actx.createMediaElementSource(audio).connect(analyser);
    analyser.connect(actx.destination);
    pulse();
  } catch { actx = null; }
}
function pulse() {
  const data = new Uint8Array(analyser.frequencyBinCount);
  (function frame() {
    let p = 1;
    if (speaking) {
      analyser.getByteFrequencyData(data);
      const avg = data.reduce((a, b) => a + b, 0) / data.length;
      p = 1 + Math.min(avg / 255, 1) * 0.45;
    }
    document.documentElement.style.setProperty("--pulse", p.toFixed(3));
    requestAnimationFrame(frame);
  })();
}
function chime() {
  if (!actx) return;
  const o = actx.createOscillator(), g = actx.createGain();
  o.frequency.setValueAtTime(880, actx.currentTime);
  o.frequency.exponentialRampToValueAtTime(1320, actx.currentTime + 0.12);
  g.gain.setValueAtTime(0.08, actx.currentTime);
  g.gain.exponentialRampToValueAtTime(0.001, actx.currentTime + 0.25);
  o.connect(g).connect(actx.destination);
  o.start(); o.stop(actx.currentTime + 0.25);
}

function playBlob(blob) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const done = () => { URL.revokeObjectURL(url); resolve(true); };
    stopVoice = () => { audio.pause(); done(); };
    audio.onended = done;
    audio.onerror = () => { URL.revokeObjectURL(url); resolve(false); };
    audio.src = url;
    if (actx?.state === "suspended") actx.resume();
    audio.play().catch(() => { URL.revokeObjectURL(url); resolve(false); });
  });
}
function browserSpeak(text) {
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(text);
    const voices = speechSynthesis.getVoices();
    u.voice = voices.find((v) => /ryan|george|daniel/i.test(v.name) && /en-GB/i.test(v.lang))
      || voices.find((v) => /en-GB/i.test(v.lang)) || null;
    u.rate = 1.05;
    u.onend = u.onerror = () => resolve(true);
    stopVoice = () => { speechSynthesis.cancel(); resolve(true); };
    speechSynthesis.speak(u);
  });
}
async function speak(text) {
  const out = $("voiceOut").value;
  if (out === "mute" || !text) return;
  stopSpeaking();
  speaking = true;
  stopRec();
  setState("speaking");
  let ok = false;
  if (out === "neural") {
    try {
      const r = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }) });
      if (r.ok) ok = await playBlob(await r.blob());
    } catch {}
  }
  if (!ok && speaking) await browserSpeak(text);
  speaking = false;
  stopVoice = null;
  setState(busy ? "thinking" : baseState());
  startRec();
}
function stopSpeaking() {
  if (!speaking) return;
  speaking = false;
  if (stopVoice) stopVoice();
}

// ---------- input ----------
$("form").onsubmit = (e) => {
  e.preventDefault();
  initAudio();
  send($("text").value);
  $("text").value = "";
};
$("resetBtn").onclick = () => {
  ws?.send(JSON.stringify({ type: "reset" }));
  addActivity("memory", "Short-term conversation cleared (long-term facts kept).");
};
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    stopSpeaking();
    if (pendingConfirm) answerConfirm(false);
    else if (busy) ws?.send(JSON.stringify({ type: "stop" }));
  }
  if (e.code === "Space" && e.ctrlKey) { e.preventDefault(); talkNow(); }
});

// ---------- telemetry ----------
async function poll() {
  try {
    const s = await (await fetch("/api/stats")).json();
    const set = (key, pct, label) => {
      const g = document.querySelector(`.gauge[data-key="${key}"]`);
      const bar = g.querySelector("i");
      bar.style.width = (pct ?? 100) + "%";
      bar.classList.toggle("hot", pct > 85 || (key === "battery" && pct !== null && pct < 20));
      g.querySelector("b").textContent = label;
    };
    set("cpu", s.cpu, Math.round(s.cpu) + "%");
    set("ram", s.ram, Math.round(s.ram) + "%");
    set("disk", s.disk, Math.round(s.disk) + "%");
    set("battery", s.battery, s.battery === null ? "AC" : s.battery + "%" + (s.plugged ? "⚡" : ""));
    $("uptime").textContent = s.uptime_h + " H";
  } catch {}
}
function tick() {
  const d = new Date();
  $("time").textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  $("date").textContent = d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" }).toUpperCase();
}
setInterval(poll, 3000); poll();
setInterval(tick, 1000); tick();
speechSynthesis?.getVoices();
connect();
