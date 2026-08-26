/* ── LaunchPad-AI Dashboard JavaScript ─────────────────────── */
/* Fetches /api/decisions and /api/latest-post, renders the UI. */

document.addEventListener("DOMContentLoaded", () => {
    loadDecisions();
    loadLatestPost();
    // Auto-refresh every 30 seconds
    setInterval(() => {
        loadDecisions();
        loadLatestPost();
    }, 30000);
});


// ── Decision Log ────────────────────────────────────────────

async function loadDecisions() {
    try {
        const resp = await fetch("/api/decisions");
        const decisions = await resp.json();
        renderDecisions(decisions);
    } catch (err) {
        console.error("Failed to load decisions:", err);
    }
}

function renderDecisions(decisions) {
    const container = document.getElementById("decision-log");
    const empty = document.getElementById("decision-log-empty");

    if (!decisions || decisions.length === 0) {
        empty.style.display = "block";
        return;
    }
    empty.style.display = "none";

    // Clear previous items (keep the empty placeholder)
    container.querySelectorAll(".decision-item").forEach(el => el.remove());

    decisions.forEach(d => {
        const item = document.createElement("div");
        item.className = "decision-item";

        const action = d.action || "unknown";
        const badgeClass = `badge-${action}`;
        const ts = d.ts ? formatTimestamp(d.ts) : "";
        const repo = d.repo || "unknown";
        const reasoning = d.reasoning || "No reasoning provided.";

        let highlightsHtml = "";
        if (d.highlights && d.highlights.length > 0) {
            highlightsHtml = `
                <div class="decision-highlights">
                    ${d.highlights.map(h => `<span class="highlight-chip">${escapeHtml(h)}</span>`).join("")}
                </div>
            `;
        }

        let linksHtml = "";
        const artifacts = d.artifacts || {};
        const links = [];
        if (artifacts.readme_pr) links.push({ label: "📄 README PR", url: artifacts.readme_pr });
        if (artifacts.portfolio_pr) links.push({ label: "🖼️ Portfolio PR", url: artifacts.portfolio_pr });
        if (d.gap) links.push({ label: `⚠️ Gap: ${d.gap}`, url: null });

        if (links.length > 0) {
            linksHtml = `
                <div class="decision-links">
                    ${links.map(l => l.url
                        ? `<a class="decision-link" href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${l.label}</a>`
                        : `<span class="decision-link" style="cursor:default;">${l.label}</span>`
                    ).join("")}
                </div>
            `;
        }

        item.innerHTML = `
            <div class="decision-header">
                <span class="decision-repo">${escapeHtml(repo)}</span>
                <span class="decision-time">${ts}</span>
            </div>
            <div class="decision-body">
                <span class="decision-action-badge ${badgeClass}">${escapeHtml(action.replace("_", " "))}</span>
                <div>
                    <div class="decision-reasoning">${escapeHtml(reasoning)}</div>
                    ${highlightsHtml}
                    ${linksHtml}
                </div>
            </div>
        `;

        container.appendChild(item);
    });
}


// ── Post Review Card ────────────────────────────────────────

async function loadLatestPost() {
    try {
        const resp = await fetch("/api/latest-post");
        const post = await resp.json();
        renderPostCard(post);
    } catch (err) {
        console.error("Failed to load latest post:", err);
    }
}

function renderPostCard(post) {
    const empty = document.getElementById("post-card-empty");
    const content = document.getElementById("post-card-content");

    if (!post || !post.post_package || Object.keys(post.post_package).length === 0) {
        empty.style.display = "block";
        content.style.display = "none";
        return;
    }

    empty.style.display = "none";
    content.style.display = "block";

    const pkg = post.post_package;

    // Repo name + badge
    document.getElementById("post-repo").textContent = post.repo || "";
    const badge = document.getElementById("post-action-badge");
    badge.textContent = (post.action || "").replace("_", " ");
    badge.className = `post-action-badge badge-${post.action || "unknown"}`;

    // Reasoning
    document.getElementById("post-reasoning").textContent = post.reasoning || "";

    // Post text
    document.getElementById("post-text").textContent = pkg.text || "";

    // Hashtags
    const hashtagsEl = document.getElementById("post-hashtags");
    hashtagsEl.innerHTML = "";
    if (pkg.hashtags && pkg.hashtags.length > 0) {
        pkg.hashtags.forEach(tag => {
            const chip = document.createElement("span");
            chip.className = "hashtag";
            chip.textContent = tag.startsWith("#") ? tag : `#${tag}`;
            hashtagsEl.appendChild(chip);
        });
    }

    // Image
    const imgContainer = document.getElementById("post-image-container");
    if (pkg.image_url) {
        document.getElementById("post-image").src = pkg.image_url;
        imgContainer.style.display = "block";
    } else {
        imgContainer.style.display = "none";
    }

    // LinkedIn share link
    const linkedinBtn = document.getElementById("btn-linkedin");
    const shareText = encodeURIComponent(
        (pkg.text || "") + "\n\n" + (pkg.hashtags || []).map(t => t.startsWith("#") ? t : `#${t}`).join(" ")
    );
    linkedinBtn.href = `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent("https://github.com/" + (post.repo || ""))}`;

    // Links (PRs)
    const linksEl = document.getElementById("post-links");
    linksEl.innerHTML = "";
    if (post.readme_pr) {
        linksEl.innerHTML += `<a class="post-link" href="${escapeHtml(post.readme_pr)}" target="_blank" rel="noopener">📄 README PR</a>`;
    }
    if (post.portfolio_pr) {
        linksEl.innerHTML += `<a class="post-link" href="${escapeHtml(post.portfolio_pr)}" target="_blank" rel="noopener">🖼️ Portfolio PR</a>`;
    }
}


// ── Utilities ───────────────────────────────────────────────

function copyPostContent() {
    const text = document.getElementById("post-text").textContent;
    const hashtags = Array.from(document.querySelectorAll(".hashtag"))
        .map(el => el.textContent)
        .join(" ");
    const full = text + "\n\n" + hashtags;

    navigator.clipboard.writeText(full).then(() => {
        showToast("Copied to clipboard!");
        const btn = document.getElementById("btn-copy");
        btn.textContent = "✅ Copied!";
        btn.classList.add("copied");
        setTimeout(() => {
            btn.textContent = "📋 Copy All";
            btn.classList.remove("copied");
        }, 2000);
    }).catch(err => {
        console.error("Copy failed:", err);
        showToast("Copy failed — try selecting manually.");
    });
}

function showToast(message) {
    let toast = document.querySelector(".toast");
    if (!toast) {
        toast = document.createElement("div");
        toast.className = "toast";
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 2500);
}

function formatTimestamp(ts) {
    try {
        const d = new Date(ts);
        return d.toLocaleString("en-IN", {
            day: "numeric",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
            hour12: true,
        });
    } catch {
        return ts;
    }
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
