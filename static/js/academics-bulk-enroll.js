// Powers the "Bulk enroll" modal on Academics > Enrollment.
// Relies on openModal(id) / closeModal(id) already defined in profile-modals.js.
// Kept off the generic ".modal-form" auto-submit handler (see profile-modals.js)
// because this form posts checkbox arrays and shows its own results summary.

(function () {
    const form = document.getElementById("bulkEnrollForm");
    if (!form) return;

    const search = document.getElementById("bulk-enroll-search");
    const list = document.getElementById("bulkStudentList");
    const rows = list ? Array.from(list.querySelectorAll(".bulk-student-row")) : [];
    const selectedCountEl = document.getElementById("bulkEnrollSelectedCount");
    const classSelect = document.getElementById("bulk-enroll-class");

    function checkboxOf(row) {
        return row.querySelector('input[type="checkbox"]');
    }

    function updateSelectedCount() {
        const count = rows.filter((row) => checkboxOf(row).checked).length;
        if (selectedCountEl) {
            selectedCountEl.textContent = `${count} student${count === 1 ? "" : "s"} selected`;
        }
    }

    function showError(afterEl, message) {
        const errorEl = document.createElement("p");
        errorEl.className = "form-error";
        errorEl.textContent = message;
        afterEl.insertAdjacentElement("afterend", errorEl);
    }

    rows.forEach((row) => {
        checkboxOf(row).addEventListener("change", updateSelectedCount);
    });

    if (search) {
        search.addEventListener("input", () => {
            const query = search.value.trim().toLowerCase();
            rows.forEach((row) => {
                const matches = !query || row.dataset.name.includes(query);
                row.style.display = matches ? "" : "none";
            });
        });
    }

    document.querySelectorAll("[data-bulk-select]").forEach((btn) => {
        btn.addEventListener("click", () => {
            const mode = btn.dataset.bulkSelect;
            rows.forEach((row) => {
                if (row.style.display === "none") return; // respect the current search filter
                const checkbox = checkboxOf(row);
                if (mode === "all") checkbox.checked = true;
            });
            updateSelectedCount();
        });
    });

    // Native form.reset() clears input values but not our own filter state,
    // so put the list back to a clean slate whenever the modal is closed.
    form.addEventListener("reset", () => {
        setTimeout(() => {
            rows.forEach((row) => { row.style.display = ""; });
            if (search) search.value = "";
            updateSelectedCount();
        }, 0);
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        form.querySelectorAll(".form-error").forEach((el) => el.remove());

        const className = classSelect.value;
        const checkedIds = rows
            .filter((row) => checkboxOf(row).checked)
            .map((row) => checkboxOf(row).value);

        let hasError = false;
        if (!className) {
            showError(classSelect, "Choose a class before enrolling.");
            hasError = true;
        }
        if (!checkedIds.length) {
            showError(list, "Select at least one student.");
            hasError = true;
        }
        if (hasError) return;

        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;

        try {
            const formData = new FormData();
            formData.append("class_name", className);
            checkedIds.forEach((id) => formData.append("student_ids", id));

            const response = await fetch(form.action, {
                method: "POST",
                headers: { "X-Requested-With": "XMLHttpRequest" },
                body: formData,
            });
            const data = await response.json();

            if (!data.success) {
                const message = (data.errors && Object.values(data.errors)[0]) || "Enrollment failed. Please try again.";
                showError(list, message);
                return;
            }

            closeModal("bulkEnrollModal");
            document.getElementById("bulkEnrollSummaryBody").innerHTML = `
                <div class="view-row"><span class="view-label">Students enrolled</span><span>${checkedIds.length}</span></div>
                <div class="view-row"><span class="view-label">Class</span><span>${className}</span></div>
            `;
            document.getElementById("bulkEnrollSummaryBtn").onclick = function () {
                window.location.reload();
            };
            openModal("bulkEnrollSummaryModal");
        } catch (err) {
            console.error("Bulk enroll failed:", err);
            showError(list, "Something went wrong enrolling those students. Please try again.");
        } finally {
            if (submitBtn) submitBtn.disabled = false;
        }
    });
})();