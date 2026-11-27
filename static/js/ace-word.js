/* ACE report cards -> editable Word (.docx).
   Same technique as the Primary "Download as Word": the document is written
   as WordprocessingML and packed into a zip in the browser, so no extra
   libraries or server code are needed. The data is read from the hidden
   .ace-report-page cards already on the page, so the Word file always matches
   the preview/PDF. Logo and signatures are embedded as PNG images. */
(function () {
    "use strict";

    const WX = (s) => String(s ?? "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")
        .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
    const F_SERIF = "Times New Roman", F_SANS = "Arial", F_HAND = "Comic Sans MS", F_GEORGIA = "Georgia";
    const AREA_FILL = {
        "maths": "F7C142", "english": "EE3124", "social-studies": "4F5B2E", "word-building": "5B4678",
        "science": "5C85B9", "animal-science": "B0A4C8", "literature-and-creative-writing": "B0A4C8",
        "bible-reading": "8F6521",
    };
    let drawingId = 0;

    /* ---------- WordprocessingML helpers ---------- */
    function run(text, o = {}) {
        const f = o.font || F_SERIF;
        const sz = Math.round((o.size || 10) * 2);
        const pr = `<w:rFonts w:ascii="${f}" w:hAnsi="${f}" w:cs="${f}"/>`
            + (o.b ? "<w:b/>" : "") + (o.i ? "<w:i/>" : "")
            + (o.color ? `<w:color w:val="${o.color}"/>` : "")
            + `<w:sz w:val="${sz}"/><w:szCs w:val="${sz}"/>`
            + (o.u ? '<w:u w:val="single"/>' : "")
            + (o.fill ? `<w:shd w:val="clear" w:color="auto" w:fill="${o.fill}"/>` : "");
        return `<w:r><w:rPr>${pr}</w:rPr><w:t xml:space="preserve">${WX(text)}</w:t></w:r>`;
    }

    function para(inner, o = {}) {
        const pr = (o.pageBreakBefore ? "<w:pageBreakBefore/>" : "")
            + `<w:spacing w:before="${o.before || 0}" w:after="${o.after || 0}"${o.line ? ` w:line="${o.line}" w:lineRule="${o.lineRule || "auto"}"` : ""}/>`
            + (o.align ? `<w:jc w:val="${o.align}"/>` : "");
        return `<w:p><w:pPr>${pr}</w:pPr>${inner || ""}</w:p>`;
    }

    function image(img, maxW, maxH) {
        if (!img) return "";
        const r = Math.min(maxW / img.w, maxH / img.h, 1);
        const cx = Math.round(img.w * r * 9525), cy = Math.round(img.h * r * 9525);
        const id = ++drawingId;
        return `<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="${cx}" cy="${cy}"/>`
            + `<wp:docPr id="${id}" name="Picture ${id}"/><wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>`
            + `<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>`
            + `<pic:nvPicPr><pic:cNvPr id="${id}" name="${WX(img.file)}"/><pic:cNvPicPr/></pic:nvPicPr>`
            + `<pic:blipFill><a:blip r:embed="${img.rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>`
            + `<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="${cx}" cy="${cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>`
            + `</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>`;
    }

    // b: border size (eighths of a point) for { top, left, bottom, right }
    function cell(paras, o = {}) {
        const side = (n, v) => (v ? `<w:${n} w:val="single" w:sz="${v}" w:space="0" w:color="111111"/>` : "");
        const b = o.b || {};
        const borders = (b.top || b.left || b.bottom || b.right)
            ? `<w:tcBorders>${side("top", b.top)}${side("left", b.left)}${side("bottom", b.bottom)}${side("right", b.right)}</w:tcBorders>` : "";
        const pr = `<w:tcW w:w="${o.w}" w:type="dxa"/>`
            + (o.span ? `<w:gridSpan w:val="${o.span}"/>` : "")
            + borders
            + (o.fill ? `<w:shd w:val="clear" w:color="auto" w:fill="${o.fill}"/>` : "")
            + `<w:vAlign w:val="${o.va || "center"}"/>`;
        return `<w:tc><w:tcPr>${pr}</w:tcPr>${paras || "<w:p/>"}</w:tc>`;
    }

    function row(cells, height) {
        return `<w:tr><w:trPr><w:cantSplit/>${height ? `<w:trHeight w:val="${height}" w:hRule="atLeast"/>` : ""}</w:trPr>${cells.join("")}</w:tr>`;
    }

    function table(widths, rows) {
        const total = widths.reduce((a, c) => a + c, 0);
        return `<w:tbl><w:tblPr><w:tblW w:w="${total}" w:type="dxa"/><w:tblLayout w:type="fixed"/>`
            + `<w:tblCellMar><w:top w:w="20" w:type="dxa"/><w:left w:w="70" w:type="dxa"/><w:bottom w:w="20" w:type="dxa"/><w:right w:w="70" w:type="dxa"/></w:tblCellMar></w:tblPr>`
            + `<w:tblGrid>${widths.map((w) => `<w:gridCol w:w="${w}"/>`).join("")}</w:tblGrid>${rows.join("")}</w:tbl>`;
    }

    const gap = (twips) => para("", { line: twips, lineRule: "exact" });

    /* ---------- read one on-screen ACE card ---------- */
    function readCard(node) {
        const q = (s) => node.querySelector(s);
        const clean = (el) => (el ? el.textContent.replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim() : "");
        const fills = (sel) => Array.from(node.querySelectorAll(`${sel} .fill`)).map(clean);
        const [name = "", age = ""] = fills(".name-row");
        const [grade = "", term = "", year = ""] = fills(".term-row");

        const head = Array.from(node.querySelectorAll(".ace-card-head-text p")).map(clean).filter(Boolean);
        const spanTh = q(".ace-card-table thead th[colspan]");
        const paceCols = spanTh ? (Number(spanTh.getAttribute("colspan")) || 9) : 9;

        const areas = [];
        const trs = Array.from(node.querySelectorAll(".ace-card-table tbody tr"));
        for (let i = 0; i + 1 < trs.length; i += 2) {
            const top = trs[i], bottom = trs[i + 1];
            const m = /ace-area-([a-z-]+)/.exec(top.className || "");
            areas.push({
                key: m ? m[1] : "",
                label: clean(top.querySelector(".ace-label")),
                paces: Array.from(top.querySelectorAll(".ace-pace-no")).map(clean),
                scores: Array.from(bottom.querySelectorAll(".ace-pace-score")).map(clean),
            });
        }

        const notes = Array.from(node.querySelectorAll(".ace-card-note-text")).map(clean);
        const signs = Array.from(node.querySelectorAll(".ace-card-sign-line")).map((el) => {
            const img = el.querySelector("img");
            return img ? img.src : "";
        });
        const next = Array.from(node.querySelectorAll(".ace-card-next span")).map((el) => {
            const b = el.querySelector("b");
            const value = clean(b);
            return { label: clean(el).replace(value, "").trim(), value };
        });

        return {
            logo: (q(".ace-card-logo") || {}).src || "",
            head,
            title: clean(q(".ace-card-title span")),
            name, age, grade, term, year, paceCols, areas,
            supervisorReport: notes[0] || "", principalReport: notes[1] || "",
            supervisorSig: signs[0] || "", principalSig: signs[1] || "",
            next, tagline: clean(q(".ace-card-tagline")),
        };
    }

    /* ---------- build one A4 page ---------- */
    function cardPage(d, imgs, pageBreak) {
        const T = 10200; // text width in twips (A4 minus margins)
        const out = [];
        if (pageBreak) out.push(para("", { pageBreakBefore: true, line: 20, lineRule: "exact" }));

        // Header: school name / address / phone, logo on the left.
        const headText = d.head.map((line, i) => para(run(line, { b: true, size: i === 0 ? 20 : 11 }), { align: "center", after: i === 0 ? 60 : 0 })).join("");
        out.push(imgs.logo
            ? table([2000, T - 4000, 2000], [row([
                cell(para(image(imgs.logo, 110, 90), { align: "left" }), { w: 2000 }),
                cell(headText, { w: T - 4000 }),
                cell(para(""), { w: 2000 }),
            ])])
            : table([T], [row([cell(headText, { w: T })])]));

        out.push(para(run(` ${d.title} `, { b: true, size: 15, fill: "000000", color: "FFFFFF" }), { align: "center", before: 240, after: 240 }));

        // Name / age, then grade / term / year.
        const lab = (txt, w) => cell(para(run(txt, { b: true, size: 11, font: F_SANS })), { w, va: "bottom" });
        const fill = (txt, w) => cell(para(run(txt, { b: true, size: 12 }), { align: "left" }), { w, va: "bottom", b: { bottom: 8 } });
        out.push(table([1100, 7300, 800, 1000], [row([lab("NAME", 1100), fill(d.name, 7300), lab("AGE", 800), fill(d.age, 1000)], 380)]));
        out.push(gap(60));
        out.push(table([1100, 4100, 900, 1500, 900, 1700], [row([
            lab("GRADE", 1100), fill(d.grade, 4100), lab("TERM", 900), fill(d.term, 1500), lab("YEAR", 900), fill(d.year, 1700),
        ], 380)]));
        out.push(gap(200));

        // Marks table: two rows per learning area (PACE numbers, then scores).
        const n = d.paceCols;
        const wLabel = 2860, wInit = 1120;
        const wPace = Math.floor((T - wLabel - wInit) / n);
        const widths = [wLabel, ...Array(n).fill(wPace), T - wLabel - wPace * n];
        const all = { top: 8, left: 8, bottom: 8, right: 8 };
        const headCell = (txt, w, span) => cell(para(run(txt, { b: true, size: 10.5, font: F_SANS }), { align: "center" }), { w, span, b: all });
        const rows = [row([headCell("LEARNING AREAS", wLabel), headCell("PACE NUMBER AND SCORES", wPace * n, n), headCell("INITIALS", widths[n + 1])], 420)];
        d.areas.forEach((a) => {
            const bg = AREA_FILL[a.key] || "FFFFFF";
            const r1 = [cell(para(run(a.label.toUpperCase(), { b: true, size: 10, font: F_SANS })), { w: wLabel, fill: bg, b: all })];
            const r2 = [cell(para(""), { w: wLabel, b: all })];
            for (let i = 0; i < n; i += 1) {
                r1.push(cell(para(run(a.paces[i] || "", { b: true, size: 10.5, font: F_SANS }), { align: "center" }), { w: wPace, b: all }));
                r2.push(cell(para(run(a.scores[i] || "", { b: true, size: 10.5, font: F_SANS, color: "E8281E" }), { align: "center" }), { w: wPace, b: all }));
            }
            r1.push(cell(para(""), { w: widths[n + 1], b: all }));
            r2.push(cell(para(""), { w: widths[n + 1], b: all }));
            rows.push(row(r1, 450), row(r2, 450));
        });
        out.push(table(widths, rows));
        out.push(gap(240));

        // Supervisor's / Principal's report + signature lines.
        const reportBlock = (label, text, sig) => {
            const body = text
                ? run(` ${text}`, { font: F_HAND, size: 12, u: true })
                : run(` ${"_".repeat(62)}`, { font: F_SANS, size: 11 });
            out.push(para(run(label, { font: F_HAND, b: true, size: 12 }) + body, { line: 340, lineRule: "auto", after: 60 }));
            out.push(table([1300, T - 1300], [row([
                cell(para(run("Signature:", { b: true, size: 11, font: F_SANS })), { w: 1300, va: "bottom" }),
                cell(sig ? para(image(sig, 220, 44), { align: "center" }) : para(""), { w: T - 1300, va: "bottom", b: { bottom: 12 } }),
            ], 760)]));
            out.push(gap(160));
        };
        reportBlock("Supervisor's Report:", d.supervisorReport, imgs.supervisorSig);
        reportBlock("Principal's Report:", d.principalReport, imgs.principalSig);

        // Footer: next-term dates + school motto.
        if (d.next.length) {
            out.push(para(d.next.map((x, i) => run(`${i ? "      " : ""}${x.label} `, { size: 11 }) + run(x.value, { b: true, u: true, size: 11 })).join(""), { align: "center", before: 120, after: 80 }));
        }
        if (d.tagline) out.push(para(run(d.tagline, { font: F_GEORGIA, b: true, i: true, size: 13, color: "5B8FD0" }), { align: "center" }));
        return out.join("");
    }

    /* ---------- zip + docx packaging ---------- */
    let crcTable = null;
    function crc32(bytes) {
        if (!crcTable) {
            crcTable = new Uint32Array(256);
            for (let n = 0; n < 256; n += 1) {
                let c = n;
                for (let k = 0; k < 8; k += 1) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
                crcTable[n] = c >>> 0;
            }
        }
        let crc = 0xFFFFFFFF;
        for (let i = 0; i < bytes.length; i += 1) crc = crcTable[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
        return (crc ^ 0xFFFFFFFF) >>> 0;
    }

    function zipStore(files, mime) {
        const enc = new TextEncoder();
        const chunks = [], central = [];
        let offset = 0;
        files.forEach((f) => {
            const name = enc.encode(f.name);
            const crc = crc32(f.data);
            const size = f.data.length;
            const lh = new Uint8Array(30 + name.length);
            const lv = new DataView(lh.buffer);
            lv.setUint32(0, 0x04034b50, true); lv.setUint16(4, 20, true); lv.setUint16(6, 0x0800, true);
            lv.setUint16(8, 0, true); lv.setUint16(10, 0, true); lv.setUint16(12, 0x21, true);
            lv.setUint32(14, crc, true); lv.setUint32(18, size, true); lv.setUint32(22, size, true);
            lv.setUint16(26, name.length, true); lv.setUint16(28, 0, true);
            lh.set(name, 30);
            chunks.push(lh, f.data);
            const ch = new Uint8Array(46 + name.length);
            const cv = new DataView(ch.buffer);
            cv.setUint32(0, 0x02014b50, true); cv.setUint16(4, 20, true); cv.setUint16(6, 20, true); cv.setUint16(8, 0x0800, true);
            cv.setUint16(10, 0, true); cv.setUint16(12, 0, true); cv.setUint16(14, 0x21, true);
            cv.setUint32(16, crc, true); cv.setUint32(20, size, true); cv.setUint32(24, size, true);
            cv.setUint16(28, name.length, true);
            cv.setUint32(42, offset, true);
            ch.set(name, 46);
            central.push(ch);
            offset += lh.length + size;
        });
        const cdSize = central.reduce((a, c) => a + c.length, 0);
        const eocd = new Uint8Array(22);
        const ev = new DataView(eocd.buffer);
        ev.setUint32(0, 0x06054b50, true); ev.setUint16(8, files.length, true); ev.setUint16(10, files.length, true);
        ev.setUint32(12, cdSize, true); ev.setUint32(16, offset, true);
        return new Blob([...chunks, ...central, eocd], { type: mime });
    }

    function buildDocx(bodyXml, images) {
        const enc = new TextEncoder();
        const NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            + 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            + 'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
            + 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            + 'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"';
        const head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
        const documentXml = `${head}<w:document ${NS}><w:body>${bodyXml}`
            + `<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="680" w:right="850" w:bottom="680" w:left="850" w:header="400" w:footer="400" w:gutter="0"/></w:sectPr>`
            + `</w:body></w:document>`;
        const contentTypes = `${head}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">`
            + `<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>`
            + `<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>`
            + `<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>`;
        const rootRels = `${head}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`
            + `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>`;
        const docRels = `${head}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`
            + images.map((im) => `<Relationship Id="${im.rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="${im.file}"/>`).join("")
            + `</Relationships>`;
        const b64ToBytes = (b64) => {
            const bin = atob(b64);
            const bytes = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
            return bytes;
        };
        return zipStore([
            { name: "[Content_Types].xml", data: enc.encode(contentTypes) },
            { name: "_rels/.rels", data: enc.encode(rootRels) },
            { name: "word/document.xml", data: enc.encode(documentXml) },
            { name: "word/_rels/document.xml.rels", data: enc.encode(docRels) },
            ...images.map((im) => ({ name: `word/${im.file}`, data: b64ToBytes(im.base64) })),
        ], "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
    }

    /* ---------- images (browser only) ---------- */
    function loadImageElement(src) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => resolve(img);
            img.onerror = reject;
            img.src = src;
        });
    }

    // Fetch an image and convert it to PNG so Word can always read it.
    async function imageUrlToPng(url) {
        if (!url) return null;
        try {
            const resp = await fetch(url, { credentials: "same-origin" });
            if (!resp.ok) return null;
            const objectUrl = URL.createObjectURL(await resp.blob());
            try {
                const img = await loadImageElement(objectUrl);
                const width = img.naturalWidth || 300, height = img.naturalHeight || 200;
                const scale = Math.min(1, 700 / Math.max(width, height));
                const w = Math.max(1, Math.round(width * scale)), h = Math.max(1, Math.round(height * scale));
                const canvas = document.createElement("canvas");
                canvas.width = w; canvas.height = h;
                canvas.getContext("2d").drawImage(img, 0, 0, w, h);
                return { base64: canvas.toDataURL("image/png").split(",")[1], w, h };
            } finally {
                URL.revokeObjectURL(objectUrl);
            }
        } catch (error) {
            return null;
        }
    }

    /* ---------- public entry point ---------- */
    async function download(pageNodes, filenameBase, button) {
        if (button && button.disabled) return;
        if (!pageNodes || !pageNodes.length) { alert("There is no report content to download."); return; }

        const originalIcon = button ? button.innerHTML : "";
        if (button) { button.disabled = true; button.innerHTML = '<i class="ti ti-loader-2"></i>'; }
        try {
            const images = [];
            const cache = {};
            drawingId = 0;
            const register = async (url) => {
                if (!url) return undefined;
                if (!(url in cache)) {
                    const png = await imageUrlToPng(url);
                    if (png) {
                        const n = images.length + 1;
                        const img = { rid: `rIdImg${n}`, file: `media/image${n}.png`, base64: png.base64, w: png.w, h: png.h };
                        images.push(img);
                        cache[url] = img;
                    } else {
                        cache[url] = undefined;
                    }
                }
                return cache[url];
            };

            let body = "";
            for (let i = 0; i < pageNodes.length; i += 1) {
                const card = readCard(pageNodes[i]);
                const imgs = {
                    logo: await register(card.logo),
                    supervisorSig: await register(card.supervisorSig),
                    principalSig: await register(card.principalSig),
                };
                body += cardPage(card, imgs, i > 0);
            }

            const url = URL.createObjectURL(buildDocx(body, images));
            const link = document.createElement("a");
            link.href = url;
            link.download = `${filenameBase || "ace-report"}.docx`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(url), 120000);
        } catch (error) {
            console.error("Could not generate ACE Word report:", error);
            alert("Something went wrong generating the Word document. Please try again.");
        } finally {
            if (button) { button.disabled = false; button.innerHTML = originalIcon; }
        }
    }

    window.AceWord = { download };
})();