(function () {
  "use strict";

  const transcript = document.getElementById("transcript");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("send-btn");

  // ── Helpers ──────────────────────────────────────────────────────────────

  function appendBubble(text, role) {
    const row = document.createElement("div");
    row.className = `bubble-row ${role}`;

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;

    row.appendChild(bubble);
    transcript.appendChild(row);
    transcript.scrollTop = transcript.scrollHeight;
  }

  function appendStatus(text) {
    const el = document.createElement("div");
    el.className = "status-msg";
    el.id = "status-msg";
    el.textContent = text;
    transcript.appendChild(el);
    transcript.scrollTop = transcript.scrollHeight;
    return el;
  }

  function removeStatus() {
    const el = document.getElementById("status-msg");
    if (el) el.remove();
  }

  function setUiBusy(busy) {
    input.disabled = busy;
    sendBtn.disabled = busy;
  }

  // ── Bridge readiness ──────────────────────────────────────────────────────

  /**
   * Resolves once window.pywebview.api is available.
   * Polls every 100 ms; gives up after 10 seconds.
   */
  function waitForBridge() {
    return new Promise((resolve, reject) => {
      const deadline = Date.now() + 10_000;

      function check() {
        if (window.pywebview && window.pywebview.api) {
          resolve(window.pywebview.api);
        } else if (Date.now() > deadline) {
          reject(new Error("pywebview bridge not available"));
        } else {
          setTimeout(check, 100);
        }
      }

      check();
    });
  }

  // ── Send logic ────────────────────────────────────────────────────────────

  async function sendMessage() {
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    appendBubble(text, "user");
    setUiBusy(true);

    const connectingEl = appendStatus("Connecting…");

    let api;
    try {
      api = await waitForBridge();
      removeStatus();
    } catch (_err) {
      connectingEl.textContent = "⚠️ Could not connect to Clippy bridge.";
      setUiBusy(false);
      return;
    }

    try {
      const response = await api.send_message(text);
      appendBubble(response, "assistant");
    } catch (err) {
      appendBubble("⚠️ Something went wrong. Please try again.", "assistant");
      console.error("Bridge error:", err);
    } finally {
      setUiBusy(false);
      input.focus();
    }
  }

  // ── Event wiring ──────────────────────────────────────────────────────────

  sendBtn.addEventListener("click", sendMessage);

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  input.focus();
})();
