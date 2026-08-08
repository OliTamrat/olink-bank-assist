/* The one-line install for the website widget.
 *
 *   <script src="https://…/embed.js" data-bank="cbe" defer></script>
 *
 * Everything here runs on a bank's own production pages, which sets the rules:
 *
 * - No globals beyond one guard, no styles applied to anything the page owns,
 *   and every element namespaced. A widget that restyles its host is a widget
 *   that gets removed.
 * - The chat itself is an iframe, so the bank's CSS cannot reach into it and
 *   ours cannot leak out. It also means the panel inherits none of the host's
 *   font or colour accidents.
 * - The launcher is a real <button> with an aria-label and a focus ring. It is
 *   often the only interactive thing added to the page, and a div that opens a
 *   chat is invisible to a keyboard.
 * - It loads the iframe on FIRST OPEN, not on page load. Most visitors never
 *   open the chat, and making every one of them fetch it would be a tax on the
 *   bank's own page speed for a feature they did not use.
 */
(function () {
  "use strict";
  if (window.__olinkBankAssistLoaded) return;   // two copies of the tag = one widget
  window.__olinkBankAssistLoaded = true;

  var script = document.currentScript;
  if (!script) return;
  var bank = script.getAttribute("data-bank");
  if (!bank) {
    // Loud, because the failure is otherwise a widget that simply never
    // appears and a bank that concludes the product does not work.
    if (window.console) console.error("[bank-assist] embed.js needs data-bank");
    return;
  }
  var origin = new URL(script.src, window.location.href).origin;
  var side = script.getAttribute("data-side") === "left" ? "left" : "right";
  var color = script.getAttribute("data-color") || "#0f766e";

  var css = document.createElement("style");
  css.textContent =
    ".olink-ba-btn{position:fixed;bottom:20px;" + side + ":20px;z-index:2147483000;" +
    "width:56px;height:56px;border-radius:50%;border:none;cursor:pointer;" +
    "background:" + color + ";color:#fff;box-shadow:0 6px 20px rgba(0,0,0,.25);" +
    "display:grid;place-items:center;padding:0;transition:transform .15s}" +
    ".olink-ba-btn:hover{transform:scale(1.06)}" +
    ".olink-ba-btn:focus-visible{outline:3px solid #fff;outline-offset:2px}" +
    ".olink-ba-panel{position:fixed;bottom:88px;" + side + ":20px;z-index:2147483000;" +
    "width:390px;max-width:calc(100vw - 32px);height:620px;max-height:calc(100vh - 120px);" +
    "border:none;border-radius:16px;box-shadow:0 18px 60px rgba(0,0,0,.3);" +
    "background:#fff;display:none}" +
    ".olink-ba-panel.open{display:block}" +
    /* On a phone the panel is the screen. A 390px card floating over a 360px
       viewport is how a widget becomes unusable on the device most Ethiopian
       customers will be holding. */
    "@media (max-width:480px){.olink-ba-panel{bottom:0;left:0;right:0;top:0;" +
    "width:100%;height:100%;max-width:none;max-height:none;border-radius:0}}";
  document.head.appendChild(css);

  var btn = document.createElement("button");
  btn.className = "olink-ba-btn";
  btn.type = "button";
  btn.setAttribute("aria-label", "Chat with us");
  btn.setAttribute("aria-expanded", "false");
  btn.innerHTML =
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"' +
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4L3 21l1.1-4.6A8.4 8.4 0 1 1 21 11.5z"/></svg>';

  var frame = null;
  var open = false;

  function toggle() {
    if (!frame) {
      // First open only — see the note at the top about page speed.
      frame = document.createElement("iframe");
      frame.className = "olink-ba-panel";
      frame.title = "Chat with us";
      frame.src = origin + "/widget?bank=" + encodeURIComponent(bank);
      document.body.appendChild(frame);
      // Next frame, so the element is in the document before .open is added
      // and the browser has something to transition from.
      requestAnimationFrame(function () { frame.classList.add("open"); });
      open = true;
    } else {
      open = !open;
      frame.classList.toggle("open", open);
    }
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  btn.addEventListener("click", toggle);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && open) { toggle(); btn.focus(); }
  });

  function mount() { document.body.appendChild(btn); }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
