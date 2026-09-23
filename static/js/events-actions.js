(function () {
    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function parseRecord(button) {
        try {
            return JSON.parse(button.dataset.record || "{}");
        } catch (error) {
            console.error("Could not read event data:", error);
            return {};
        }
    }

    function setValue(id, value) {
        const element = document.getElementById(id);
        if (element) element.value = value || "";
    }

    function setSelectedClasses(selectId, audience) {
        const select = document.getElementById(selectId);
        if (!select) return;
        const selected = new Set(String(audience || "").split(",").map((item) => item.trim()).filter(Boolean));
        Array.from(select.options).forEach((option) => {
            option.selected = selected.has(option.value);
        });
    }

    function syncAudienceFields(scope) {
        const root = scope || document;
        root.querySelectorAll(".audience-mode").forEach((select) => {
            const field = select.closest("form").querySelector(".audience-classes-field");
            if (field) field.hidden = select.value !== "Classes";
        });
    }

    function detailRows(rows) {
        return rows.map(([label, value]) => `
            <div class="view-row">
                <span class="view-label">${escapeHtml(label)}</span>
                <span>${escapeHtml(value || "—")}</span>
            </div>
        `).join("");
    }

    function openEventView(record) {
        document.getElementById("eventViewTitle").textContent = record.name || "Event details";
        document.getElementById("eventViewBody").innerHTML = detailRows([
            ["Name", record.name],
            ["Date range", record.date_range],
            ["Audience", record.audience],
            ["Teacher in charge", record.teacher],
            ["Activity", record.activity],
        ]);
        openModal("eventViewModal");
    }

    function openEventEdit(record) {
        document.getElementById("eventEditForm").action = `${EVENT_URL_BASE}/${record.id}/edit`;
        setValue("event-edit-name", record.name);
        setValue("event-edit-start", record.start_date);
        setValue("event-edit-end", record.end_date);
        setValue("event-edit-teacher", record.teacher);
        const isWholeSchool = record.audience === "Whole school";
        setValue("event-edit-audience-mode", isWholeSchool ? "Whole school" : "Classes");
        setSelectedClasses("event-edit-audience-classes", isWholeSchool ? "" : record.audience);
        syncAudienceFields(document.getElementById("eventEditForm"));
        openModal("eventEditModal");
    }

    function openDeleteConfirm(formId, label) {
        document.getElementById("confirmDeleteText").textContent =
            `This will permanently remove ${label}. This can't be undone.`;
        document.getElementById("confirmDeleteBtn").onclick = function () {
            document.getElementById(formId).submit();
        };
        openModal("confirmDeleteModal");
    }

    document.addEventListener("change", (event) => {
        if (event.target.classList.contains("audience-mode")) {
            syncAudienceFields(event.target.closest("form"));
        }
    });

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-event-action]");
        if (!button) return;

        if (button.dataset.eventAction === "view") {
            openEventView(parseRecord(button));
        } else if (button.dataset.eventAction === "edit") {
            openEventEdit(parseRecord(button));
        } else if (button.dataset.eventAction === "delete") {
            openDeleteConfirm(button.dataset.formId, button.dataset.label || "this event");
        }
    });

    document.addEventListener("DOMContentLoaded", () => {
        syncAudienceFields(document);
    });
})();
