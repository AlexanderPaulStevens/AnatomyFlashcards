(() => {
  function groupBy(items, keyFn) {
    const map = new Map();
    for (const item of items) {
      const keys = [].concat(keyFn(item) || []).filter(Boolean);
      for (const key of keys) {
        if (!map.has(key)) map.set(key, []);
        const bucket = map.get(key);
        if (!bucket.includes(item)) bucket.push(item);
      }
    }
    return map;
  }

  function names(list) {
    return list.map((m) => m.name).join("; ");
  }

  function nervesOf(m) {
    return String(m.n)
      .split(/\s*\+\s*/)
      .map((s) => s.replace(/\s*\([^)]*\)\s*/g, "").trim())
      .filter(Boolean);
  }

  /** Normalize to array of topic ids. Empty / "all" → all muscles. */
  function resolveTopics(topics) {
    if (!topics || topics === "all") return null;
    const list = Array.isArray(topics) ? topics : [topics];
    const ids = list.filter((id) => id && id !== "all");
    return ids.length ? ids : null;
  }

  function buildCards(muscles, topicKey) {
    const cards = [];
    const selected = resolveTopics(topicKey);
    const topicSet = selected ? new Set(selected) : null;

    for (const m of muscles) {
      const tag = m.group || "spier";
      cards.push({ q: `${m.name} — Origo?`, a: m.o, tag, topic: m.topic, kind: "O" });
      cards.push({ q: `${m.name} — Insertie?`, a: m.i, tag, topic: m.topic, kind: "I" });
      cards.push({ q: `${m.name} — Functie?`, a: m.f, tag, topic: m.topic, kind: "F" });
      cards.push({ q: `${m.name} — Bezenuwing?`, a: m.n, tag, topic: m.topic, kind: "N" });
    }

    for (const [nerve, list] of groupBy(muscles, nervesOf)) {
      cards.push({
        q: `Welke spier(en) worden bezenuwd door: ${nerve}?`,
        a: names(list),
        tag: "zenuw→spier",
        topic: topicKey,
        kind: "Nrev",
      });
    }

    for (const [origo, list] of groupBy(muscles, (m) => m.o)) {
      cards.push({
        q: `Welke spier(en) hebben origo: ${origo}?`,
        a: names(list),
        tag: "O→spier",
        topic: topicKey,
        kind: "Orev",
      });
    }

    for (const [ins, list] of groupBy(muscles, (m) => m.i)) {
      cards.push({
        q: `Welke spier(en) insereren op: ${ins}?`,
        a: names(list),
        tag: "I→spier",
        topic: topicKey,
        kind: "Irev",
      });
    }

    const extras = (window.EXTRA_CARDS || []).filter((c) => {
      if (!topicSet) return true;
      return topicSet.has(c.topic);
    });
    for (const c of extras) {
      cards.push({ q: c.q, a: c.a, tag: c.tag, topic: c.topic, kind: "extra" });
    }

    return cards;
  }

  /** Card-kind filters: empty / "all" → alle aspecten. */
  const KIND_GROUPS = {
    O: new Set(["O", "Orev"]),
    I: new Set(["I", "Irev"]),
    F: new Set(["F"]),
    N: new Set(["N", "Nrev"]),
  };

  window.KINDS = [
    { id: "O", label: "Origo", short: "Origo" },
    { id: "I", label: "Insertie", short: "Insertie" },
    { id: "F", label: "Functie", short: "Functie" },
    { id: "N", label: "Bezenuwing", short: "Bezenuw." },
  ];

  function resolveKinds(kinds) {
    if (!kinds || kinds === "all") return null;
    const list = Array.isArray(kinds) ? kinds : [kinds];
    const ids = list.filter((id) => KIND_GROUPS[id]);
    return ids.length ? ids : null;
  }

  function cardMatchesKinds(card, kindIds) {
    if (!kindIds) return true;
    if (card.kind === "extra") return false;
    return kindIds.some((id) => KIND_GROUPS[id].has(card.kind));
  }

  window.getDeck = function getDeck(topics, kinds) {
    const all = window.MUSCLES || [];
    const selected = resolveTopics(topics);
    const muscles = selected
      ? all.filter((m) => selected.includes(m.topic))
      : all;
    const key = selected ? selected.slice().sort().join("+") : "all";
    const cards = buildCards(muscles, key);
    const kindIds = resolveKinds(kinds);
    return kindIds ? cards.filter((c) => cardMatchesKinds(c, kindIds)) : cards;
  };

  window.DECK = window.getDeck("all");
})();
