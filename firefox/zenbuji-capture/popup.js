// zenbuji caption capture — toolbar popup. A single on/off toggle + a count of
// the lines sent this Firefox session.

const btn = document.getElementById("toggle");
const count = document.getElementById("count");

function render(s) {
  const on = !!(s && s.enabled);
  btn.textContent = on ? "Capturing — tap to stop" : "Start capturing";
  btn.classList.toggle("off", !on);
  const n = (s && s.session) || 0;
  count.textContent = `${n} line${n === 1 ? "" : "s"} sent this session`;
}

async function refresh() {
  render(await browser.runtime.sendMessage({ kind: "getStatus" }));
}

btn.addEventListener("click", async () => {
  const cur = await browser.runtime.sendMessage({ kind: "getStatus" });
  await browser.runtime.sendMessage({
    kind: "setEnabled",
    enabled: !(cur && cur.enabled),
  });
  refresh();
});

refresh();
