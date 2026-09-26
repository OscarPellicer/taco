export function normalizedDatasetUrl(value) {
  const text = String(value ?? "").trim();
  if (!text) throw new Error("Enter a TACO dataset URL.");
  const url = new URL(text);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("The dataset URL must use HTTP or HTTPS.");
  }
  if (url.hostname === "source.coop" || url.hostname === "www.source.coop") {
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.length < 2) throw new Error("Enter a Source Cooperative product URL.");
    url.protocol = "https:";
    url.hostname = "data.source.coop";
    url.port = "";
    url.search = "";
    url.hash = "";
  } else if (url.hostname === "huggingface.co" || url.hostname === "www.huggingface.co") {
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts[0] !== "datasets" || parts.length < 3) {
      throw new Error("Enter a Hugging Face dataset URL.");
    }
    const route = parts[3];
    if (!route) {
      parts.push("resolve", "main");
    } else if (route === "tree" || route === "blob") {
      if (!parts[4]) throw new Error("The Hugging Face URL is missing a revision.");
      parts[3] = "resolve";
    } else if (route !== "resolve") {
      throw new Error("Enter a Hugging Face dataset or file URL.");
    }
    url.protocol = "https:";
    url.hostname = "huggingface.co";
    url.port = "";
    url.pathname = `/${parts.join("/")}`;
    if (route !== "resolve") url.search = "";
    url.hash = "";
  }
  return url.href;
}
