// Powers the "Upload in bulk" modals on the Profiles page (staff + students).
// Relies on openModal(id) / closeModal(id) already defined in profile-modals.js.
// Kept separate from the generic ".modal-form" auto-submit handler because a
// successful upload needs to show a results summary (added / skipped rows)
// instead of just redirecting straight away.

(function () {

    function clearErrors(form) {
        form.querySelectorAll(".form-error").forEach((el) => el.remove());
    }

    function showError(afterEl, message) {
        const errorEl = document.createElement("p");
        errorEl.className = "form-error";
        errorEl.textContent = message;
        afterEl.insertAdjacentElement("afterend", errorEl);
    }

    function showUploadSummary(resultLabel, data) {
        const skipped = data.skipped || [];
        const parts = [
            `<div class="view-row"><span class="view-label">${resultLabel} added</span><span>${data.added}</span></div>`,
            `<div class="view-row"><span class="view-label">Rows processed</span><span>${data.total_rows}</span></div>`,
            `<div class="view-row"><span class="view-label">Rows skipped</span><span>${skipped.length}</span></div>`,
        ];
        if (skipped.length) {
            parts.push(
                '<div class="bulk-skip-list">' +
                skipped.map((item) => `<p class="form-hint">Row ${item.row}: ${item.reason}</p>`).join("") +
                "</div>"
            );
        }
        document.getElementById("bulkUploadSummaryBody").innerHTML = parts.join("");
        document.getElementById("bulkUploadSummaryBtn").onclick = function () {
            window.location.reload();
        };
        openModal("bulkUploadSummaryModal");
    }

    function bindBulkUploadForm(formId, resultLabel) {
        const form = document.getElementById(formId);
        if (!form) return;

        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            clearErrors(form);

            const fileInput = form.querySelector('input[type="file"]');
            if (!fileInput || !fileInput.files.length) {
                showError(fileInput, "Choose a CSV file first.");
                return;
            }

            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) submitBtn.disabled = true;

            try {
                const response = await fetch(form.action, {
                    method: "POST",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                    body: new FormData(form),
                });
                const data = await response.json();

                if (!data.success) {
                    const message = (data.errors && Object.values(data.errors)[0]) || "Upload failed. Check the file and try again.";
                    showError(fileInput, message);
                    return;
                }

                closeModal(form.closest(".modal-overlay").id);
                showUploadSummary(resultLabel, data);
            } catch (err) {
                console.error("Bulk upload failed:", err);
                showError(fileInput, "Something went wrong uploading that file. Please try again.");
            } finally {
                if (submitBtn) submitBtn.disabled = false;
            }
        });
    }

    bindBulkUploadForm("studentBulkUploadForm", "Students");
    bindBulkUploadForm("staffBulkUploadForm", "Staff");

})();