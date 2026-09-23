(function () {
    document.addEventListener("DOMContentLoaded", () => {
        const button = document.getElementById("filterButton");
        const panel = document.getElementById("filterPanel");
        if (!button || !panel) return;

        button.addEventListener("click", (e) => {
            e.stopPropagation();
            panel.classList.toggle("open");
        });

        // Clicking inside the panel (e.g. the selects) shouldn't close it
        panel.addEventListener("click", (e) => e.stopPropagation());

        document.addEventListener("click", () => {
            panel.classList.remove("open");
        });

        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") panel.classList.remove("open");
        });
    });
})();