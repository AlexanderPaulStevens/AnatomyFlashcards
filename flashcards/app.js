(() => {
  /** Empty set = alle regio's */
  let selected = new Set();
  let cards = window.getDeck("all");
  let i = 0;
  let flipped = false;

  const regionTopics = () =>
    (window.TOPICS || []).filter((t) => t.id !== "all");

  const el = {
    card: document.getElementById("card"),
    deck: document.getElementById("deck"),
    front: document.getElementById("front"),
    back: document.getElementById("back"),
    count: document.getElementById("count"),
    tag: document.getElementById("tag"),
    progress: document.getElementById("progress"),
    prev: document.getElementById("prev"),
    next: document.getElementById("next"),
    shuffle: document.getElementById("shuffle"),
    topics: document.getElementById("topics"),
    subtitle: document.getElementById("subtitle"),
  };

  const accentKinds = new Set(["diep", "zenuw→spier", "O→spier", "I→spier"]);

  function isAll() {
    return selected.size === 0;
  }

  function subtitleText() {
    if (isAll()) return "Alle regio's";
    const labels = regionTopics()
      .filter((t) => selected.has(t.id))
      .map((t) => t.short);
    if (labels.length <= 2) return labels.join(" + ");
    return `${labels.length} regio's`;
  }

  function deckArg() {
    return isAll() ? "all" : [...selected];
  }

  function rebuildDeck() {
    cards = window.getDeck(deckArg());
    i = 0;
    el.subtitle.textContent = subtitleText();
    buildTopicBar();
    render(true);
  }

  function buildTopicBar() {
    el.topics.innerHTML = "";

    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = "topic" + (isAll() ? " active" : "");
    allBtn.textContent = "Alles";
    allBtn.title = "Alle regio's";
    allBtn.setAttribute("aria-pressed", isAll() ? "true" : "false");
    allBtn.addEventListener("click", () => {
      selected = new Set();
      rebuildDeck();
    });
    el.topics.appendChild(allBtn);

    for (const t of regionTopics()) {
      const on = selected.has(t.id);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "topic" + (on ? " active" : "");
      btn.textContent = t.short;
      btn.title = `${t.label} (meerdere selecteerbaar)`;
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.addEventListener("click", () => toggleTopic(t.id));
      el.topics.appendChild(btn);
    }
  }

  function toggleTopic(id) {
    if (isAll()) {
      selected = new Set([id]);
    } else if (selected.has(id)) {
      selected.delete(id);
      // geen selectie → terug naar alles
    } else {
      selected.add(id);
    }
    rebuildDeck();
  }

  function render(animate = false) {
    if (!cards.length) {
      el.front.textContent = "Geen kaarten";
      el.back.textContent = "—";
      el.count.textContent = "0 / 0";
      el.progress.style.width = "0%";
      return;
    }

    const c = cards[i];
    flipped = false;
    el.card.classList.remove("flipped");

    const paint = () => {
      el.front.textContent = c.q;
      el.back.textContent = c.a;
      el.count.textContent = `${i + 1} / ${cards.length}`;
      el.tag.textContent = c.tag;
      el.tag.classList.toggle("diep", accentKinds.has(c.tag) || c.tag === "diep");
      el.progress.style.width = `${((i + 1) / cards.length) * 100}%`;
    };

    if (!animate) {
      paint();
      return;
    }

    el.card.classList.add("swap");
    window.setTimeout(() => {
      paint();
      el.card.classList.remove("swap");
    }, 160);
  }

  function flip() {
    if (!cards.length) return;
    flipped = !flipped;
    el.card.classList.toggle("flipped", flipped);
  }

  function go(delta) {
    if (!cards.length) return;
    i = (i + delta + cards.length) % cards.length;
    render(true);
  }

  function shuffle() {
    for (let n = cards.length - 1; n > 0; n--) {
      const j = Math.floor(Math.random() * (n + 1));
      [cards[n], cards[j]] = [cards[j], cards[n]];
    }
    i = 0;
    render(true);
  }

  el.deck.addEventListener("click", flip);
  el.prev.addEventListener("click", (e) => {
    e.stopPropagation();
    go(-1);
  });
  el.next.addEventListener("click", (e) => {
    e.stopPropagation();
    go(1);
  });
  el.shuffle.addEventListener("click", (e) => {
    e.stopPropagation();
    shuffle();
  });

  window.addEventListener("keydown", (e) => {
    if (e.code === "Space") {
      e.preventDefault();
      flip();
    } else if (e.code === "ArrowRight") {
      go(1);
    } else if (e.code === "ArrowLeft") {
      go(-1);
    } else if (e.key === "s" || e.key === "S") {
      shuffle();
    }
  });

  el.topics.setAttribute("aria-label", "Regio's (meerdere selecteerbaar)");
  buildTopicBar();
  el.subtitle.textContent = subtitleText();
  render();
})();
