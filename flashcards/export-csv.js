global.window = {};
require("./muscles.js");
require("./deck.js");

function esc(s) {
  return `"${String(s).replace(/"/g, '""')}"`;
}

const deck = window.getDeck("all");
const rows = [["Front", "Back", "Topic", "Kind"].join(",")];
for (const c of deck) {
  rows.push([esc(c.q), esc(c.a), esc(c.topic || ""), esc(c.kind || "")].join(","));
}

require("fs").writeFileSync("../anato_flashcards.csv", rows.join("\n") + "\n");

const byTopic = {};
for (const m of window.MUSCLES) byTopic[m.topic] = (byTopic[m.topic] || 0) + 1;
console.log("muscles:", window.MUSCLES.length, byTopic);
console.log("cards:", deck.length);
