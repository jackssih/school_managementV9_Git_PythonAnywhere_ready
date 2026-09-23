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
            console.error("Could not read attendance data:", error);
            return {};
        }
    }

    function currentTime() {
        const now = new Date();
        return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
    }

    function statusOptions(selected) {
        return `
            <option value="">Choose</option>
            ${ATTENDANCE_STATUSES.map((status) => (
                `<option value="${status}" ${selected === status ? "selected" : ""}>${status}</option>`
            )).join("")}
        `;
    }

    function detailRows(rows) {
        return rows.map(([label, value]) => `
            <div class="view-row">
                <span class="view-label">${escapeHtml(label)}</span>
                <span>${escapeHtml(value || "—")}</span>
            </div>
        `).join("");
    }

    function openAttendanceView(record) {
        document.getElementById("attendanceViewTitle").textContent = record.entity || "Attendance details";
        document.getElementById("attendanceViewBody").innerHTML = detailRows([
            ["Date", record.date],
            ["Type", record.attendance_type],
            ["Session", record.session],
            ["Entity", record.entity],
            ["Attendances", record.attendance_label],
        ]);
        openModal("attendanceViewModal");
    }

    function openDeleteConfirm(formId, label) {
        document.getElementById("confirmDeleteText").textContent =
            `This will permanently remove ${label}. This can't be undone.`;
        document.getElementById("confirmDeleteBtn").onclick = function () {
            document.getElementById(formId).submit();
        };
        openModal("confirmDeleteModal");
    }

    function openAttendanceMarks(record) {
        document.getElementById("attendanceMarksTitle").textContent =
            `${record.entity} attendance · ${record.attendance_label}`;
        document.getElementById("attendanceMarksForm").action = `${ATTENDANCE_URL_BASE}/${record.id}/marks`;
        document.getElementById("attendance-mark-all").value = "";

        const students = record.students || [];
        document.getElementById("attendanceGrid").innerHTML = students.length
            ? `
                <div class="attendance-row attendance-row-header">
                    <span>Name</span>
                    <span>Status</span>
                    <span>Time</span>
                </div>
                ${students.map((student) => `
                    <div class="attendance-row">
                        <div>
                            <p class="promotion-name">${escapeHtml(student.name)}</p>
                        </div>
                        <select class="form-input attendance-status" name="status_${student.id}">
                            ${statusOptions(student.status)}
                        </select>
                        <div class="attendance-time-cell">
                            <input class="form-input attendance-time" type="text" name="time_${student.id}"
                                   value="${escapeHtml(student.time || "")}" placeholder="Optional">
                            <button type="button" class="secondary-btn attendance-time-btn">Add time</button>
                        </div>
                    </div>
                `).join("")}
            `
            : '<p class="form-subheading">No students found for this attendance record.</p>';

        openModal("attendanceMarksModal");
    }

    function syncEntityFields() {
        const type = document.getElementById("attendance-type").value;
        document.querySelectorAll(".attendance-entity-field").forEach((field) => {
            field.hidden = field.dataset.entityField !== type;
        });
        const session = document.getElementById("attendance-session");
        if (type === "Class") {
            session.value = "Day";
        } else if (type === "Subject" && session.value === "Day") {
            session.value = "Period 1";
        }
    }

    document.addEventListener("click", (event) => {
        const marksButton = event.target.closest('[data-attendance-action="marks"]');
        if (marksButton) {
            openAttendanceMarks(parseRecord(marksButton));
            return;
        }

        const viewButton = event.target.closest('[data-attendance-action="view"]');
        if (viewButton) {
            openAttendanceView(parseRecord(viewButton));
            return;
        }

        const deleteButton = event.target.closest('[data-attendance-action="delete"]');
        if (deleteButton) {
            openDeleteConfirm(deleteButton.dataset.formId, deleteButton.dataset.label || "this attendance");
            return;
        }

        const timeButton = event.target.closest(".attendance-time-btn");
        if (timeButton) {
            const input = timeButton.closest(".attendance-time-cell").querySelector(".attendance-time");
            input.value = currentTime();
        }
    });

    document.addEventListener("change", (event) => {
        if (event.target.id === "attendance-type") {
            syncEntityFields();
        }
        if (event.target.id === "attendance-mark-all") {
            const value = event.target.value;
            document.querySelectorAll(".attendance-status").forEach((select) => {
                select.value = value;
            });
        }
    });

    document.addEventListener("DOMContentLoaded", () => {
        const type = document.getElementById("attendance-type");
        if (type) syncEntityFields();

        const resetButton = document.getElementById("attendanceResetBtn");
        if (resetButton) {
            resetButton.addEventListener("click", () => {
                document.getElementById("attendance-mark-all").value = "";
                document.querySelectorAll(".attendance-status").forEach((select) => {
                    select.value = "";
                });
                document.querySelectorAll(".attendance-time").forEach((input) => {
                    input.value = "";
                });
            });
        }
    });
})();