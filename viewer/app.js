(() => {
  const data = window.VIEWER_DATA;
  if (!data?.rows?.length) {
    document.getElementById("gallery").textContent = "Geen data geladen.";
    return;
  }

  const els = {
    sides: document.getElementById("sides"),
    tabs: document.getElementById("tabs"),
    gallery: document.getElementById("gallery"),
    pill: document.getElementById("pill"),
    count: document.getElementById("count"),
    lightbox: document.getElementById("lightbox"),
    lbImg: document.getElementById("lb-img"),
    lbPin: document.getElementById("lb-pin"),
    lbCaption: document.getElementById("lb-caption"),
    lbCallout: document.getElementById("lb-callout"),
  };

  let side = "Anterior";
  let rowId = data.rows.find((r) => r.side === side)?.id || data.rows[0].id;

  function rowsForSide() {
    return data.rows.filter((r) => r.side === side);
  }

  function currentRow() {
    return data.rows.find((r) => r.id === rowId) || rowsForSide()[0];
  }

  function renderTabs() {
    const rows = rowsForSide();
    if (!rows.some((r) => r.id === rowId)) rowId = rows[0].id;
    els.tabs.innerHTML = "";
    rows.forEach((row) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "topic" + (row.id === rowId ? " active" : "");
      btn.textContent = row.label.replace("lidmaat ", "");
      btn.title = `${row.side} · ${row.label}`;
      btn.addEventListener("click", () => {
        rowId = row.id;
        render();
      });
      els.tabs.appendChild(btn);
    });
  }

  function addPin(thumb, pin) {
    if (!pin) return;
    const mark = document.createElement("span");
    mark.className = "pin-arrow";
    mark.style.left = `${pin.x * 100}%`;
    mark.style.top = `${pin.y * 100}%`;
    mark.setAttribute("aria-hidden", "true");
    thumb.appendChild(mark);
  }

  function addCallout(thumb, text) {
    if (!text) return;
    const tag = document.createElement("p");
    tag.className = "img-callout";
    tag.textContent = text;
    thumb.appendChild(tag);
  }

  function makeThumb(src, { badge, pin, alt, callout }) {
    const thumb = document.createElement("div");
    thumb.className = "thumb";

    const b = document.createElement("span");
    b.className = "badge";
    b.textContent = badge;
    thumb.appendChild(b);

    if (src) {
      const img = document.createElement("img");
      img.alt = alt;
      img.loading = "lazy";
      img.decoding = "async";
      img.addEventListener("load", () => img.classList.add("ready"));
      img.addEventListener("error", () => {
        img.remove();
        thumb.classList.add("broken");
      });
      img.src = src;
      thumb.appendChild(img);
      addPin(thumb, pin);
      addCallout(thumb, callout || alt);
    } else {
      const miss = document.createElement("p");
      miss.className = "missing";
      miss.textContent = "geen foto";
      thumb.appendChild(miss);
    }
    return thumb;
  }

  function internetBadge(block) {
    if (!block) return "internet";
    if (block.provider === "bassett" || block.confidence === "bassett") {
      return block.legendNum ? `bassett #${block.legendNum}` : "bassett";
    }
    if (block.provider === "commons" || block.confidence === "commons") return "commons";
    if (block.provider === "gray" || block.confidence === "gray") return "gray";
    return "internet";
  }

  function bindThumb(thumb, view) {
    thumb.tabIndex = 0;
    thumb.setAttribute("role", "button");
    const open = () => openLightbox(view);
    thumb.addEventListener("click", open);
    thumb.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    });
  }

  function renderGallery() {
    const row = currentRow();
    const withAny = row.items.filter(
      (i) => i.spot?.image || i.internet?.image || i.commons?.image || i.image
    ).length;
    els.pill.textContent = `${row.side} · ${row.label}`;
    els.count.textContent = `${row.items.length} structuren · ${withAny} met foto`;
    els.gallery.innerHTML = "";

    const bl = row.bluelink || row.items.find((i) => i.bluelink)?.bluelink;
    if (bl?.url) {
      const atlas = document.createElement("a");
      atlas.className = "atlas-link";
      atlas.href = bl.url;
      atlas.target = "_blank";
      atlas.rel = "noopener noreferrer";
      atlas.textContent = `BlueLink atlas · ${bl.label || "regio"}`;
      atlas.title = (data.bluelinkMeta?.credit || "Michigan BlueLink") + " — educational use";
      els.gallery.appendChild(atlas);
    }

    row.items.forEach((item, i) => {
      const card = document.createElement("article");
      card.className = "card";
      card.style.animationDelay = `${Math.min(i, 24) * 0.03}s`;

      const head = document.createElement("div");
      head.className = "card-head";

      const name = document.createElement("p");
      name.className = "card-name";
      name.textContent = item.name;
      head.appendChild(name);

      if (item.optional) {
        const opt = document.createElement("span");
        opt.className = "badge opt inline";
        opt.textContent = "opt";
        head.appendChild(opt);
      }
      card.appendChild(head);

      const pair = document.createElement("div");
      pair.className = "pair";

      const spot = item.spot || null;
      const net = item.internet || item.commons || null;
      const hasSpot = Boolean(spot?.image);
      const hasNet = Boolean(net?.image);

      if (hasSpot || hasNet) {
        if (hasSpot) {
          const callout = spot.callout || item.name;
          const thumb = makeThumb(spot.image, {
            badge: "cursus",
            pin: spot.pin,
            alt: item.name,
            callout,
          });
          thumb.title = "Oranje pijl = deze structuur";
          bindThumb(thumb, {
            name: item.name,
            image: spot.image,
            pin: spot.pin,
            credit: spot.credit,
            matchedAs: spot.matchedAs,
            callout,
            kind: "cursus",
            sourceUrl: null,
          });
          pair.appendChild(thumb);
        }
        if (hasNet) {
          const badge = internetBadge(net);
          const callout = net.callout || item.name;
          const thumb = makeThumb(net.image, {
            badge,
            pin: null,
            alt: item.name,
            callout,
          });
          thumb.title = net.credit || badge;
          bindThumb(thumb, {
            name: item.name,
            image: net.image,
            pin: null,
            credit: net.credit,
            matchedAs: net.matchedAs,
            callout,
            kind: badge,
            sourceUrl: net.sourceUrl,
          });
          pair.appendChild(thumb);
        }
      } else {
        const empty = makeThumb(null, {
          badge: "geen foto",
          pin: null,
          alt: item.name,
          callout: null,
        });
        pair.appendChild(empty);
        card.classList.add("no-img");
      }

      card.appendChild(pair);

      if (spot?.matchedAs && spot.matchedAs.toLowerCase() !== item.name.toLowerCase()) {
        const sub = document.createElement("p");
        sub.className = "card-sub";
        sub.textContent = `cursuslabel: ${spot.matchedAs}`;
        card.appendChild(sub);
      }

      const credits = [];
      if (hasSpot) credits.push("cursus + pijl");
      if (hasNet) {
        credits.push(net.callout ? `gemarkeerd: ${net.callout}` : (net.credit || internetBadge(net)));
      }
      if (credits.length) {
        const cred = document.createElement("p");
        cred.className = "card-credit";
        cred.textContent = credits.join(" · ");
        card.appendChild(cred);
      }

      els.gallery.appendChild(card);
    });
  }

  function openLightbox(view) {
    if (!view?.image) return;
    let caption = view.name;
    if (view.kind) caption += ` · ${view.kind}`;
    if (view.callout && view.callout !== view.name) caption += `\n→ ${view.callout}`;
    if (view.matchedAs && view.kind === "cursus"
        && view.matchedAs.toLowerCase() !== view.name.toLowerCase()) {
      caption += `\nlabel: ${view.matchedAs}`;
    }
    if (view.credit) caption += `\n${view.credit}`;
    if (view.sourceUrl) caption += `\n${view.sourceUrl}`;
    els.lbCaption.textContent = caption;
    els.lbImg.src = view.image;
    els.lbImg.alt = view.name;
    if (els.lbCallout) {
      els.lbCallout.textContent = view.callout || view.name;
      els.lbCallout.hidden = false;
    }
    if (view.pin) {
      els.lbPin.classList.remove("hidden");
      els.lbPin.className = "pin-arrow lb-pin";
      els.lbPin.style.left = `${view.pin.x * 100}%`;
      els.lbPin.style.top = `${view.pin.y * 100}%`;
    } else {
      els.lbPin.classList.add("hidden");
    }
    els.lightbox.showModal();
  }

  function render() {
    renderTabs();
    renderGallery();
  }

  els.sides.addEventListener("click", (e) => {
    const btn = e.target.closest(".side");
    if (!btn) return;
    side = btn.dataset.side;
    els.sides.querySelectorAll(".side").forEach((b) => {
      b.classList.toggle("active", b === btn);
    });
    rowId = rowsForSide()[0].id;
    render();
  });

  els.lightbox.addEventListener("click", (e) => {
    if (e.target === els.lightbox) els.lightbox.close();
  });

  render();
})();
