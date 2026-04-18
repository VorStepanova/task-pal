(function () {
  "use strict";

  const transcript = document.getElementById("transcript");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("send-btn");
  const newChatBtn = document.getElementById("new-chat-btn");

  // ── Helpers ──────────────────────────────────────────────────────────────

  function renderMarkdown(text) {
    var escaped = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    // Bold: **text**
    escaped = escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    // Italic: *text* (but not inside bold)
    escaped = escaped.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, "<em>$1</em>");
    // Inline code: `text`
    escaped = escaped.replace(/`([^`]+)`/g, "<code>$1</code>");
    // Bullet lines: - text or * text at start of line
    escaped = escaped.replace(/^[\-\*]\s+(.+)$/gm, "<li>$1</li>");
    escaped = escaped.replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");
    // Line breaks
    escaped = escaped.replace(/\n/g, "<br>");
    return escaped;
  }

  function createReminderButtons(label) {
    const btnRow = document.createElement("div");
    btnRow.className = "action-btn-row";

    function selectButton(chosen) {
      btnRow.querySelectorAll("button").forEach(function (b) {
        b.disabled = true;
        if (b !== chosen) {
          b.classList.add("btn-faded");
        }
      });
      chosen.classList.add("btn-selected");
    }

    const doneBtn = document.createElement("button");
    doneBtn.className = "ack-btn";
    doneBtn.textContent = "✓ Done";
    doneBtn.addEventListener("click", async function () {
      selectButton(doneBtn);
      doneBtn.classList.add("btn-done");
      try {
        const api = await waitForBridge();
        await api.acknowledge_reminder(label);
      } catch (e) {
        console.error("Ack error:", e);
      }
    });

    const notTodayBtn = document.createElement("button");
    notTodayBtn.className = "action-btn";
    notTodayBtn.textContent = "Not today";
    notTodayBtn.addEventListener("click", async function () {
      selectButton(notTodayBtn);
      try {
        const api = await waitForBridge();
        await api.dismiss_reminder(label);
      } catch (e) {
        console.error("Dismiss error:", e);
      }
    });

    const snoozeBtn = document.createElement("button");
    snoozeBtn.className = "action-btn";
    snoozeBtn.textContent = "Snooze 1h";
    snoozeBtn.addEventListener("click", async function () {
      selectButton(snoozeBtn);
      try {
        const api = await waitForBridge();
        await api.snooze_reminder(label, 1);
      } catch (e) {
        console.error("Snooze error:", e);
      }
    });

    btnRow.appendChild(doneBtn);
    btnRow.appendChild(notTodayBtn);
    btnRow.appendChild(snoozeBtn);
    return btnRow;
  }

  function appendBubble(text, role) {
    const row = document.createElement("div");
    row.className = `bubble-row ${role}`;

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (role === "assistant") {
      bubble.innerHTML = renderMarkdown(text);
    } else {
      bubble.textContent = text;
    }

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

  function autoResize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  }

  async function startNewChat() {
    let api;
    try {
      api = await waitForBridge();
    } catch (_err) {
      return;
    }
    try {
      await api.new_chat();
      while (transcript.firstChild) {
        transcript.removeChild(transcript.firstChild);
      }
    } catch (err) {
      console.error("New chat error:", err);
    }
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
    input.style.height = "auto";
    appendBubble(text, "user");
    setUiBusy(true);

    const connectingEl = appendStatus("Connecting…");

    let api;
    try {
      api = await waitForBridge();
      removeStatus();
    } catch (_err) {
      connectingEl.textContent = "⚠️ Could not connect to TaskPal bridge.";
      setUiBusy(false);
      return;
    }

    try {
      const response = await api.send_message(text);
      let parsed = null;
      try { parsed = JSON.parse(response); } catch (_) {}

      if (parsed && parsed.message && parsed.agenda) {
        const row = document.createElement("div");
        row.className = "bubble-row assistant";
        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.innerHTML = renderMarkdown(parsed.message);
        parsed.agenda.forEach(function (item) {
          const itemLabel = document.createElement("div");
          itemLabel.className = "agenda-label";
          itemLabel.textContent = (item.emoji ? item.emoji + " " : "") + item.label;
          bubble.appendChild(itemLabel);
          bubble.appendChild(createReminderButtons(item.label));
        });
        row.appendChild(bubble);
        transcript.appendChild(row);
        transcript.scrollTop = transcript.scrollHeight;
      } else {
        appendBubble(response, "assistant");
      }
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

  input.addEventListener("input", autoResize);

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  newChatBtn.addEventListener("click", startNewChat);

  input.focus();

  window.injectAssistantMessage = function (payload) {
    let text, buttons = [];
    try {
      const parsed = JSON.parse(payload);
      text = parsed.message || payload;
      buttons = parsed.buttons || [];
    } catch (_) {
      text = payload;
    }

    const row = document.createElement("div");
    row.className = "bubble-row assistant";

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = renderMarkdown(text);

    // Reminder action buttons
    if (text.startsWith("⏰")) {
      const match = text.match(/^⏰\s+([^—–]+?)\s*[—–]/);
      const label = match ? match[1].trim() : "";
      bubble.appendChild(createReminderButtons(label));
    }

    // Action buttons (e.g. Full / Lazy)
    if (buttons.length > 0) {
      const btnRow = document.createElement("div");
      btnRow.className = "action-btn-row";
      buttons.forEach(function (btnDef) {
        const btn = document.createElement("button");
        btn.className = "action-btn";
        btn.textContent = btnDef.label;
        btn.addEventListener("click", async function () {
          btnRow.querySelectorAll(".action-btn").forEach(b => b.disabled = true);
          try {
            const api = await waitForBridge();
            await api.handle_action(btnDef.action);
          } catch (e) {
            console.error("Action error:", e);
          }
        });
        btnRow.appendChild(btn);
      });
      bubble.appendChild(btnRow);
    }

    row.appendChild(bubble);
    transcript.appendChild(row);
    transcript.scrollTop = transcript.scrollHeight;
  };

  window.updateHeaderFace = function (emoji) {
    const el = document.getElementById("header-face");
    if (el) el.textContent = emoji;
  };

  // ── Header clock ────────────────────────────────────────────────────────

  (function () {
    const clock = document.getElementById("header-clock");
    if (!clock) return;
    var showDate = false;

    function pad(n) { return n < 10 ? "0" + n : "" + n; }

    function update() {
      var now = new Date();
      if (showDate) {
        var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
        var days = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
        clock.textContent = days[now.getDay()] + ", " + months[now.getMonth()] + " " + now.getDate();
      } else {
        var h = now.getHours();
        var ampm = h >= 12 ? "PM" : "AM";
        h = h % 12 || 12;
        clock.textContent = h + ":" + pad(now.getMinutes()) + " " + ampm;
      }
    }

    clock.addEventListener("click", function () {
      showDate = !showDate;
      update();
    });

    update();
    setInterval(update, 1000);
  })();
})();
