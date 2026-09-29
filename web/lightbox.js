// The war table lightbox: click any picture on a board page to see it large.
// Wheel, + and - zoom; drag pans; 0 fits it back; arrows move between pictures;
// F goes full screen; Esc or a click on the dark closes it.
(function () {
  var MIN_SIZE = 80;   // smaller images are icons or badges, not pictures
  var css = document.createElement("style");
  css.textContent =
    "img.gl-zoomable{cursor:zoom-in}" +
    ".gl-box{position:fixed;inset:0;z-index:99999;background:rgba(20,13,8,.92);display:none;overflow:hidden;user-select:none}" +
    ".gl-box.on{display:block}" +
    ".gl-box img{position:absolute;left:0;top:0;transform-origin:0 0;max-width:none;max-height:none;cursor:grab;box-shadow:0 10px 40px rgba(0,0,0,.6);background:#fff}" +
    ".gl-box img.drag{cursor:grabbing}" +
    ".gl-bar{position:absolute;top:10px;right:12px;display:flex;gap:6px;z-index:2}" +
    ".gl-bar button{font:13px/1 Georgia,serif;color:#f3e7c9;background:rgba(91,62,40,.85);border:1px solid #cdb88e;border-radius:4px;padding:7px 10px;cursor:pointer}" +
    ".gl-bar button:hover{background:#8a4b12}" +
    ".gl-cap{position:absolute;left:0;right:0;bottom:0;padding:10px 16px;color:#f3e7c9;font:14px/1.4 Georgia,serif;background:linear-gradient(transparent,rgba(0,0,0,.7));text-align:center;pointer-events:none}" +
    ".gl-nav{position:absolute;top:50%;transform:translateY(-50%);font:28px/1 Georgia,serif;color:#f3e7c9;background:rgba(91,62,40,.7);border:1px solid #cdb88e;border-radius:4px;padding:10px 12px;cursor:pointer;z-index:2}" +
    ".gl-prev{left:12px}.gl-next{right:12px}";
  document.head.appendChild(css);

  var box, pic, cap, pics = [], at = 0, scale = 1, x = 0, y = 0, drag = null;

  function build() {
    box = document.createElement("div");
    box.className = "gl-box";
    box.innerHTML =
      '<div class="gl-bar"><button data-a="out" title="Zoom out (-)">&minus;</button>' +
      '<button data-a="fit" title="Fit (0)">Fit</button><button data-a="real" title="Real size (1)">1:1</button>' +
      '<button data-a="in" title="Zoom in (+)">+</button><button data-a="full" title="Full screen (F)">Full screen</button>' +
      '<button data-a="close" title="Close (Esc)">&times;</button></div>' +
      '<button class="gl-nav gl-prev" data-a="prev" title="Previous">&lsaquo;</button>' +
      '<button class="gl-nav gl-next" data-a="next" title="Next">&rsaquo;</button>' +
      '<img alt=""><div class="gl-cap"></div>';
    document.body.appendChild(box);
    pic = box.querySelector("img");
    cap = box.querySelector(".gl-cap");
    box.addEventListener("click", function (e) {
      var a = e.target.getAttribute && e.target.getAttribute("data-a");
      if (a) { act(a); e.stopPropagation(); return; }
      if (e.target === box) close();
    });
    box.addEventListener("wheel", function (e) {
      e.preventDefault();
      zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY);
    }, { passive: false });
    pic.addEventListener("mousedown", function (e) {
      e.preventDefault();
      drag = { sx: e.clientX, sy: e.clientY, x: x, y: y };
      pic.classList.add("drag");
    });
    pic.addEventListener("dblclick", function (e) {
      if (scale < real() * 0.99) { var r = real() / scale; zoomAt(r, e.clientX, e.clientY); } else fit();
    });
    window.addEventListener("mousemove", function (e) {
      if (!drag) return;
      x = drag.x + e.clientX - drag.sx; y = drag.y + e.clientY - drag.sy; paint();
    });
    window.addEventListener("mouseup", function () { drag = null; pic && pic.classList.remove("drag"); });
    window.addEventListener("resize", function () { if (box.classList.contains("on")) fit(); });
    document.addEventListener("keydown", function (e) {
      if (!box.classList.contains("on")) return;
      var k = { Escape: "close", "+": "in", "=": "in", "-": "out", "0": "fit", "1": "real",
                f: "full", F: "full", ArrowLeft: "prev", ArrowRight: "next" }[e.key];
      if (k) { e.preventDefault(); act(k); }
    });
  }

  function real() { return 1; }
  function paint() { pic.style.transform = "translate(" + x + "px," + y + "px) scale(" + scale + ")"; }
  function zoomAt(f, cx, cy) {
    var s = Math.min(12, Math.max(0.05, scale * f));
    x = cx - (cx - x) * (s / scale); y = cy - (cy - y) * (s / scale); scale = s; paint();
  }
  function center() { return [box.clientWidth / 2, box.clientHeight / 2]; }
  function fit() {
    var w = pic.naturalWidth || 1, h = pic.naturalHeight || 1, pad = 40;
    scale = Math.min((box.clientWidth - pad * 2) / w, (box.clientHeight - pad * 2 - 30) / h, 4);
    x = (box.clientWidth - w * scale) / 2; y = (box.clientHeight - h * scale) / 2 - 10; paint();
  }
  function act(a) {
    var c = center();
    if (a === "close") close();
    else if (a === "in") zoomAt(1.25, c[0], c[1]);
    else if (a === "out") zoomAt(0.8, c[0], c[1]);
    else if (a === "fit") fit();
    else if (a === "real") zoomAt(real() / scale, c[0], c[1]);
    else if (a === "prev") show(at - 1);
    else if (a === "next") show(at + 1);
    else if (a === "full") {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (box.requestFullscreen) box.requestFullscreen().catch(function () {});
    }
  }
  function caption(img) {
    var fig = img.closest("figure");
    var fc = fig && fig.querySelector("figcaption");
    return (fc ? fc.innerText : img.alt || img.title || "").trim();
  }
  function show(i) {
    at = (i + pics.length) % pics.length;
    var img = pics[at];
    pic.onload = fit;
    pic.src = img.currentSrc || img.src;
    if (pic.complete) fit();
    cap.textContent = caption(img) + (pics.length > 1 ? "   (" + (at + 1) + " of " + pics.length + ")" : "");
    var many = pics.length > 1 ? "" : "none";
    box.querySelector(".gl-prev").style.display = many;
    box.querySelector(".gl-next").style.display = many;
  }
  function open(img) {
    if (!box) build();
    pics = [].filter.call(document.images, zoomable);
    box.classList.add("on");
    show(Math.max(0, pics.indexOf(img)));
  }
  function close() {
    if (document.fullscreenElement) document.exitFullscreen();
    box.classList.remove("on");
  }
  function zoomable(img) {
    if (box && box.contains(img)) return false;
    if (img.closest("a[href]")) return false;   // a linked image keeps its link
    return (img.naturalWidth || img.width) >= MIN_SIZE && (img.naturalHeight || img.height) >= MIN_SIZE;
  }

  function mark() { [].forEach.call(document.images, function (img) { if (zoomable(img)) img.classList.add("gl-zoomable"); }); }
  document.addEventListener("click", function (e) {
    var img = e.target.closest && e.target.closest("img");
    if (img && zoomable(img)) { e.preventDefault(); open(img); }
  });
  window.addEventListener("load", mark);
  document.addEventListener("DOMContentLoaded", mark);
})();
