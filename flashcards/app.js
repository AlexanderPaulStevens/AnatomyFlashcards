(() => {
  /** Empty set = alle regio's / alle aspecten */
  let selected = new Set();
  let selectedKinds = new Set();
  let cards = window.getDeck("all");
  let i = 0;
  let flipped = false;

  const regionTopics = () =>
    (window.TOPICS || []).filter((t) => t.id !== "all");

  const kindOptions = () => window.KINDS || [];

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
    kinds: document.getElementById("kinds"),
    subtitle: document.getElementById("subtitle"),
  };

  const accentKinds = new Set(["diep", "zenuw→spier", "O→spier", "I→spier"]);

  function isAllRegions() {
    return selected.size === 0;
  }

  function isAllKinds() {
    return selectedKinds.size === 0;
  }

  function regionSubtitle() {
    if (isAllRegions()) return "Alle regio's";
    const labels = regionTopics()
      .filter((t) => selected.has(t.id))
      .map((t) => t.short);
    if (labels.length <= 2) return labels.join(" + ");
    return `${labels.length} regio's`;
  }

  function kindSubtitle() {
    if (isAllKinds()) return null;
    const labels = kindOptions()
      .filter((k) => selectedKinds.has(k.id))
      .map((k) => k.short);
    if (labels.length <= 2) return labels.join(" + ");
    return `${labels.length} aspecten`;
  }

  function subtitleText() {
    const kindPart = kindSubtitle();
    return kindPart ? `${regionSubtitle()} · ${kindPart}` : regionSubtitle();
  }

  function deckTopicsArg() {
    return isAllRegions() ? "all" : [...selected];
  }

  function deckKindsArg() {
    return isAllKinds() ? "all" : [...selectedKinds];
  }

  function rebuildDeck() {
    cards = window.getDeck(deckTopicsArg(), deckKindsArg());
    i = 0;
    el.subtitle.textContent = subtitleText();
    buildTopicBar();
    buildKindBar();
    render(true);
  }

  function makeChip(opts) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "topic" + (opts.active ? " active" : "");
    btn.textContent = opts.label;
    btn.title = opts.title;
    btn.setAttribute("aria-pressed", opts.active ? "true" : "false");
    btn.addEventListener("click", opts.onClick);
    return btn;
  }

  function buildTopicBar() {
    el.topics.innerHTML = "";

    el.topics.appendChild(
      makeChip({
        label: "Alles",
        title: "Alle regio's",
        active: isAllRegions(),
        onClick: () => {
          selected = new Set();
          rebuildDeck();
        },
      })
    );

    for (const t of regionTopics()) {
      const on = selected.has(t.id);
      el.topics.appendChild(
        makeChip({
          label: t.short,
          title: `${t.label} (meerdere selecteerbaar)`,
          active: on,
          onClick: () => toggleTopic(t.id),
        })
      );
    }
  }

  function buildKindBar() {
    if (!el.kinds) return;
    el.kinds.innerHTML = "";

    el.kinds.appendChild(
      makeChip({
        label: "Alles",
        title: "Alle aspecten (origo, insertie, functie, bezenuwing)",
        active: isAllKinds(),
        onClick: () => {
          selectedKinds = new Set();
          rebuildDeck();
        },
      })
    );

    for (const k of kindOptions()) {
      const on = selectedKinds.has(k.id);
      el.kinds.appendChild(
        makeChip({
          label: k.short,
          title: `${k.label} (meerdere selecteerbaar)`,
          active: on,
          onClick: () => toggleKind(k.id),
        })
      );
    }
  }

  function toggleTopic(id) {
    if (isAllRegions()) {
      selected = new Set([id]);
    } else if (selected.has(id)) {
      selected.delete(id);
    } else {
      selected.add(id);
    }
    rebuildDeck();
  }

  function toggleKind(id) {
    if (isAllKinds()) {
      selectedKinds = new Set([id]);
    } else if (selectedKinds.has(id)) {
      selectedKinds.delete(id);
    } else {
      selectedKinds.add(id);
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
  if (el.kinds) {
    el.kinds.setAttribute("aria-label", "Leeraspecten (meerdere selecteerbaar)");
  }
  buildTopicBar();
  buildKindBar();
  el.subtitle.textContent = subtitleText();
  render();
})();
