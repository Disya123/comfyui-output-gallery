// Output Gallery SPA. Vanilla ES module, no build step.
// State is a single mutable object; render functions read it and patch the DOM.

const API = "/api/gallery";

const state = {
    items: [],
    total: 0,
    page: 0,
    limit: 48,
    loading: false,
    done: false,
    filters: { query: "", tag: "", favorite: false, sort: "date" },
    currentImage: null,
    tags: [],
};

// --------------------------------------------------------------------------- //
// Bootstrap
// --------------------------------------------------------------------------- //

const el = (id) => document.getElementById(id);
const grid = el("grid");
const sentinel = el("sentinel");
const empty = el("empty");
const search = el("search");
const sortSel = el("sort");
const favOnly = el("favorite-only");
const reindexBtn = el("reindex");
const statsEl = el("stats");
const tagbar = el("tagbar");
const tagFilter = el("tag-filter");
const tagFilterChip = el("tag-filter__chip");
const tagFilterClear = el("tag-filter__clear");

const modal = el("modal");
const modalImg = el("modal-img");
const modalName = el("modal-name");
const modalMeta = el("modal-meta");
const modalPositive = el("modal-positive");
const modalNegative = el("modal-negative");
const negativeBlock = el("negative-block");
const modalRaw = el("modal-raw");
const modalTags = el("modal-tags");
const modalFavorite = el("modal-favorite");
const tagForm = el("tag-form");
const tagInput = el("tag-input");
const gridSizeSlider = el("grid-size");
const modalZoomBtn = el("modal-zoom-btn");
const modalMediaContainer = el("modal-media-container");

let searchTimer = null;

function init() {
    search.addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            state.filters.query = search.value.trim();
            resetAndLoad();
        }, 250);
    });
    sortSel.addEventListener("change", () => {
        state.filters.sort = sortSel.value;
        resetAndLoad();
    });
    favOnly.addEventListener("change", () => {
        state.filters.favorite = favOnly.checked;
        resetAndLoad();
    });
    reindexBtn.addEventListener("click", onReindex);
    tagFilterClear.addEventListener("click", () => {
        state.filters.tag = "";
        tagFilter.hidden = true;
        resetAndLoad();
    });

    // Modal close handlers.
    modal.querySelectorAll("[data-close]").forEach((n) =>
        n.addEventListener("click", closeModal)
    );
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeModal();
    });

    // Zoom handlers
    if (modalZoomBtn) {
        const toggleZoom = () => {
            modalMediaContainer.classList.toggle("zoomed");
        };
        modalZoomBtn.addEventListener("click", toggleZoom);
        modalImg.addEventListener("click", toggleZoom);
    }

    // Grid size handler
    if (gridSizeSlider) {
        const savedSize = localStorage.getItem("ogallery-grid-size");
        if (savedSize) {
            gridSizeSlider.value = savedSize;
            document.documentElement.style.setProperty('--grid-size', savedSize + 'px');
        }
        gridSizeSlider.addEventListener("input", () => {
            document.documentElement.style.setProperty('--grid-size', gridSizeSlider.value + 'px');
            localStorage.setItem("ogallery-grid-size", gridSizeSlider.value);
        });
    }

    // Copy buttons.
    document.querySelectorAll(".copy").forEach((btn) => {
        btn.addEventListener("click", () => {
            const target = el(btn.dataset.copyTarget);
            if (target) copyText(target.textContent, btn);
        });
    });

    // Tag form.
    tagForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const tag = tagInput.value.trim();
        if (!tag || !state.currentImage) return;
        api("/tag", { method: "POST", body: { name: state.currentImage.filename, tag } })
            .then(() => {
                tagInput.value = "";
                loadTags();
                return api("/image?name=" + encodeURIComponent(state.currentImage.filename));
            })
            .then((r) => r.json())
            .then((r) => {
                if (r.success) {
                    state.currentImage = r.image;
                    renderModalTags();
                }
            })
            .catch(console.warn);
    });

    modalFavorite.addEventListener("click", () => {
        if (!state.currentImage) return;
        const next = !state.currentImage.favorite;
        api("/favorite", {
            method: "POST",
            body: { name: state.currentImage.filename, favorite: next },
        })
            .then(() => {
                state.currentImage.favorite = next;
                updateFavoriteUI();
                // Reflect in the grid.
                const card = grid.querySelector(`[data-name="${cssEscape(state.currentImage.filename)}"] .card__fav`);
                if (card) card.textContent = next ? "★" : "";
            })
            .catch(console.warn);
    });

    // Infinite scroll.
    const io = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting) loadPage();
    }, { rootMargin: "400px" });
    io.observe(sentinel);

    loadTags();
    resetAndLoad();
    refreshStats();
}

// --------------------------------------------------------------------------- //
// Data loading
// --------------------------------------------------------------------------- //

function resetAndLoad() {
    state.items = [];
    state.page = 0;
    state.done = false;
    grid.innerHTML = "";
    empty.hidden = true;
    loadPage();
}

function loadPage() {
    if (state.loading || state.done) return;
    state.loading = true;
    state.page += 1;
    const f = state.filters;
    const params = new URLSearchParams({
        page: String(state.page),
        limit: String(state.limit),
        sort: f.sort,
    });
    if (f.query) params.set("query", f.query);
    if (f.tag) params.set("tag", f.tag);
    if (f.favorite) params.set("favorite", "1");

    fetch(`${API}/images?${params}`)
        .then((r) => r.json())
        .then((data) => {
            state.items.push(...data.items);
            state.total = data.total;
            renderCards(data.items);
            state.done = data.items.length < state.limit || state.items.length >= data.total;
            if (state.items.length === 0) empty.hidden = false;
            updateStatsText();
        })
        .catch((err) => {
            console.error(err);
            empty.hidden = false;
            empty.querySelector("p").textContent = "Failed to load: " + err.message;
        })
        .finally(() => { state.loading = false; });
}

function loadTags() {
    fetch(`${API}/tags`)
        .then((r) => r.json())
        .then((data) => {
            state.tags = data.tags || [];
            renderTagbar();
        })
        .catch(() => {});
}

function refreshStats() {
    fetch(`${API}/stats`)
        .then((r) => r.json())
        .then((data) => {
            updateStatsText(data.stats);
        })
        .catch(() => {});
}

function updateStatsText(stats) {
    if (!stats) {
        statsEl.textContent = `${state.items.length}/${state.total || "?"} shown`;
    } else {
        statsEl.textContent = `${stats.total_images} indexed · ${stats.favorites} ★`;
    }
}

// --------------------------------------------------------------------------- //
// Rendering
// --------------------------------------------------------------------------- //

function renderCards(items) {
    const frag = document.createDocumentFragment();
    for (const item of items) {
        const card = document.createElement("div");
        card.className = "card";
        card.dataset.name = item.filename;
        card.innerHTML = `
            <img class="card__img" loading="lazy" src="${escapeHtml(item.thumb)}" alt="" />
            <span class="card__fav">${item.favorite ? "★" : ""}</span>
            <div class="card__foot">${item.width}×${item.height} · ${escapeHtml(shortName(item.filename))}</div>
        `;
        card.addEventListener("click", () => openImage(item));
        frag.appendChild(card);
    }
    grid.appendChild(frag);
}

function renderTagbar() {
    tagbar.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const t of state.tags) {
        const chip = document.createElement("span");
        chip.className = "chip" + (state.filters.tag === t.name ? " chip--active" : "");
        chip.textContent = `${t.name} · ${t.count}`;
        chip.addEventListener("click", () => {
            state.filters.tag = state.filters.tag === t.name ? "" : t.name;
            renderTagbar();
            tagFilter.hidden = !state.filters.tag;
            if (state.filters.tag) tagFilterChip.textContent = state.filters.tag;
            resetAndLoad();
        });
        frag.appendChild(chip);
    }
    tagbar.appendChild(frag);
}

function openImage(item) {
    fetch(`${API}/image?name=${encodeURIComponent(item.filename)}`)
        .then((r) => r.json())
        .then((data) => {
            if (!data.success) return;
            state.currentImage = data.image;
            renderModal();
            modal.hidden = false;
            document.body.style.overflow = "hidden";
        })
        .catch(console.warn);
}

function closeModal() {
    modal.hidden = true;
    document.body.style.overflow = "";
    state.currentImage = null;
    modalMediaContainer.classList.remove("zoomed");
}

function renderModal() {
    const img = state.currentImage;
    if (!img) return;
    modalImg.src = img.url;
    modalName.textContent = img.filename;

    modalPositive.textContent = img.positive || "(empty)";
    if (img.negative && img.negative.trim()) {
        modalNegative.textContent = img.negative;
        negativeBlock.hidden = false;
    } else {
        negativeBlock.hidden = true;
    }

    modalMeta.innerHTML = "";
    const p = img.params || {};
    const pills = [
        ["Res", `${img.width}×${img.height}`],
        ["Seed", p.seed],
        ["Steps", p.steps],
        ["CFG", p.cfg],
        ["Sampler", p.sampler_name || p.sampler],
        ["Scheduler", p.scheduler],
        ["Model", p.model],
        ["Denoise", p.denoise],
    ];
    for (const [k, v] of pills) {
        if (v === undefined || v === null || v === "") continue;
        const span = document.createElement("span");
        span.className = "meta-pill";
        span.innerHTML = `<b>${escapeHtml(String(k))}</b> ${escapeHtml(String(v))}`;
        modalMeta.appendChild(span);
    }

    const raw = [];
    if (img.raw_prompt) raw.push("// prompt\n" + img.raw_prompt);
    if (img.raw_workflow) raw.push("\n// workflow\n" + img.raw_workflow);
    modalRaw.textContent = raw.join("\n") || "(none)";

    updateFavoriteUI();
    renderModalTags();
}

function renderModalTags() {
    modalTags.innerHTML = "";
    const tags = (state.currentImage && state.currentImage.tags) || [];
    for (const t of tags) {
        const chip = document.createElement("span");
        chip.className = "chip chip--active";
        chip.textContent = t;
        const x = document.createElement("button");
        x.className = "chip chip--close";
        x.textContent = "✕";
        x.addEventListener("click", () => {
            api("/untag", {
                method: "POST",
                body: { name: state.currentImage.filename, tag: t },
            })
                .then(() => api("/image?name=" + encodeURIComponent(state.currentImage.filename)))
                .then((r) => r.json())
                .then((r) => {
                    if (r.success) {
                        state.currentImage = r.image;
                        renderModalTags();
                    }
                    loadTags();
                })
                .catch(console.warn);
        });
        const wrap = document.createElement("span");
        wrap.className = "chip";
        wrap.style.display = "inline-flex";
        wrap.style.gap = "4px";
        wrap.append(chip, x);
        modalTags.appendChild(wrap);
    }
}

function updateFavoriteUI() {
    const fav = state.currentImage && state.currentImage.favorite;
    modalFavorite.textContent = fav ? "★" : "☆";
    modalFavorite.setAttribute("aria-pressed", String(!!fav));
}

// --------------------------------------------------------------------------- //
// Actions
// --------------------------------------------------------------------------- //

function onReindex() {
    reindexBtn.disabled = true;
    reindexBtn.textContent = "⟳ Indexing…";
    api("/reindex", { method: "POST" })
        .then(() => {
            loadTags();
            refreshStats();
            resetAndLoad();
        })
        .catch(console.warn)
        .finally(() => {
            reindexBtn.disabled = false;
            reindexBtn.textContent = "⟳ Refresh";
        });
}

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //

function api(path, opts = {}) {
    const init = { method: opts.method || "GET", headers: {} };
    if (opts.body !== undefined) {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(opts.body);
    }
    return fetch(API + path, init).then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r;
    });
}

function copyText(text, btn) {
    navigator.clipboard.writeText(text).then(
        () => {
            const old = btn.textContent;
            btn.textContent = "✓";
            setTimeout(() => { btn.textContent = old; }, 1200);
        },
        () => {}
    );
}

function shortName(name) {
    const parts = name.split("/");
    return parts[parts.length - 1];
}

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function cssEscape(s) {
    return window.CSS && CSS.escape ? CSS.escape(s) : s.replace(/"/g, '\\"');
}

init();
