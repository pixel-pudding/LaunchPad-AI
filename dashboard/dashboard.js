/* ── LaunchPad AI — Dashboard Application Logic ─────────────────────── */
/* Handles tab switching, dynamic polling, decision logs, and post sharing. */

let currentPostPackage = null;

// ── Tab Switching Navigation ────────────────────────────────
function switchTab(tabName) {
    const landingView = document.getElementById("view-landing");
    const dashboardView = document.getElementById("view-dashboard");
    const landingTabBtn = document.getElementById("tab-btn-landing");
    const dashboardTabBtn = document.getElementById("tab-btn-dashboard");

    if (!landingView || !dashboardView) return;

    if (tabName === "dashboard") {
        landingView.style.display = "none";
        dashboardView.style.display = "block";
        if (landingTabBtn) landingTabBtn.classList.remove("active");
        if (dashboardTabBtn) dashboardTabBtn.classList.add("active");
        if (window.location.hash !== "#dashboard") {
            window.location.hash = "dashboard";
        }
    } else {
        landingView.style.display = "block";
        dashboardView.style.display = "none";
        if (landingTabBtn) landingTabBtn.classList.add("active");
        if (dashboardTabBtn) dashboardTabBtn.classList.remove("active");
        if (window.location.hash !== "#overview") {
            window.location.hash = "overview";
        }
    }
}

// Expose functions globally on window
window.switchTab = switchTab;
window.connectPortfolioRepo = connectPortfolioRepo;
window.editPortfolioRepo = editPortfolioRepo;

function applyHashRoute() {
    const hash = window.location.hash.replace("#", "");
    if (hash === "dashboard") {
        switchTab("dashboard");
    } else {
        switchTab("landing");
    }
}

window.addEventListener("hashchange", applyHashRoute);

// ── Portfolio Repo Connector ────────────────────────────────
function parseRepoSlug(input) {
    if (!input) return "";
    let clean = input.trim().replace(/^https?:\/\/github\.com\//i, "").replace(/\/$/, "").replace(/\.git$/i, "");
    const parts = clean.split("/").filter(Boolean);
    if (parts.length >= 2) {
        return `${parts[0]}/${parts[1]}`;
    }
    return clean;
}

function loadConnectedPortfolioRepo() {
    const saved = localStorage.getItem("launchpad_portfolio_repo");
    const inputWrapper = document.getElementById("repo-input-wrapper");
    const connectedState = document.getElementById("repo-connected-state");
    const nameDisplay = document.getElementById("portfolio-target-name");
    const inputEl = document.getElementById("portfolio-repo-input");

    if (saved && nameDisplay && inputWrapper && connectedState) {
        nameDisplay.textContent = saved;
        inputWrapper.style.display = "none";
        connectedState.style.display = "flex";
        if (inputEl) inputEl.value = saved;
    } else if (inputWrapper && connectedState) {
        inputWrapper.style.display = "flex";
        connectedState.style.display = "none";
        if (inputEl) inputEl.value = "";
    }
}

function connectPortfolioRepo() {
    const inputEl = document.getElementById("portfolio-repo-input");
    if (!inputEl) return;
    const slug = parseRepoSlug(inputEl.value);

    if (!slug || !slug.includes("/")) {
        showToast("Please enter a valid repo (e.g. username/portfolio or GitHub URL)");
        return;
    }

    localStorage.setItem("launchpad_portfolio_repo", slug);
    loadConnectedPortfolioRepo();
    showToast(`Connected ${slug} as target portfolio repo!`);
}

function editPortfolioRepo() {
    const inputWrapper = document.getElementById("repo-input-wrapper");
    const connectedState = document.getElementById("repo-connected-state");
    const inputEl = document.getElementById("portfolio-repo-input");

    if (inputWrapper && connectedState) {
        inputWrapper.style.display = "flex";
        connectedState.style.display = "none";
        if (inputEl) {
            inputEl.value = "";
            inputEl.focus();
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    applyHashRoute();
    loadConnectedPortfolioRepo();

    // Initial data fetch
    loadDecisions();
    loadLatestPost();

    // Auto-refresh every 30 seconds
    setInterval(() => {
        loadDecisions();
        loadLatestPost();
    }, 30000);
});

// ── Decision Log Fetching & Rendering ─────────────────────────
async function loadDecisions() {
    try {
        const resp = await fetch("/api/decisions");
        if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
        const decisions = await resp.json();
        renderDecisions(decisions);
    } catch (err) {
        console.error("Failed to fetch decisions:", err);
    }
}

function renderDecisions(decisions) {
    const container = document.getElementById("decision-log");
    const emptyState = document.getElementById("decision-log-empty");
    const countPill = document.getElementById("nav-decisions-count");

    if (!decisions || decisions.length === 0) {
        emptyState.style.display = "block";
        if (countPill) countPill.textContent = "0";
        return;
    }

    emptyState.style.display = "none";
    if (countPill) countPill.textContent = decisions.length.toString();

    // Update last sync time
    const syncText = document.getElementById("dash-last-event-text");
    if (syncText && decisions[0] && decisions[0].ts) {
        syncText.textContent = formatRelativeTime(decisions[0].ts);
    }

    // Clear previous items
    container.innerHTML = "";

    decisions.forEach(d => {
        const item = document.createElement("div");
        item.className = "decision-row-item";

        const action = d.action || "skip";
        const badgeClass = `badge-${action}`;
        const tsFormatted = d.ts ? formatTimestamp(d.ts) : "";
        const repo = d.repo || "unknown/repo";
        const tag = d.tag ? `v${d.tag.replace(/^v/, "")}` : "";
        const reasoning = d.reasoning || "No evaluation reasoning provided.";

        // Highlights
        let highlightsHtml = "";
        if (d.highlights && d.highlights.length > 0) {
            highlightsHtml = `
                <div class="decision-highlights-wrap font-mono-lp">
                    ${d.highlights.map(h => `<span class="highlight-tag">${escapeHtml(h)}</span>`).join("")}
                </div>
            `;
        }

        // Links (PRs)
        let linksHtml = "";
        const artifacts = d.artifacts || {};
        const links = [];
        if (artifacts.readme_pr) {
            links.push(`<a class="pr-link-chip font-mono-lp" href="${escapeHtml(artifacts.readme_pr)}" target="_blank" rel="noopener">📄 README PR</a>`);
        }
        if (artifacts.portfolio_pr) {
            const isMerged = artifacts.portfolio_pr_merged ? `<span class="pr-merged-indicator font-mono-lp">AUTO-MERGED</span>` : "";
            links.push(`<a class="pr-link-chip font-mono-lp" href="${escapeHtml(artifacts.portfolio_pr)}" target="_blank" rel="noopener">🖼️ Portfolio PR ${isMerged}</a>`);
        }

        if (links.length > 0) {
            linksHtml = `<div class="decision-links-row">${links.join("")}</div>`;
        }

        item.innerHTML = `
            <div class="decision-row-top">
                <div class="decision-repo-title">
                    <span>${escapeHtml(repo)}</span>
                    ${tag ? `<span class="decision-version-tag font-mono-lp">${escapeHtml(tag)}</span>` : ""}
                </div>
                <span class="decision-meta-time font-mono-lp">${escapeHtml(tsFormatted)}</span>
            </div>
            <div class="decision-row-body">
                <div class="decision-action-wrap">
                    <span class="decision-badge font-mono-lp ${badgeClass}">${escapeHtml(action)}</span>
                </div>
                <div class="decision-reasoning-text">${escapeHtml(reasoning)}</div>
                ${highlightsHtml}
                ${linksHtml}
            </div>
        `;

        container.appendChild(item);
    });
}

// ── Post Review Card Fetching & Rendering ─────────────────────
async function loadLatestPost() {
    try {
        const resp = await fetch("/api/latest-post");
        if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
        const post = await resp.json();
        renderPostCard(post);
        renderNextBuilds(post);
    } catch (err) {
        console.error("Failed to fetch latest post:", err);
    }
}

function renderPostCard(post) {
    const empty = document.getElementById("post-card-empty");
    const content = document.getElementById("post-card-content");
    const repoEl = document.getElementById("post-repo");
    const badge = document.getElementById("post-action-badge");

    if (!post || !post.post_package || Object.keys(post.post_package).length === 0) {
        if (empty) empty.style.display = "block";
        if (content) content.style.display = "none";
        if (repoEl) repoEl.textContent = "";
        if (badge) badge.style.display = "none";
        return;
    }

    if (empty) empty.style.display = "none";
    if (content) content.style.display = "block";

    currentPostPackage = post;
    const pkg = post.post_package;

    // Repo name + badge
    if (repoEl) repoEl.textContent = post.repo || "";

    if (badge) {
        badge.style.display = "inline-block";
        badge.textContent = (post.action || "READY").toUpperCase();
        badge.className = `decision-badge font-mono-lp badge-${post.action || "feature_new"}`;
    }

    // Reasoning quote
    const reasoningEl = document.getElementById("post-reasoning");
    if (reasoningEl) {
        reasoningEl.textContent = post.reasoning ? `"${post.reasoning}"` : "";
    }

    // Post body text
    const textEl = document.getElementById("post-text");
    if (textEl) {
        textEl.textContent = pkg.text || "Draft content being generated...";
    }

    // Generated Image Banner
    const imgContainer = document.getElementById("post-image-container");
    const imgEl = document.getElementById("post-image");
    if (pkg.image_url) {
        imgEl.src = pkg.image_url;
        imgContainer.style.display = "block";
    } else {
        imgContainer.style.display = "none";
    }

    // Hashtags
    const hashtagsEl = document.getElementById("post-hashtags");
    hashtagsEl.innerHTML = "";
    if (pkg.hashtags && pkg.hashtags.length > 0) {
        pkg.hashtags.forEach(tag => {
            const chip = document.createElement("span");
            chip.className = "post-hashtag-chip font-mono-lp";
            chip.textContent = tag.startsWith("#") ? tag : `#${tag}`;
            hashtagsEl.appendChild(chip);
        });
    }

    // PR Links
    const linksEl = document.getElementById("post-links");
    linksEl.innerHTML = "";
    if (post.portfolio_pr) {
        linksEl.innerHTML += `
            <a class="pr-link-chip font-mono-lp" href="${escapeHtml(post.portfolio_pr)}" target="_blank" rel="noopener">
                🖼️ View Portfolio PR ↗
            </a>
        `;
    }
    if (post.readme_pr) {
        linksEl.innerHTML += `
            <a class="pr-link-chip font-mono-lp" href="${escapeHtml(post.readme_pr)}" target="_blank" rel="noopener">
                📄 View README PR ↗
            </a>
        `;
    }
}

// ── Next Builds Footnote Card ─────────────────────────────────
function renderNextBuilds(post) {
    const section = document.getElementById("next-builds-section");
    const listEl = document.getElementById("next-builds-list");
    if (!section || !listEl) return;

    const nextBuilds = (post && post.next_builds) || [];

    if (!nextBuilds.length) {
        section.style.display = "none";
        return;
    }

    section.style.display = "block";
    listEl.innerHTML = nextBuilds.map((item, idx) => {
        const numStr = String(idx + 1).padStart(2, "0");
        const title = item.title || item.text || "";
        const reason = item.one_line_reason || item.reason || "";
        return `
            <li class="next-build-item">
                <span class="next-build-num font-mono-lp">${numStr}</span>
                <div class="next-build-content">
                    <p><strong>${escapeHtml(title)}</strong> — ${escapeHtml(reason)}</p>
                    <span class="next-build-gap-chip font-mono-lp">SKILL GAP RECOMMENDATION</span>
                </div>
            </li>
        `;
    }).join("");
}

// ── Copy Post & Open LinkedIn Composer ─────────────────────────
function copyPostContent() {
    if (!currentPostPackage || !currentPostPackage.post_package) {
        showToast("No active post draft to copy.");
        return;
    }

    const pkg = currentPostPackage.post_package;
    const text = pkg.text || "";
    const hashtags = (pkg.hashtags || []).map(t => t.startsWith("#") ? t : `#${t}`).join(" ");
    const fullContent = hashtags ? `${text}\n\n${hashtags}` : text;

    navigator.clipboard.writeText(fullContent).then(() => {
        showToast("Copied post! Opening LinkedIn composer...");
        const btn = document.getElementById("btn-copy");
        if (btn) {
            btn.textContent = "✓ Copied to clipboard!";
            btn.classList.add("copied");
            setTimeout(() => {
                btn.textContent = "📋 Copy post & Open LinkedIn";
                btn.classList.remove("copied");
            }, 2500);
        }
        // Open LinkedIn feed with active share modal
        window.open("https://www.linkedin.com/feed/?shareActive=true", "_blank");
    }).catch(err => {
        console.error("Clipboard copy failed:", err);
        showToast("Copy failed — please select and copy text manually.");
        window.open("https://www.linkedin.com/feed/?shareActive=true", "_blank");
    });
}

function editPostContent() {
    const textEl = document.getElementById("post-text");
    if (!textEl) return;
    const isEditing = textEl.getAttribute("contenteditable") === "true";
    if (isEditing) {
        textEl.setAttribute("contenteditable", "false");
        textEl.style.border = "1px solid var(--border-base)";
        showToast("Draft updated!");
    } else {
        textEl.setAttribute("contenteditable", "true");
        textEl.focus();
        textEl.style.border = "1px solid var(--accent-sage)";
        showToast("You can now edit the post directly.");
    }
}

// ── Helpers & Formatting ──────────────────────────────────────
function showToast(message) {
    let toast = document.getElementById("global-toast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "global-toast";
        toast.className = "toast font-mono-lp";
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 3000);
}

function formatTimestamp(ts) {
    try {
        const d = new Date(ts);
        return d.toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false
        }) + " UTC";
    } catch {
        return ts;
    }
}

function formatRelativeTime(ts) {
    try {
        const now = new Date();
        const past = new Date(ts);
        const diffMs = now - past;
        const diffMins = Math.floor(diffMs / (1000 * 60));
        if (diffMins < 1) return "just now";
        if (diffMins < 60) return `${diffMins}m ago`;
        const diffHours = Math.floor(diffMins / 60);
        if (diffHours < 24) return `${diffHours}h ago`;
        const diffDays = Math.floor(diffHours / 24);
        return `${diffDays}d ago`;
    } catch {
        return "recently";
    }
}

function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
