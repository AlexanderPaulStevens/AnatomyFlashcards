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

  function makeThumb(src, { badge, pin, alt }) {
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
    } else {
      const miss = document.createElement("p");
      miss.className = "missing";
      miss.textContent = "geen foto";
      thumb.appendChild(miss);
    }
    return thumb;
  }

  function renderGallery() {
    const row = currentRow();
    const withAny = row.items.filter((i) => i.spot?.image || i.commons?.image || i.image).length;
    els.pill.textContent = `${row.side} · ${row.label}`;
    els.count.textContent = `${row.items.length} structuren · ${withAny} met foto`;
    els.gallery.innerHTML = "";

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
      const commons = item.commons || null;
      const hasSpot = Boolean(spot?.image);
      const hasCommons = Boolean(commons?.image);

      // Legacy single-image items
      if (!spot && !commons && item.image) {
        const legacySpot = item.source === "spot" || item.pin;
        const thumb = makeThumb(item.image, {
          badge: legacySpot ? "cursus" : "commons",
          pin: legacySpot ? item.pin : null,
          alt: item.name,
        });
        thumb.tabIndex = 0;
        thumb.role = "button";
        thumb.addEventListener("click", () => openLightbox({
          name: item.name,
          image: item.image,
          pin: legacySpot ? item.pin : null,
          credit: item.credit,
          matchedAs: item.matchedAs,
          kind: legacySpot ? "cursus" : "commons",
        }));
        pair.appendChild(thumb);
      } else {
        if (hasSpot || hasCommons) {
          if (hasSpot) {
            const thumb = makeThumb(spot.image, {
              badge: "cursus",
              pin: spot.pin,
              alt: item.name,
            });
            thumb.tabIndex = 0;
            thumb.role = "button";
            thumb.title = "Cursusfoto — oranje pijl markeert de structuur";
            thumb.addEventListener("click", () => openLightbox({
              name: item.name,
              image: spot.image,
              pin: spot.pin,
              credit: spot.credit,
              matchedAs: spot.matchedAs,
              kind: "cursus",
            }));
            pair.appendChild(thumb);
          }
          if (hasCommons) {
            const thumb = makeThumb(commons.image, {
              badge: "commons",
              pin: null,
              alt: item.name,
            });
            thumb.tabIndex = 0;
            thumb.role = "button";
            thumb.title = commons.credit || "Wikimedia Commons";
            thumb.addEventListener("click", () => openLightbox({
              name: item.name,
              image: commons.image,
              pin: null,
              credit: commons.credit,
              matchedAs: commons.matchedAs,
              kind: "commons",
            }));
            pair.appendChild(thumb);
          }
        } else {
          const empty = makeThumb(null, { badge: "geen foto", pin: null, alt: item.name });
          pair.appendChild(empty);
          card.classList.add("no-img");
        }
      }

      card.appendChild(pair);

      if (spot?.matchedAs && spot.matchedAs.toLowerCase() !== item.name.toLowerCase()) {
        const sub = document.createElement("p");
        sub.className = "card-sub";
        sub.textContent = `cursuslabel: ${spot.matchedAs}`;
        card.appendChild(sub);
      }

      const credits = [];
      if (hasSpot) credits.push("cursus + markering");
      if (hasCommons) credits.push(commons.credit || "commons");
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
    if (view.kind === "cursus") caption += " · cursus";
    if (view.kind === "commons") caption += " · commons";
    if (view.matchedAs && view.kind === "cursus"
        && view.matchedAs.toLowerCase() !== view.name.toLowerCase()) {
      caption += `\nlabel: ${view.matchedAs}`;
    }
    if (view.credit) caption += `\n${view.credit}`;
    els.lbCaption.textContent = caption;
    els.lbImg.src = view.image;
    els.lbImg.alt = view.name;
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
