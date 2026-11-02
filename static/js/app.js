document.addEventListener("DOMContentLoaded", function () {
    "use strict";

    // ---- Mensajes flash: se ocultan solos (excepto errores) ----
    document.querySelectorAll(".flash-messages .alert").forEach(function (alert) {
        if (alert.classList.contains("alert-danger")) return;
        setTimeout(function () {
            alert.style.transition = "opacity 0.5s";
            alert.style.opacity = "0";
            setTimeout(function () { alert.remove(); }, 500);
        }, 5000);
    });

    // ---- Menu lateral en movil ----
    var toggle = document.getElementById("menuToggle");
    if (toggle) {
        toggle.addEventListener("click", function (e) {
            e.stopPropagation();
            document.body.classList.toggle("nav-open");
        });
        document.addEventListener("click", function (e) {
            var sb = document.getElementById("sidebar");
            if (document.body.classList.contains("nav-open") && sb && !sb.contains(e.target)) {
                document.body.classList.remove("nav-open");
            }
        });
    }

    // ---- Dialogos: <button data-dialog="id"> abre <dialog id="id"> ----
    document.querySelectorAll("[data-dialog]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var dlg = document.getElementById(btn.getAttribute("data-dialog"));
            if (!dlg) return;
            // Rellena campos del formulario con data-fill-* (para editar registros)
            Object.keys(btn.dataset).forEach(function (k) {
                if (k.indexOf("fill") !== 0) return;
                var campo = k.slice(4).replace(/^[A-Z]/, function (c) { return c.toLowerCase(); })
                    .replace(/[A-Z]/g, function (c) { return "_" + c.toLowerCase(); });
                var input = dlg.querySelector('[name="' + campo + '"]');
                if (input) input.value = btn.dataset[k];
            });
            if (btn.dataset.action) {
                var form = dlg.querySelector("form");
                if (form) form.action = btn.dataset.action;
            }
            if (btn.dataset.title) {
                var h = dlg.querySelector(".dlg-head h3");
                if (h) h.textContent = btn.dataset.title;
            }
            if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
        });
    });
    document.querySelectorAll("dialog [data-close]").forEach(function (btn) {
        btn.addEventListener("click", function () { btn.closest("dialog").close(); });
    });

    // ---- Confirmacion antes de acciones destructivas ----
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
        form.addEventListener("submit", function (e) {
            if (!window.confirm(form.getAttribute("data-confirm"))) e.preventDefault();
        });
    });

    // ---- Filtro rapido de tablas: <input data-filter="tablaId"> ----
    document.querySelectorAll("input[data-filter]").forEach(function (input) {
        var tabla = document.getElementById(input.getAttribute("data-filter"));
        if (!tabla) return;
        input.addEventListener("input", function () {
            var q = input.value.trim().toLowerCase();
            tabla.querySelectorAll("tbody tr").forEach(function (tr) {
                tr.style.display = !q || tr.textContent.toLowerCase().indexOf(q) !== -1 ? "" : "none";
            });
        });
    });

    // ---- Evita doble envio de formularios ----
    document.querySelectorAll("form").forEach(function (form) {
        form.addEventListener("submit", function (e) {
            if (e.defaultPrevented || form.dataset.noLock !== undefined || form.target === "_blank") return;
            setTimeout(function () {
                form.querySelectorAll('button[type="submit"]').forEach(function (b) { b.disabled = true; });
            }, 0);
        });
    });

    // ---- Selector de semestre (gestion) ----
    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute("content") : "";
    }
    var trigger = document.getElementById("semesterTrigger");
    var selector = document.getElementById("semesterSelector");
    var dropdown = document.getElementById("semesterDropdown");
    var list = document.getElementById("semesterList");
    var createBtn = document.getElementById("semesterCreateBtn");
    if (!trigger || !selector) return;

    trigger.addEventListener("click", function (e) {
        e.stopPropagation();
        selector.classList.toggle("open");
        if (selector.classList.contains("open")) loadSemestres();
    });
    document.addEventListener("click", function (e) {
        if (!selector.contains(e.target)) selector.classList.remove("open");
    });
    dropdown.addEventListener("click", function (e) { e.stopPropagation(); });

    function loadSemestres() {
        fetch("/api/semestres", { headers: { "X-CSRFToken": getCsrfToken() } })
            .then(function (r) { return r.json(); })
            .then(function (semestres) {
                list.innerHTML = "";
                if (!semestres.length) {
                    list.innerHTML = '<div class="semester-list-empty">No hay semestres creados</div>';
                    return;
                }
                semestres.forEach(function (s) {
                    var btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "semester-list-item" + (s.actual ? " active" : "");
                    var etiqueta = document.createElement("span");
                    etiqueta.textContent = s.codigo + (s.activo ? "  (vigente)" : "");
                    btn.appendChild(etiqueta);
                    if (s.actual) {
                        var check = document.createElement("span");
                        check.className = "check";
                        check.textContent = "✓";
                        btn.appendChild(check);
                    }
                    btn.addEventListener("click", function () { cambiarSemestre(s.id); });
                    list.appendChild(btn);
                });
            });
    }

    function cambiarSemestre(id) {
        fetch("/api/cambiar-semestre", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
            body: JSON.stringify({ semestre_id: id })
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.ok) window.location.reload();
        });
    }

    var overlay = document.getElementById("modalOverlay");
    var errorEl = document.getElementById("modalError");
    function closeModal() { if (overlay) overlay.style.display = "none"; }
    if (createBtn && overlay) {
        createBtn.addEventListener("click", function () {
            selector.classList.remove("open");
            overlay.style.display = "flex";
            if (errorEl) errorEl.style.display = "none";
        });
        document.getElementById("modalClose").addEventListener("click", closeModal);
        document.getElementById("modalCancel").addEventListener("click", closeModal);
        overlay.addEventListener("click", function (e) { if (e.target === overlay) closeModal(); });
        document.getElementById("modalSubmit").addEventListener("click", function () {
            errorEl.style.display = "none";
            fetch("/api/crear-semestre", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
                body: JSON.stringify({
                    anio: document.getElementById("modalAnio").value,
                    periodo: document.getElementById("modalPeriodo").value
                })
            }).then(function (r) { return r.json(); }).then(function (data) {
                if (data.ok) { window.location.reload(); return; }
                errorEl.textContent = data.error || "No se pudo crear el semestre";
                errorEl.style.display = "block";
            });
        });
    }
});
