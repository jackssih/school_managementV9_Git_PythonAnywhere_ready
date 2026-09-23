function openCellEditor(day, periodId, className, subject, teacher) {
    document.getElementById("cellEditorTitle").textContent = `${className} · ${day}`;
    document.getElementById("cellDay").value = day;
    document.getElementById("cellPeriodId").value = periodId;
    document.getElementById("cellClassName").value = className;
    document.getElementById("cellSubject").value = subject || "";

    const teacherSelect = document.getElementById("cellTeacher");
    const teacherValue = teacher || "";
    const hasOption = Array.from(teacherSelect.options).some((opt) => opt.value === teacherValue);
    if (teacherValue && !hasOption) {
        const legacyOption = document.createElement("option");
        legacyOption.value = teacherValue;
        legacyOption.textContent = `${teacherValue} (not in Staff)`;
        teacherSelect.appendChild(legacyOption);
    }
    teacherSelect.value = teacherValue;

    openModal("cellEditorModal");
}

function clearCellAndSubmit() {
    document.getElementById("cellSubject").value = "";
    document.getElementById("cellTeacher").value = "";
    document.getElementById("cellEditorForm").requestSubmit();
}