(function() {
    function openDeleteConfirm(formId, label) {
        document.getElementById("confirmDeleteText").textContent =
            `This will permanently remove ${label}. This can't be undone.`;
        document.getElementById("confirmDeleteBtn").onclick = function() {
            document.getElementById(formId).submit();
        };
        openModal("confirmDeleteModal");
    }

    function openTimetableEditor(record) {
        if (!record || !record.id) return;
        document.getElementById("editTimetableForm").action = `/timetable/${record.id}/edit`;
        document.getElementById("timetable-edit-name").value = record.name || "";

        const selectedClasses = new Set(record.classes || []);
        document.querySelectorAll(".timetable-edit-class").forEach((checkbox) => {
            checkbox.checked = selectedClasses.has(checkbox.value);
        });

        openModal("editTimetableModal");
    }

    var dutyChips = [];

    function renderDutyChips() {
        var list = document.getElementById("dutyChipList");
        list.innerHTML = "";
        if (!dutyChips.length) {
            var empty = document.createElement("span");
            empty.className = "duty-chip-empty";
            empty.textContent = "No teacher assigned yet.";
            list.appendChild(empty);
        } else {
            dutyChips.forEach(function (name, i) {
                var chip = document.createElement("span");
                chip.className = "duty-chip";
                chip.textContent = name;
                var remove = document.createElement("button");
                remove.type = "button";
                remove.className = "duty-chip-remove";
                remove.setAttribute("aria-label", "Remove " + name);
                remove.innerHTML = '<i class="ti ti-x"></i>';
                remove.onclick = function () { removeDutyChip(i); };
                chip.appendChild(remove);
                list.appendChild(chip);
            });
        }
        document.getElementById("dutyNames").value = dutyChips.join(", ");
    }

    function addDutyChip() {
        var input = document.getElementById("dutyNameInput");
        var name = input.value.trim();
        if (!name || dutyChips.indexOf(name) !== -1) return;
        dutyChips.push(name);
        input.value = "";
        renderDutyChips();
        input.focus();
    }

    function removeDutyChip(index) {
        dutyChips.splice(index, 1);
        renderDutyChips();
    }

    function openDutyEditor(day, shiftId, shiftLabel, names) {
        document.getElementById("dutyEditorTitle").textContent = `${day} · ${shiftLabel}`;
        document.getElementById("dutyEditorForm").action = `/timetable/duty/${day}/${shiftId}/save`;
        dutyChips = (names || []).slice();
        renderDutyChips();
        document.getElementById("dutyNameInput").value = "";
        openModal("dutyEditorModal");

        var input = document.getElementById("dutyNameInput");
        input.onkeydown = function (event) {
            if (event.key === "Enter") {
                event.preventDefault();
                addDutyChip();
            }
        };
    }

    function openGateEditor(weekId, day, title, name) {
        document.getElementById("gateEditorTitle").textContent = title;
        document.getElementById("gateEditorForm").action = `/timetable/gate/${weekId}/${day}/save`;
        document.getElementById("gateName").value = name || "";
        openModal("gateEditorModal");
    }

    function openShiftEditor(shiftId, label, time) {
        document.getElementById("shiftEditorForm").action = `/timetable/duty/shifts/${shiftId}/edit`;
        document.getElementById("shiftLabel").value = label || "";
        document.getElementById("shiftTime").value = time || "";
        openModal("shiftEditorModal");
    }

    function openWeekEditor(weekId, label, dateRange) {
        document.getElementById("weekEditorForm").action = `/timetable/gate/weeks/${weekId}/edit`;
        document.getElementById("weekLabel").value = label || "";
        document.getElementById("weekRange").value = dateRange || "";
        openModal("weekEditorModal");
    }

    window.openDeleteConfirm = openDeleteConfirm;
    window.openTimetableEditor = openTimetableEditor;
    window.openDutyEditor = openDutyEditor;
    window.addDutyChip = addDutyChip;
    window.removeDutyChip = removeDutyChip;
    window.openGateEditor = openGateEditor;
    window.openShiftEditor = openShiftEditor;
    window.openWeekEditor = openWeekEditor;

    document.addEventListener("click", function(event) {
        const button = event.target.closest("[data-timetable-action]");
        if (!button) return;

        const action = button.dataset.timetableAction;
        if (action === "edit") {
            try {
                openTimetableEditor(JSON.parse(button.dataset.record || "{}"));
            } catch (error) {
                console.error("Could not read timetable row data.", error);
            }
        } else if (action === "delete") {
            openDeleteConfirm(button.dataset.formId, button.dataset.label || "this timetable");
        }
    });
})();