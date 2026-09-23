// Powers the term switcher in the header (#termSwitcher):
//   1. The plain "Change term" <select> + "Save and Switch" button — a normal
//      server-rendered form, this file just needs to not get in its way.
//   2. The "Set term dates" year grid below it, which lets someone create or
//      edit a term's start/end dates without ever touching the database by
//      hand. Term data comes from window.ALL_TERMS (set in base.html from the
//      real Term table), and saving posts to /terms/dates.
(function () {
    document.addEventListener("DOMContentLoaded", () => {
        const switcher = document.getElementById("termSwitcher");
        const button = document.getElementById("termButton");
        const menu = document.getElementById("termMenu");
        const yearLabel = document.getElementById("termYearLabel");
        const optionsWrap = document.getElementById("termMenuOptions");
        const prevBtn = document.getElementById("termYearPrev");
        const nextBtn = document.getElementById("termYearNext");

        if (!switcher || !button || !menu) return;

        // Clicks anywhere inside the switcher (select, date-grid, modal
        // trigger) shouldn't bubble to the document listener below, or
        // interacting with the menu would close it before the click lands.
        switcher.addEventListener("click", (e) => e.stopPropagation());
        button.addEventListener("click", () => menu.classList.toggle("open"));
        document.addEventListener("click", () => menu.classList.remove("open"));

        if (!yearLabel || !optionsWrap || !prevBtn || !nextBtn) return;

        const terms = window.ALL_TERMS || [];
        const currentTermId = window.CURRENT_TERM_ID;

        let viewYear = new Date().getFullYear();
        const activeTerm = terms.find((t) => t.id === currentTermId);
        if (activeTerm) viewYear = activeTerm.year;

        function termFor(year, number) {
            return terms.find((t) => t.year === year && t.term_number === number);
        }

        function render() {
            yearLabel.textContent = viewYear;
            optionsWrap.innerHTML = "";

            [1, 2, 3].forEach((number) => {
                const term = termFor(viewYear, number);
                const isActive = term && term.id === currentTermId;

                const option = document.createElement("button");
                option.type = "button";
                option.className = "term-option" + (isActive ? " term-option-active" : "");
                option.innerHTML = `
                    <span class="term-option-name">Term ${number}${isActive ? " · Current" : ""}</span>
                    <span class="term-option-dates">${term ? `${term.start} – ${term.end}` : "Not set — click to add dates"}</span>
                `;
                option.addEventListener("click", () => openTermDatesModal(viewYear, number, term));
                optionsWrap.appendChild(option);
            });
        }

        function openTermDatesModal(year, number, existingTerm) {
            document.getElementById("termDatesTitle").textContent = `Term ${number}, ${year}`;
            document.getElementById("termDatesYear").value = year;
            document.getElementById("termDatesNumber").value = number;
            document.getElementById("termDatesStart").value = existingTerm ? existingTerm.start : "";
            document.getElementById("termDatesEnd").value = existingTerm ? existingTerm.end : "";
            menu.classList.remove("open");
            openModal("termDatesModal");
        }

        prevBtn.addEventListener("click", () => {
            viewYear -= 1;
            render();
        });

        nextBtn.addEventListener("click", () => {
            viewYear += 1;
            render();
        });

        render();
    });
})();