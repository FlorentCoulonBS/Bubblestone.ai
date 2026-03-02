/* LinkedIn Generator — BubbleStone AI */

// Toast notification
function toast(message, type = 'success') {
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

// API call helper
async function api(url, method = 'POST', data = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (data) opts.body = JSON.stringify(data);
    const res = await fetch(url, opts);
    const json = await res.json();
    if (!res.ok || json.error) {
        throw new Error(json.error || `HTTP ${res.status}`);
    }
    return json;
}

// Validate post (generate image)
async function validatePost(postId, detail = false) {
    const btn = event?.target;
    if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳ Génération image...';
    }
    try {
        const result = await api(`/api/post/${postId}/validate`);
        toast('Post validé !');
        if (result.error) toast(result.error, 'error');
        setTimeout(() => location.reload(), 500);
    } catch (e) {
        toast(e.message, 'error');
        if (btn) {
            btn.disabled = false;
            btn.textContent = '✅ Valider';
        }
    }
}

// Reject post
async function rejectPost(postId, detail = false) {
    if (!confirm('Rejeter ce post ?')) return;
    try {
        await api(`/api/post/${postId}/reject`);
        toast('Post rejeté');
        setTimeout(() => {
            if (detail) location.href = '/';
            else location.reload();
        }, 500);
    } catch (e) {
        toast(e.message, 'error');
    }
}

// Publish post
async function publishPost(postId, detail = false) {
    try {
        await api(`/api/post/${postId}/publish`);
        toast('Post marqué comme publié !');
        setTimeout(() => location.reload(), 500);
    } catch (e) {
        toast(e.message, 'error');
    }
}

// Save text (inline edit)
async function saveText(postId) {
    const textarea = document.getElementById('postText');
    if (!textarea) return;
    try {
        const result = await api(`/api/post/${postId}/update`, 'POST', {
            post_text: textarea.value
        });
        toast(`Sauvegardé (${result.chars} chars)`);
    } catch (e) {
        toast(e.message, 'error');
    }
}

// Copy text to clipboard
function copyText() {
    const textarea = document.getElementById('postText');
    if (!textarea) return;
    navigator.clipboard.writeText(textarea.value).then(() => {
        toast('📋 Texte copié !');
    }).catch(() => {
        textarea.select();
        document.execCommand('copy');
        toast('📋 Texte copié !');
    });
}

// Copy article markdown
function copyArticle() {
    const el = document.getElementById('articleMd');
    if (!el) return;
    navigator.clipboard.writeText(el.textContent).then(() => {
        toast('📋 Article copié !');
    }).catch(() => {
        toast('Erreur copie', 'error');
    });
}

// Regenerate image
async function regenerateImage(postId) {
    const promptEl = document.getElementById('imagePrompt');
    const prompt = promptEl ? promptEl.value : null;
    
    const btn = event?.target;
    if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳ Génération...';
    }
    
    try {
        const data = prompt ? { image_prompt: prompt } : {};
        await api(`/api/post/${postId}/regenerate-image`, 'POST', data);
        toast('Image régénérée !');
        setTimeout(() => location.reload(), 500);
    } catch (e) {
        toast(e.message, 'error');
        if (btn) {
            btn.disabled = false;
            btn.textContent = '🔄 Régénérer';
        }
    }
}

// Character counter for textarea
document.addEventListener('DOMContentLoaded', () => {
    const textarea = document.getElementById('postText');
    const counter = document.getElementById('charCount');
    if (textarea && counter) {
        textarea.addEventListener('input', () => {
            const len = textarea.value.length;
            counter.textContent = `${len} chars`;
            counter.style.color = len > 1300 ? '#ef4444' : len > 1100 ? '#f59e0b' : '';
        });
    }
});
