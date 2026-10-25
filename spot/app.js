(() => {
  const data = window.SPOT_DATA;
  if (!data || !data.questions?.length) {
    document.body.innerHTML = "<p style='padding:2rem;color:#e8f4f1'>Geen quizdata. Run build_data.py eerst.</p>";
    return;
  }

  let mode = "mc"; // mc | reveal
  let groupBy = "category"; // category | photo
  let selectedRegions = new Set();
  let deck = [];
  let i = 0;
  let answered = false;
  let lastOk = null;
  let correctCount = 0;
  let attempted = 0;
  let currentChoices = [];

  const el = {
    regions: document.getElementById("regions"),
    groupings: document.getElementById("groupings"),
    modes: document.getElementById("modes"),
    subtitle: document.getElementById("subtitle"),
    tag: document.getElementById("tag"),
    score: document.getElementById("score"),
    count: document.getElementById("count"),
    progress: document.getElementById("progress"),
    photo: document.getElementById("photo"),
    pin: document.getElementById("pin"),
    prompt: document.getElementById("prompt"),
    choices: document.getElementById("choices"),
    feedback: document.getElementById("feedback"),
    prev: document.getElementById("prev"),
    next: document.getElementById("next"),
    shuffle: document.getElementById("shuffle"),
  };

  function norm(s) {
    return String(s || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, "")
      .trim();
  }

  function sameAnswer(a, b) {
    return norm(a) === norm(b);
  }

  function shuffleInPlace(arr) {
    for (let k = arr.length - 1; k > 0; k--) {
      const j = Math.floor(Math.random() * (k + 1));
      [arr[k], arr[j]] = [arr[j], arr[k]];
    }
    return arr;
  }

  function pickChoices(q) {
    const correct = q.answer;
    const pool = [...(q.siblings || []), ...(q.distractors || [])].filter(
      (a) => !sameAnswer(a, correct)
    );
    const seen = new Set();
    const uniq = [];
    for (const a of pool) {
      const k = norm(a);
      if (seen.has(k) || k.length < 3) continue;
      seen.add(k);
      uniq.push(a);
    }
    shuffleInPlace(uniq);
    const opts = [correct, ...uniq.slice(0, 3)];
    while (opts.length < 4 && data.answerPool?.length) {
      const extra = data.answerPool[Math.floor(Math.random() * data.answerPool.length)];
      if (extra && !opts.some((o) => sameAnswer(o, extra))) opts.push(extra);
      else break;
    }
    return shuffleInPlace(opts.slice(0, 4));
  }

  function filteredQuestions() {
    const all = data.questions;
    if (selectedRegions.size === 0) return [...all];
    return all.filter((q) => selectedRegions.has(q.region));
  }

  function rebuildDeck() {
    const pool = filteredQuestions();
    if (groupBy === "photo") {
      // Keep all labels of one photo together; shuffle photo order + within-photo
      const byPlate = new Map();
      for (const q of pool) {
        const key = q.plateId || q.image;
        if (!byPlate.has(key)) byPlate.set(key, []);
        byPlate.get(key).push(q);
      }
      const plates = [...byPlate.values()];
      shuffleInPlace(plates);
      deck = [];
      for (const labels of plates) {
        shuffleInPlace(labels);
        deck.push(...labels);
      }
    } else {
      deck = pool;
      shuffleInPlace(deck);
    }
    i = 0;
    answered = false;
    lastOk = null;
    correctCount = 0;
    attempted = 0;
    updateScore();
    render();
  }

  function current() {
    return deck[i] || null;
  }

  function regionSubtitle() {
    const modeLabel = groupBy === "photo" ? "Per foto" : "Per categorie";
    let regions;
    if (selectedRegions.size === 0) regions = "alle regio's";
    else if (selectedRegions.size <= 2) regions = [...selectedRegions].join(" + ");
    else regions = `${selectedRegions.size} regio's`;
    return `${modeLabel} · ${regions}`;
  }

  function photoProgress(q) {
    if (groupBy !== "photo" || !q) return null;
    const pid = q.plateId || q.image;
    let start = i;
    while (start > 0) {
      const prev = deck[start - 1];
      if ((prev.plateId || prev.image) !== pid) break;
      start -= 1;
    }
    let end = i;
    while (end < deck.length - 1) {
      const next = deck[end + 1];
      if ((next.plateId || next.image) !== pid) break;
      end += 1;
    }
    const local = i - start + 1;
    const total = end - start + 1;
    const plateIds = [];
    const seen = new Set();
    for (const item of deck) {
      const key = item.plateId || item.image;
      if (!seen.has(key)) {
        seen.add(key);
        plateIds.push(key);
      }
    }
    const photoIdx = plateIds.indexOf(pid) + 1;
    return { local, total, photoIdx, photoCount: plateIds.length };
  }

  function buildRegions() {
    el.regions.innerHTML = "";
    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = "topic" + (selectedRegions.size === 0 ? " active" : "");
    allBtn.textContent = "alles";
    allBtn.addEventListener("click", () => {
      selectedRegions.clear();
      rebuildDeck();
      buildRegions();
    });
    el.regions.appendChild(allBtn);

    for (const region of data.regions || []) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "topic" + (selectedRegions.has(region) ? " active" : "");
      btn.textContent = region;
      btn.addEventListener("click", () => {
        if (selectedRegions.has(region)) selectedRegions.delete(region);
        else selectedRegions.add(region);
        rebuildDeck();
        buildRegions();
      });
      el.regions.appendChild(btn);
    }
  }

  function setMode(next) {
    mode = next;
    [...el.modes.querySelectorAll(".topic")].forEach((b) => {
      b.classList.toggle("active", b.dataset.mode === mode);
    });
    answered = false;
    lastOk = null;
    currentChoices = [];
    render();
  }

  function setGroupBy(next) {
    if (next === groupBy) return;
    groupBy = next;
    [...el.groupings.querySelectorAll(".topic")].forEach((b) => {
      b.classList.toggle("active", b.dataset.group === groupBy);
    });
    rebuildDeck();
  }

  function updateScore() {
    el.score.textContent = attempted
      ? `${correctCount}/${attempted} juist`
      : "0 juist";
  }

  function showFeedback(kind, text) {
    el.feedback.hidden = false;
    el.feedback.className = "feedback " + kind;
    el.feedback.textContent = text;
  }

  function hideFeedback() {
    el.feedback.hidden = true;
    el.feedback.textContent = "";
  }

  function placePin(q, state) {
    if (mode === "reveal") {
      el.pin.classList.add("hidden");
      return;
    }
    el.pin.classList.remove("hidden", "ok", "bad");
    if (state === "ok") el.pin.classList.add("ok");
    if (state === "bad") el.pin.classList.add("bad");
    el.pin.style.left = `${q.x * 100}%`;
    el.pin.style.top = `${q.y * 100}%`;
  }

  const preloaded = new Set();
  let loadToken = 0;

  function preload(src) {
    if (!src || preloaded.has(src)) return;
    preloaded.add(src);
    const img = new Image();
    img.decoding = "async";
    img.src = src;
  }

  function prefetchAround() {
    if (!deck.length) return;
    for (const offset of [0, 1, 2, -1]) {
      const q = deck[(i + offset + deck.length) % deck.length];
      if (!q) continue;
      preload(q.image);
      preload(q.imageReveal);
    }
  }

  function applyPhoto(src, frame) {
    el.photo.src = src;
    el.photo.classList.add("ready");
    frame?.classList.remove("loading", "error");
    preloaded.add(src);
  }

  function setPhoto(src) {
    const frame = document.getElementById("frame");
    const token = ++loadToken;

    // Same image already shown — keep it
    if (el.photo.getAttribute("src") === src && el.photo.complete && el.photo.naturalWidth > 0) {
      frame?.classList.remove("loading", "error");
      el.photo.classList.add("ready");
      return;
    }

    // Keep previous photo visible; only show spinner if nothing is on screen yet
    const hasVisible = el.photo.classList.contains("ready") && el.photo.naturalWidth > 0;
    if (!hasVisible) frame?.classList.add("loading");
    frame?.classList.remove("error");

    const img = new Image();
    img.decoding = "async";
    img.onload = () => {
      if (token !== loadToken) return;
      applyPhoto(src, frame);
    };
    img.onerror = () => {
      if (token !== loadToken) return;
      // one retry (Google Drive / flaky local sync)
      setTimeout(() => {
        if (token !== loadToken) return;
        const retry = new Image();
        retry.onload = () => {
          if (token !== loadToken) return;
          applyPhoto(src, frame);
        };
        retry.onerror = () => {
          if (token !== loadToken) return;
          frame?.classList.remove("loading");
          frame?.classList.add("error");
        };
        retry.src = src + (src.includes("?") ? "&" : "?") + "r=" + Date.now();
      }, 400);
    };
    img.src = src;
  }

  function renderChoices(q) {
    if (!answered || !currentChoices.length) {
      currentChoices = pickChoices(q);
    }
    el.choices.innerHTML = "";
    currentChoices.forEach((opt, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice";
      btn.textContent = `${idx + 1}. ${opt}`;
      btn.disabled = answered;
      if (answered) {
        if (sameAnswer(opt, q.answer)) btn.classList.add("correct");
        else if (sameAnswer(opt, el.choices.dataset.picked || "")) btn.classList.add("wrong");
        else btn.classList.add("dim");
      }
      btn.addEventListener("click", () => submitAnswer(opt));
      el.choices.appendChild(btn);
    });
  }

  function render() {
    const q = current();
    el.subtitle.textContent = regionSubtitle();

    if (!q) {
      el.photo.removeAttribute("src");
      el.prompt.textContent = "Geen vragen in deze selectie.";
      el.choices.innerHTML = "";
      el.pin.classList.add("hidden");
      el.count.textContent = "0 / 0";
      el.progress.style.width = "0%";
      return;
    }

    el.tag.textContent = q.region;
    el.tag.title = q.topic;
    const pp = photoProgress(q);
    if (pp) {
      el.count.textContent = `foto ${pp.photoIdx}/${pp.photoCount} · ${pp.local}/${pp.total}`;
      el.progress.style.width = `${(pp.local / pp.total) * 100}%`;
    } else {
      el.count.textContent = `${i + 1} / ${deck.length}`;
      el.progress.style.width = `${((i + 1) / deck.length) * 100}%`;
    }

    const src = mode === "reveal" ? q.imageReveal : q.image;
    setPhoto(src);
    prefetchAround();

    placePin(q, answered ? (lastOk ? "ok" : "bad") : null);

    if (mode === "reveal") {
      el.prompt.textContent = q.topic;
      el.choices.innerHTML = "";
      showFeedback(
        "info",
        `Labels zichtbaar · op deze foto: ${(q.siblings || []).join(" · ") || q.answer}`
      );
      return;
    }

    el.prompt.textContent = "Welke structuur wijst dit pijltje aan?";
    if (!answered) {
      hideFeedback();
      el.pin.classList.remove("ok", "bad");
    }
    renderChoices(q);
  }

  function submitAnswer(raw) {
    const q = current();
    if (!q || answered || mode === "reveal") return;
    answered = true;
    attempted += 1;
    const ok = sameAnswer(raw, q.answer);
    lastOk = ok;
    if (ok) correctCount += 1;
    updateScore();
    placePin(q, ok ? "ok" : "bad");

    el.choices.dataset.picked = raw;
    [...el.choices.querySelectorAll(".choice")].forEach((btn) => {
      btn.disabled = true;
      const text = btn.textContent.replace(/^\d+\.\s*/, "");
      if (sameAnswer(text, q.answer)) btn.classList.add("correct");
      else if (sameAnswer(text, raw) && !ok) btn.classList.add("wrong");
      else btn.classList.add("dim");
    });

    showFeedback(
      ok ? "ok" : "bad",
      ok ? `Juist — ${q.answer}` : `Fout — juist is: ${q.answer}`
    );
  }

  function go(delta) {
    if (!deck.length) return;
    i = (i + delta + deck.length) % deck.length;
    answered = false;
    lastOk = null;
    currentChoices = [];
    delete el.choices.dataset.picked;
    hideFeedback();
    render();
  }

  el.modes.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-mode]");
    if (!btn) return;
    setMode(btn.dataset.mode);
  });

  el.groupings.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-group]");
    if (!btn) return;
    setGroupBy(btn.dataset.group);
  });

  el.prev.addEventListener("click", () => go(-1));
  el.next.addEventListener("click", () => go(1));
  el.shuffle.addEventListener("click", () => rebuildDeck());

  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea")) return;
    if (e.key === "ArrowLeft") go(-1);
    if (e.key === "ArrowRight") go(1);
    if (e.key === "s" || e.key === "S") rebuildDeck();
    if (e.key === "f" || e.key === "F") {
      setGroupBy(groupBy === "photo" ? "category" : "photo");
    }
    if (e.key === "r" || e.key === "R") {
      setMode(mode === "reveal" ? "mc" : "reveal");
    }
    if (mode === "mc" && !answered && /^[1-4]$/.test(e.key)) {
      const idx = Number(e.key) - 1;
      if (currentChoices[idx]) submitAnswer(currentChoices[idx]);
    }
  });

  buildRegions();
  rebuildDeck();
})();
