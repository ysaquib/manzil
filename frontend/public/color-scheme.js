try {
  var stored = window.localStorage.getItem("manzil-color-scheme");
  var colorScheme =
    stored === "light" || stored === "dark" || stored === "auto" ? stored : "auto";
  var computed =
    colorScheme !== "auto"
      ? colorScheme
      : window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
  document.documentElement.setAttribute("data-mantine-color-scheme", computed);
} catch (_error) {
  // Storage can be unavailable in hardened/private browser contexts. Mantine
  // will apply its normal default after mount.
}
