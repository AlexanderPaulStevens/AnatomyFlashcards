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

  function renderGallery() {
    const row = currentRow();
    els.pill.textContent = `${row.side} · ${row.label}`;
    els.count.textContent = `${row.items.length} structuren`;
    els.gallery.innerHTML = "";

    row.items.forEach((item, i) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "card";
      card.style.animationDelay = `${Math.min(i, 24) * 0.03}s`;

      const thumb = document.createElement("div");
      thumb.className = "thumb";

      if (item.source === "region") {
        const badge = document.createElement("span");
        badge.className = "badge";
        badge.textContent = "regio";
        thumb.appendChild(badge);
      }
      if (item.optional) {
        const opt = document.createElement("span");
        opt.className = "badge opt";
        opt.textContent = "opt";
        thumb.appendChild(opt);
      }

      if (item.image) {
        const img = document.createElement("img");
        img.alt = item.name;
        img.loading = "lazy";
        img.decoding = "async";
        img.addEventListener("load", () => img.classList.add("ready"));
        img.addEventListener("error", () => {
          img.remove();
          thumb.style.background = "#1a3339";
        });
        img.src = item.image;
        thumb.appendChild(img);

        if (item.pin && item.source === "spot") {
          const pin = document.createElement("span");
          pin.className = "pin";
          pin.style.left = `${item.pin.x * 100}%`;
          pin.style.top = `${item.pin.y * 100}%`;
          thumb.appendChild(pin);
        }
      }

      const name = document.createElement("p");
      name.className = "card-name";
      name.textContent = item.name;

      card.appendChild(thumb);
      card.appendChild(name);

      if (item.matchedAs && item.matchedAs.toLowerCase() !== item.name.toLowerCase()) {
        const sub = document.createElement("p");
        sub.className = "card-sub";
        sub.textContent = `≈ ${item.matchedAs}`;
        card.appendChild(sub);
      }

      card.addEventListener("click", () => openLightbox(item));
      els.gallery.appendChild(card);
    });
  }

  function openLightbox(item) {
    if (!item.image) return;
    els.lbCaption.textContent = item.name;
    els.lbImg.src = item.image;
    els.lbImg.alt = item.name;
    if (item.pin && item.source === "spot") {
      els.lbPin.classList.remove("hidden");
      els.lbPin.style.left = `${item.pin.x * 100}%`;
      els.lbPin.style.top = `${item.pin.y * 100}%`;
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
