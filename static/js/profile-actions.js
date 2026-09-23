// Powers the "Actions" column (view / edit / delete) on the Profiles page.
// Relies on openModal(id) / closeModal(id) already defined in profile-modals.js.

(function () {

    // --- Staff ---

    window.openStaffView = function (member) {
        document.getElementById("staffViewBody").innerHTML = `
            <div class="view-row"><span class="view-label">Full name</span><span>${member.name || "—"}</span></div>
            <div class="view-row"><span class="view-label">Email</span><span>${member.email || "—"}</span></div>
            <div class="view-row"><span class="view-label">Phone</span><span>${member.phone || "—"}</span></div>
            <div class="view-row"><span class="view-label">Role</span><span>${member.role || "—"}</span></div>
            <div class="view-row"><span class="view-label">Status</span><span>${member.status || "—"}</span></div>
            <div class="view-row"><span class="view-label">Created on</span><span>${member.created_on || "—"}</span></div>
        `;
        openModal("staffViewModal");
    };

    window.openStaffEdit = function (member) {
        const form = document.getElementById("staffEditForm");
        form.action = `${STAFF_EDIT_URL_BASE}/${member.id}/edit`;
        document.getElementById("staff-edit-name").value = member.name || "";
        document.getElementById("staff-edit-email").value = member.email || "";
        document.getElementById("staff-edit-phone").value = member.phone || "";
        document.getElementById("staff-edit-role").value = member.role || "teacher";
        openModal("staffEditModal");
    };

    // --- Students ---

    window.openStudentView = function (student) {
        document.getElementById("studentViewBody").innerHTML = `
            <div class="view-row"><span class="view-label">Full name</span><span>${student.name || "—"}</span></div>
            <div class="view-row"><span class="view-label">Gender</span><span>${student.gender || "—"}</span></div>
            <div class="view-row"><span class="view-label">Date of birth</span><span>${student.date_of_birth || "—"}</span></div>
            <div class="view-row"><span class="view-label">LIN</span><span>${student.lin || "—"}</span></div>
            <div class="view-row"><span class="view-label">Class</span><span>${student.class_name || "—"}</span></div>
            <div class="view-row"><span class="view-label">Status</span><span>${student.status || "—"}</span></div>
            <div class="view-row"><span class="view-label">Created on</span><span>${student.created_on || "—"}</span></div>
        `;
        openModal("studentViewModal");
    };

    window.openStudentEdit = function (student) {
        const form = document.getElementById("studentEditForm");
        form.action = `${STUDENT_EDIT_URL_BASE}/${student.id}/edit`;
        document.getElementById("student-edit-registration-number").value = student.registration_number || "";
        document.getElementById("student-edit-name").value = student.name || "";
        document.getElementById("student-edit-gender").value = student.gender || "";
        document.getElementById("student-edit-dob").value = student.date_of_birth || "";
        document.getElementById("student-edit-lin").value = student.lin || "";
        openModal("studentEditModal");
    };

    // --- Shared delete confirmation ---

    window.openDeleteConfirm = function (formId, label) {
        document.getElementById("confirmDeleteText").textContent =
            `This will permanently remove ${label}. This can't be undone.`;
        const btn = document.getElementById("confirmDeleteBtn");
        btn.onclick = function () {
            document.getElementById(formId).submit();
        };
        openModal("confirmDeleteModal");
    };

})();