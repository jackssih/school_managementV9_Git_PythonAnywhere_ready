function openModal(id) {
    const overlay = document.getElementById(id);
    if (!overlay) return;
    overlay.classList.add("open");
    const firstInput = overlay.querySelector("input, select");
    if (firstInput) firstInput.focus();
}

function closeModal(id) {
    const overlay = document.getElementById(id);
    if (!overlay) return;
    overlay.classList.remove("open");
    overlay.querySelectorAll(".form-error").forEach((el) => el.remove());
    const form = overlay.querySelector("form");
    if (form) form.reset();
}

document.addEventListener("DOMContentLoaded", () => {
    // Click outside the dialog closes it
    document.querySelectorAll(".modal-overlay").forEach((overlay) => {
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) closeModal(overlay.id);
        });
    });

    // Escape closes whichever modal is open
    document.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        document.querySelectorAll(".modal-overlay.open").forEach((overlay) => closeModal(overlay.id));
    });

    // Intercept submit on both forms and post via fetch so we never leave the page
    document.querySelectorAll(".modal-form").forEach((form) => {
        form.addEventListener("submit", async (e) => {
            e.preventDefault();

            form.querySelectorAll(".form-error").forEach((el) => el.remove());

            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) submitBtn.disabled = true;

            try {
                const response = await fetch(form.action, {
                    method: "POST",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                    body: new FormData(form),
                });
                const data = await response.json();

                if (data.success) {
                    window.location = data.redirect;
                    return;
                }

                for (const [field, message] of Object.entries(data.errors || {})) {
                    const input = form.querySelector(`[name="${field}"]`);
                    if (!input) continue;
                    const errorEl = document.createElement("p");
                    errorEl.className = "form-error";
                    errorEl.textContent = message;
                    input.insertAdjacentElement("afterend", errorEl);
                }
            } catch (err) {
                console.error("Form submission failed:", err);
            } finally {
                if (submitBtn) submitBtn.disabled = false;
            }
        });
    });
});