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
const emptyRefresh = el("empty-refresh");

const modal = el("modal");
const modalImg = el("modal-img");
const modalName = el("modal-name");
const modalFilename = el("modal-filename");
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
let _lastDateGroup = null;

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
    if (emptyRefresh) emptyRefresh.addEventListener("click", onReindex);
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

    // ── Zoom: transform-origin at cursor, clamped pan, scroll-wheel ──
    // ── Zoom: transform-origin at cursor, clamped pan, scroll-wheel ──
// ── Zoom: transform-origin center, clamped pan, smooth scroll ──
    if (modalZoomBtn) {
        const Z = {
            scale: 1,
            x: 0, y: 0,
            dragging: false,
            moved: false,
            startX: 0, startY: 0,
            startTx: 0, startTy: 0
        };

        const apply = (animate = false) => {
            // Мягкий транзишн только для кликов, при драге — вырубаем, чтобы не было "резины"
            modalImg.style.transition = animate ? 'transform 0.15s ease-out' : 'none';
            modalImg.style.transform = `translate(${Z.x}px, ${Z.y}px) scale(${Z.scale})`;
        };

const clamp = () => {
            if (Z.scale <= 1) { 
                Z.x = 0; Z.y = 0; 
                return; 
            }

            const cw = modalMediaContainer.clientWidth;
            const ch = modalMediaContainer.clientHeight;
            
            // Берем ИСТИННЫЕ размеры картинки из файла
            const nw = modalImg.naturalWidth;
            const nh = modalImg.naturalHeight;
            if (!nw || !nh) return;

            // Вычисляем, какой размер картинка имеет визуально при scale = 1 (эмуляция object-fit: contain)
            const containerRatio = cw / ch;
            const imageRatio = nw / nh;

            let renderedW, renderedH;
            if (imageRatio > containerRatio) {
                // Картинка шире контейнера (горизонтальная)
                renderedW = cw;
                renderedH = cw / imageRatio;
            } else {
                // Картинка выше контейнера (вертикальная - твой случай)
                renderedW = ch * imageRatio;
                renderedH = ch;
            }

            // Умножаем ВИДИМЫЕ размеры на зум
            const scaledW = renderedW * Z.scale;
            const scaledH = renderedH * Z.scale;

            // Считаем максимально допустимое смещение. 
            // Если отзумленная картинка всё ещё меньше экрана по какой-то оси, не даем ее двигать (max = 0)
            const maxTx = Math.max(0, (scaledW - cw) / 2);
            const maxTy = Math.max(0, (scaledH - ch) / 2);

            // Жестко зажимаем
            Z.x = Math.max(-maxTx, Math.min(maxTx, Z.x));
            Z.y = Math.max(-maxTy, Math.min(maxTy, Z.y));
        };

        const resetZoom = () => {
            Z.scale = 1; Z.x = 0; Z.y = 0;
            modalMediaContainer.classList.remove("zoomed");
            modalZoomBtn.textContent = "⊕";
            apply(true);
        };

        const zoomTo = (newScale, clientX, clientY, animate = false) => {
            const min = 1, max = 15;
            const targetScale = Math.max(min, Math.min(max, newScale));
            if (targetScale === Z.scale) return;

            const rect = modalImg.getBoundingClientRect();
            // Центр текущего отрендеренного прямоугольника
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;

            const ratio = targetScale / Z.scale;
            Z.scale = targetScale;

            if (Z.scale > 1) {
                modalMediaContainer.classList.add("zoomed");
                modalZoomBtn.textContent = "⊖";
            } else {
                modalMediaContainer.classList.remove("zoomed");
                modalZoomBtn.textContent = "⊕";
            }

            // Магия сдвига: корректируем X и Y так, чтобы точка под курсором осталась на месте
            Z.x -= (clientX - cx) * (ratio - 1);
            Z.y -= (clientY - cy) * (ratio - 1);

            clamp();
            apply(animate);
        };

        modalZoomBtn.addEventListener("click", () => {
            if (Z.scale > 1) resetZoom();
            else {
                const rect = modalMediaContainer.getBoundingClientRect();
                zoomTo(2.5, rect.left + rect.width / 2, rect.top + rect.height / 2, true);
            }
        });

        modalImg.addEventListener("click", (e) => {
            if (Z.moved) { Z.moved = false; return; }
            if (Z.scale > 1) resetZoom();
            else zoomTo(2.5, e.clientX, e.clientY, true);
        });

        modalMediaContainer.addEventListener("wheel", (e) => {
            e.preventDefault();
            // Плавный расчет множителя на основе дельты колесика. 
            // Идеально работает и для мышей, и для маковских трекпадов.
            let delta = e.deltaY;
            if (delta > 200) delta = 200; 
            if (delta < -200) delta = -200;
            const factor = Math.exp(-delta * 0.002);
            
            zoomTo(Z.scale * factor, e.clientX, e.clientY, false);
        }, { passive: false });

        modalImg.addEventListener("mousedown", (e) => {
            if (Z.scale <= 1) return;
            e.preventDefault();
            Z.dragging = true;
            Z.moved = false;
            Z.startX = e.clientX;
            Z.startY = e.clientY;
            Z.startTx = Z.x;
            Z.startTy = Z.y;
        });

        window.addEventListener("mousemove", (e) => {
            if (!Z.dragging) return;
            const dx = e.clientX - Z.startX;
            const dy = e.clientY - Z.startY;
            // Погрешность в 3 пикселя, чтобы не считать микро-сдвиги при клике за скролл
            if (Math.abs(dx) > 3 || Math.abs(dy) > 3) Z.moved = true;
            Z.x = Z.startTx + dx;
            Z.y = Z.startTy + dy;
            clamp();
            apply(false); // Вырубаем анимацию, иначе интерфейс будет вязким как кисель
        });

        window.addEventListener("mouseup", () => { Z.dragging = false; });
        modalImg.addEventListener('dragstart', (e) => e.preventDefault()); // Защита от нативного драга картинок
        
        // Сброс зума, если в модалку загрузилась другая картинка
        modalImg.addEventListener('load', resetZoom);
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
    _lastDateGroup = null;
    loadPage();
}

function loadPage() {
    if (state.loading || state.done) return;
    state.loading = true;
    state.page += 1;

    // Show skeleton cards during load (only for first page)
    if (state.page === 1) {
        showSkeletons(state.limit);
    }

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
            if (state.items.length === 0) {
                empty.hidden = false;
            } else {
                empty.hidden = true;
            }
            updateStatsText();
        })
        .catch((err) => {
            console.error(err);
            grid.querySelectorAll(".card--skeleton").forEach((c) => c.remove());
            empty.hidden = false;
            const p = empty.querySelector(".empty__text");
            if (p) p.textContent = "Failed to load: " + err.message;
        })
        .finally(() => { state.loading = false; });
}

function showSkeletons(count) {
    const frag = document.createDocumentFragment();
    for (let i = 0; i < count; i++) {
        const card = document.createElement("div");
        card.className = "card card--skeleton";
        card.setAttribute("aria-hidden", "true");
        card.innerHTML = `
            <div class="card__img-wrap"></div>
        `;
        frag.appendChild(card);
    }
    grid.appendChild(frag);
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
    // Remove any skeleton cards
    grid.querySelectorAll(".card--skeleton").forEach((c) => c.remove());

    const frag = document.createDocumentFragment();
    for (const item of items) {
        const group = dateGroup(item.mtime);
        if (group !== _lastDateGroup) {
            _lastDateGroup = group;
            const sep = document.createElement("div");
            sep.className = "date-sep";
            sep.setAttribute("role", "separator");
            sep.textContent = group;
            frag.appendChild(sep);
        }

        const card = document.createElement("div");
        card.className = "card";
        card.dataset.name = item.filename;
        card.setAttribute("role", "article");
        card.setAttribute("tabindex", "0");
        card.innerHTML = `
            <div class="card__img-wrap">
                <img class="card__img" loading="lazy" src="${escapeHtml(item.thumb)}" alt="${escapeHtml(shortName(item.filename))}" />
            </div>
            <span class="card__fav" aria-hidden="true">${item.favorite ? "★" : ""}</span>
        `;
        card.addEventListener("click", () => openImage(item));
        card.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                openImage(item);
            }
        });
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
    modalImg.style.transform = "";
    modalImg.style.transformOrigin = "";
    modalImg.style.transition = "";
}

function renderModal() {
    const img = state.currentImage;
    if (!img) return;
    modalImg.src = img.url;
    modalName.textContent = promptTitle(img.positive);
    if (modalFilename) modalFilename.textContent = img.filename;

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

function promptTitle(positive) {
    if (!positive || !positive.trim()) return "Image details";
    const parts = positive.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length === 0) return "Image details";
    // Take first 3-4 keywords, keep total under ~70 chars
    let title = "";
    for (let i = 0; i < Math.min(parts.length, 4); i++) {
        const next = title ? title + ", " + parts[i] : parts[i];
        if (next.length > 70) break;
        title = next;
    }
    // Remove trailing comma artifacts
    return title.replace(/,\s*$/, "") || "Image details";
}

function dateGroup(ts) {
    if (!ts) return "Unsorted";
    const d = new Date(ts * 1000);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const dateOnly = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diffDays = Math.floor((today - dateOnly) / 86400000);

    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 7) return "This week";
    if (diffDays < 14) return "Last week";
    if (diffDays < 30) return "This month";

    const months = ["January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"];
    const month = months[d.getMonth()];
    if (d.getFullYear() === now.getFullYear()) {
        return `${month} ${d.getDate()}`;
    }
    return `${month} ${d.getDate()}, ${d.getFullYear()}`;
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
